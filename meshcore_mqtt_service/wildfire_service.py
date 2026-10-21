"""Service-owned wildfire refresh and persistent, channel-scoped subscriptions."""

import asyncio
import json
import logging
import time

from scripts.wildfire_settings import validate

LOG = logging.getLogger("wildfire")


async def refresh_loop(root, config):
    """Run one bounded child refresh per service session; SQLite excludes other writers."""
    from responder import run_script
    request = dict(sender="Wildfire refresh", channel_name="", channel_index=-1,
                   id="wildfire-refresh", phrase="", arguments=[])
    while True:
        try:
            output, detail = await run_script(
                root, dict(script="scripts/wildfire_refresh.py", timeout=300), request,
                dict(config, max_output_bytes=max(65536, config["max_output_bytes"])))
            if detail:
                LOG.warning("Wildfire refresh: %s", detail)
            else:
                result = json.loads(output)
                failed = [k for k, v in result.items() if isinstance(v, dict) and not v.get("ok")]
                if failed:
                    LOG.warning("Wildfire sources unavailable: %s", ", ".join(failed))
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("Wildfire refresh unavailable")
        await asyncio.sleep(60)


def changes(old, new, config):
    """Compare against the last notified baseline; disappearance never implies containment."""
    messages = []
    before, after = old["incidents"], new["incidents"]
    for key in sorted(after.keys() - before.keys()):
        messages.append("Newly reported: " + str(after[key]["name"]))
    for key in sorted(before.keys() - after.keys()):
        messages.append(str(before[key]["name"]) + " no longer listed; status unconfirmed")
    for key in sorted(before.keys() & after.keys()):
        left, right = before[key], after[key]
        for field, threshold, unit in (("acres", config["acreage_change"], "ac"),
                                       ("containment", config["containment_change"], "% contained")):
            a, b = left[field], right[field]
            if a != b and (a is None or b is None or abs(b - a) >= threshold or
                           (field == "containment" and b == 100)):
                messages.append(f"{right['name']}: {field} now " + ("not reported" if b is None else f"{b:g} {unit}"))
        if left["perimeter"] != right["perimeter"]:
            messages.append(str(right["name"]) + (" mapped perimeter available" if right["perimeter"] else " perimeter unavailable"))
    for key in sorted(new["alerts"]):
        if old["alerts"].get(key) != new["alerts"][key]:
            messages.append("New/updated " + new["alerts"][key]["event"])
    for key in sorted(old["alerts"].keys() - new["alerts"].keys()):
        messages.append(old["alerts"][key]["event"] + " no longer active in current feed")
    return messages


