"""Temporary California/Nevada alert subscriptions owned by the existing service/event loop."""

import asyncio
import json
import logging
import time

from scripts.landslide_lookup import alert_summary, checked_snapshot, format_alerts, parse_query
from scripts.landslide_settings import validate
from scripts.response_text import compact_fields, short_label

LOG = logging.getLogger("landslide")


def changes(before, after, now):
    """Compare CAP content and references; distinguish expiry/cancellation from feed disappearance."""
    old, new = before["alerts"], after["alerts"]
    messages, replaced = [], set()
    for key, alert in new.items():
        references = set(alert["references"]) & old.keys()
        previous = old.get(key)
        if previous is None and references:
            previous = old[sorted(references)[0]]
        replaced.update(references)
        if previous is None or previous["fingerprint"] != alert["fingerprint"]:
            messages.append(alert_summary(alert).split(" | ")[0] + " | " + ("New" if previous is None else "Updated"))
    for key in old.keys() - new.keys() - replaced:
        if key in after.get("cancelled_ids", []):
            reason = "cancelled by NWS"
        elif now >= old[key]["expires"]:
            reason = "expired"
        else:
            reason = "unlisted; cancellation unconfirmed"
        if key not in after.get("cancelled_ids", []) and now < old[key]["expires"]:
            messages.append("NWS alert unlisted; cancellation unconfirmed. Not an all-clear. | " + old[key]["event"])
        else:
            messages.append(old[key]["event"] + " " + reason + "; not an all-clear.")
    return messages