class WildfireAlarms:
    """Persist subscription control in the existing bridge database, on its event-loop thread."""

    def __init__(self, db, channel, identity, config, read, notify, allowed, clock=time.time):
        self.db, self.channel, self.identity = db, channel, identity
        self.config, self.read, self.notify, self.allowed, self.clock = validate(config), read, notify, allowed, clock
        db.execute("""CREATE TABLE IF NOT EXISTS wildfire_subscriptions(
            channel TEXT, sender TEXT, identity TEXT, revision TEXT, sender_timestamp INTEGER,
            expires REAL, enabled INTEGER, ready INTEGER, target TEXT, zones TEXT,
            baseline TEXT, next_check REAL, error TEXT, PRIMARY KEY(channel,sender))""")
        db.execute("UPDATE wildfire_subscriptions SET enabled=0 WHERE channel=? AND identity IS NOT ?",
                   (channel, identity))
        if not allowed() or not self.config["enabled"]:
            db.execute("UPDATE wildfire_subscriptions SET enabled=0 WHERE channel=?", (channel,))
        db.commit()

    def row(self, sender):
        cursor = self.db.execute("SELECT * FROM wildfire_subscriptions WHERE channel=? AND sender=?",
                                 (self.channel, sender))
        value = cursor.fetchone()
        return dict(zip((c[0] for c in cursor.description), value)) if value else None

    def remember(self, request, now):
        """Reserve a revision at acceptance; off cancels even while an older lookup is pending."""
        from scripts.wildfire_lookup import parse_query
        query = parse_query("firealarm", request["arguments"][0])
        if query["action"] not in {"on", "off"}:
            return True
        old = self.row(request["sender"])
        if old and request["sender_timestamp"] <= old["sender_timestamp"]:
            return False
        self.db.execute("""INSERT OR REPLACE INTO wildfire_subscriptions
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (self.channel, request["sender"], self.identity, request["id"], request["sender_timestamp"],
             now + self.config["subscription_hours"] * 3600, 0, 0, query["target"], None, None, now, None))
        self.db.commit()
        return True

    def current(self, reading):
        """Recheck identity, expiry, assignment and revision after awaits and queued radio sends."""
        row = self.row(reading["sender"])
        return bool(self.allowed() and self.config["enabled"] and row and row["enabled"] and row["ready"]
                    and row["identity"] == self.identity and row["revision"] == reading["revision"]
                    and self.clock() < row["expires"])

    async def control(self, request):
        """Resolve and baseline an enrollment, or inspect/cancel it; readiness waits for acknowledgment."""
        from scripts.wildfire_lookup import parse_query
        query = parse_query("firealarm", request["arguments"][0])
        row = self.row(request["sender"])
        if query["action"] == "help":
            return "Use !firealarm on ZONE/LOCATION, status, or off.", ""
        if query["action"] == "off":
            return "Wildfire monitoring stopped.", ""
        if query["action"] == "status":
            if not row or not self.current(row):
                return "No active wildfire subscription.", ""
            return (f"Wildfire monitoring {', '.join(json.loads(row['zones']))}; "
                    f"{max(0, int((row['expires'] - self.clock()) / 60))} minutes remaining."
                    + (" Data unavailable; retaining previous baseline." if row["error"] else ""), "")
        if not self.config["enabled"]:
            return "Wildfire monitoring is disabled in configuration.", ""
        if not row or row["revision"] != request["id"]:
            return "Wildfire request superseded.", ""
        try:
            snapshot = await self.read(query["target"])
        except Exception as exc:
            return "Wildfire monitoring was not started: " + str(exc), str(exc)
        row = self.row(request["sender"])
        if not row or row["revision"] != request["id"] or self.clock() >= row["expires"]:
            return "Wildfire request expired or superseded.", ""
        self.db.execute("""UPDATE wildfire_subscriptions SET enabled=1,zones=?,baseline=?,next_check=?
            WHERE channel=? AND sender=? AND revision=?""",
            (json.dumps(snapshot["zones"]), json.dumps(snapshot),
             self.clock() + self.config["subscription_interval"], self.channel, request["sender"], request["id"]))
        self.db.commit()
        return (f"Wildfire monitoring set for {', '.join(snapshot['zones'])}; "
                f"{self.config['subscription_hours']:g} hours. Baseline: {len(snapshot['incidents'])} incident records, "
                f"{len(snapshot['alerts'])} fire-weather alerts. Use !fires/!firewarn for details; !firealarm off to stop.", "")

    def control_current(self, request):
        """Prevent a superseded on/off acknowledgment from leaving the radio queue."""
        from scripts.wildfire_lookup import parse_query
        action = parse_query("firealarm", request["arguments"][0])["action"]
        if action not in {"on", "off"}:
            return self.allowed()
        row = self.row(request["sender"])
        return bool(self.allowed() and row and row["revision"] == request["id"]
                    and (action == "off" or self.clock() < row["expires"]))

    def acknowledge(self, request):
        self.db.execute("""UPDATE wildfire_subscriptions SET ready=1
            WHERE channel=? AND sender=? AND revision=? AND enabled=1""",
            (self.channel, request["sender"], request["id"]))
        self.db.commit()

    async def check_one(self):
        """Preserve the baseline on outage; emit one outage/recovery notice and meaningful changes."""
        now = self.clock()
        self.db.execute("UPDATE wildfire_subscriptions SET enabled=0 WHERE expires<=?", (now,))
        if not self.allowed() or not self.config["enabled"]:
            self.db.execute("UPDATE wildfire_subscriptions SET enabled=0 WHERE channel=?", (self.channel,))
        self.db.commit()
        due = self.db.execute("""SELECT sender FROM wildfire_subscriptions
            WHERE channel=? AND enabled=1 AND ready=1 AND next_check<=? ORDER BY next_check LIMIT 1""",
            (self.channel, now)).fetchone()
        if not due:
            return False
        reading = self.row(due[0])
        self.db.execute("UPDATE wildfire_subscriptions SET next_check=? WHERE channel=? AND sender=?",
                        (now + self.config["subscription_interval"], self.channel, reading["sender"]))
        self.db.commit()
        try:
            snapshot = await self.read(json.loads(reading["zones"]))
        except Exception as exc:
            if self.current(reading):
                self.db.execute("UPDATE wildfire_subscriptions SET error=? WHERE channel=? AND sender=?",
                                (str(exc), self.channel, reading["sender"]))
                self.db.commit()
                if reading["error"] is None:
                    await self.notify(reading, "Wildfire monitoring data unavailable; previous status retained. " + str(exc))
            return True
        if not self.current(reading):
            return True
        messages = changes(json.loads(reading["baseline"]), snapshot, self.config)
        if reading["error"]:
            messages.insert(0, "Wildfire monitoring data available again")
        # Commit before delivery to avoid replaying possibly delivered messages after restart.
        self.db.execute("""UPDATE wildfire_subscriptions SET baseline=?,error=NULL
            WHERE channel=? AND sender=?""",
            (json.dumps(snapshot) if messages else reading["baseline"], self.channel, reading["sender"]))
        self.db.commit()
        if messages:
            await self.notify(reading, "Wildfire " + ", ".join(snapshot["zones"]) + ": " + "; ".join(messages))
        return True

    async def run(self):
        while True:
            try:
                worked = await self.check_one()
            except Exception:
                LOG.exception("Wildfire subscription check/delivery failed")
                worked = False
            await asyncio.sleep(0 if worked else 1)