class LandslideAlarms:
    """Keep channel/sender subscriptions in bridge.sqlite3; network work runs through bounded callbacks."""

    def __init__(self, db, channel, identity, config, read, notify, allowed, clock=time.time):
        """Create persistent state and disable subscriptions whose channel identity or assignment changed."""
        self.db, self.channel, self.identity = db, channel, identity
        self.config = validate(config)
        self.read, self.notify, self.allowed, self.clock = read, notify, allowed, clock
        db.execute("""CREATE TABLE IF NOT EXISTS landslide_subscriptions(
            channel TEXT, sender TEXT, identity TEXT, revision TEXT, sender_timestamp INTEGER,
            expires REAL, enabled INTEGER, ready INTEGER, target TEXT, point TEXT,
            baseline TEXT, next_check REAL, error TEXT, PRIMARY KEY(channel,sender))""")
        db.execute("UPDATE landslide_subscriptions SET enabled=0 WHERE channel=? AND identity IS NOT ?",
                   (channel, identity))
        if not allowed() or not self.config["enabled"]:
            db.execute("UPDATE landslide_subscriptions SET enabled=0 WHERE channel=?", (channel,))
        db.commit()

    def row(self, sender):
        """Read one subscription without changing the shared connection's row factory."""
        cursor = self.db.execute("SELECT * FROM landslide_subscriptions WHERE channel=? AND sender=?",
                                 (self.channel, sender))
        row = cursor.fetchone()
        return dict(zip((c[0] for c in cursor.description), row)) if row else None

    def remember(self, request, now):
        """Reserve ordered on/off revisions at acceptance; off invalidates pending lookups immediately."""
        if request["command"] != "!slidealarm" or not self.allowed():
            return False
        query = parse_query("slidealarm", request["arguments"][0])
        if query["action"] not in {"on", "off"}:
            return True
        old = self.row(request["sender"])
        if old and request["sender_timestamp"] <= old["sender_timestamp"]:
            return False
        self.db.execute("INSERT OR REPLACE INTO landslide_subscriptions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (self.channel, request["sender"], self.identity, request["id"], request["sender_timestamp"],
                         now + self.config["subscription_hours"] * 3600, 0, 0, query["target"], None, None, now, None))
        self.db.commit()
        return True

    def current(self, reading):
        """Recheck expiry, identity, revision and assignment after awaits and inside the radio queue."""
        row = self.row(reading["sender"])
        return bool(self.allowed() and self.config["enabled"] and row and row["enabled"] and row["ready"]
                    and row["identity"] == self.identity and row["revision"] == reading["revision"]
                    and self.clock() < row["expires"])

    def control_current(self, request):
        """Suppress obsolete control acknowledgments while allowing status/help without enrollment."""
        action = parse_query("slidealarm", request["arguments"][0])["action"]
        if action not in {"on", "off"}:
            return self.allowed()
        row = self.row(request["sender"])
        return bool(self.allowed() and row and row["identity"] == self.identity
                    and row["revision"] == request["id"]
                    and (action == "off" or self.clock() < row["expires"]))

    async def control(self, request):
        """Baseline an enrollment before acknowledgment; keep monitoring disabled on lookup failure."""
        query = parse_query("slidealarm", request["arguments"][0])
        row = self.row(request["sender"])
        if query["action"] == "help":
            return "Use !slidealarm on LOCATION, status, or off. California/Nevada ZIP, city [CA/NV], or latitude longitude; bare cities default to CA.", ""
        if query["action"] == "off":
            return "Landslide monitoring stopped.", ""
        if query["action"] == "status":
            if not row or not self.current(row):
                return "No active landslide subscription.", ""
            return compact_fields("Landslide monitoring active." + (" Data unavailable." if row["error"] else ""),
                                  [f"{max(0, int((row['expires']-self.clock())/60))}m left", short_label(row["target"], 25)]), ""
        if not self.config["enabled"]:
            return "Landslide monitoring is disabled in configuration.", ""
        if not self.control_current(request):
            return "Landslide request expired or superseded.", ""
        try:
            snapshot = checked_snapshot(await self.read(query["target"]), self.config, self.clock())
        except Exception as exc:
            return "Landslide monitoring was not started: " + str(exc), str(exc)
        if not self.control_current(request):
            return "Landslide request expired or superseded.", ""
        self.db.execute("""UPDATE landslide_subscriptions SET enabled=1,point=?,baseline=?,next_check=?
            WHERE channel=? AND sender=? AND revision=?""",
                        (json.dumps(snapshot["point"]), json.dumps(snapshot),
                         self.clock() + self.config["subscription_interval"], self.channel, request["sender"], request["id"]))
        self.db.commit()
        return compact_fields(format_alerts(snapshot, query["target"], self.config).split(" | ")[0],
                              [f"Monitoring set {self.config['subscription_hours']:g}h", "Stop: !slidealarm off"]), ""


    def acknowledge(self, request):
        """Permit scheduled checks only after all acknowledgment parts have been sent."""
        self.db.execute("""UPDATE landslide_subscriptions SET ready=1
            WHERE channel=? AND sender=? AND revision=? AND enabled=1""",
                        (self.channel, request["sender"], request["id"]))
        self.db.commit()

    async def check_one(self):
        """Check one due fixed point; retain baselines on failure and report outage/recovery once."""
        now = self.clock()
        self.db.execute("UPDATE landslide_subscriptions SET enabled=0 WHERE expires<=?", (now,))
        if not self.allowed() or not self.config["enabled"]:
            self.db.execute("UPDATE landslide_subscriptions SET enabled=0 WHERE channel=?", (self.channel,))
        self.db.commit()
        due = self.db.execute("""SELECT sender FROM landslide_subscriptions
            WHERE channel=? AND enabled=1 AND ready=1 AND next_check<=? ORDER BY next_check LIMIT 1""",
                             (self.channel, now)).fetchone()
        if not due:
            return False
        reading = self.row(due[0])
        self.db.execute("UPDATE landslide_subscriptions SET next_check=? WHERE channel=? AND sender=?",
                        (now + self.config["subscription_interval"], self.channel, reading["sender"]))
        self.db.commit()
        try:
            point = json.loads(reading["point"])
            snapshot = checked_snapshot(await self.read(" ".join(map(str, point))), self.config, self.clock())
            if snapshot["point"] != point:
                raise ValueError("Landslide monitor location changed unexpectedly")
        except Exception as exc:
            if self.current(reading):
                self.db.execute("UPDATE landslide_subscriptions SET error=? WHERE channel=? AND sender=?",
                                (str(exc), self.channel, reading["sender"]))
                self.db.commit()
                if reading["error"] is None:
                    await self.notify(reading, "Landslide data unavailable; status unknown. Not an all-clear.")
            return True
        if not self.current(reading):
            return True
        messages = changes(json.loads(reading["baseline"]), snapshot, self.clock())
        if reading["error"]:
            messages.insert(0, "Landslide alert data available again")
        # Commit before delivery, matching the service's policy against replay of uncertain sends.
        self.db.execute("UPDATE landslide_subscriptions SET baseline=?,error=NULL WHERE channel=? AND sender=?",
                        (json.dumps(snapshot), self.channel, reading["sender"]))
        self.db.commit()
        for message in messages:
            if not self.current(reading):
                break
            await self.notify(reading, compact_fields(message, [short_label(reading["target"], 25)]))
        return True

    async def run(self):
        """Poll due subscriptions until the parent service cancels this worker."""
        while True:
            try:
                worked = await self.check_one()
            except Exception:
                LOG.exception("Landslide subscription check/delivery failed")
                worked = False
            await asyncio.sleep(0 if worked else 1)
