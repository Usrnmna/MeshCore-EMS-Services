"""Location-pinned flood subscriptions owned by the existing service/event loop."""

import asyncio
import json
import logging
import time

from scripts.water_lookup import (
    checked_snapshot,
    compact,
    condition_summary,
    parse_query,
)
from scripts.water_changes import changes
from scripts.water_notifications import (
    active_notice,
    format_notification,
    official_notifications,
    priority,
    status_notice,
)
from scripts.water_settings import validate

LOG = logging.getLogger("flood")
NOTIFICATION_PAUSE_SECONDS = 5.0


from scripts.response_text import compact_fields, short_label

class FloodAlarms:
    """Keep channel/sender subscriptions in bridge.sqlite3; network work runs through bounded callbacks."""

    def __init__(
        self,
        db,
        channel,
        identity,
        config,
        read,
        notify,
        allowed,
        clock=time.time,
        monotonic=time.monotonic,
    ):
        """Create persistent state and disable subscriptions whose channel identity or assignment changed."""
        self.db, self.channel, self.identity = db, channel, identity
        self.config = validate(config)
        self.read, self.notify, self.allowed, self.clock = read, notify, allowed, clock
        self.monotonic = monotonic
        self.pending = {}
        self.initial_notices = {}
        self.next_send = 0.0
        db.execute(
            """CREATE TABLE IF NOT EXISTS flood_location_subscriptions(
            channel TEXT, sender TEXT, identity TEXT, revision TEXT, sender_timestamp INTEGER,
            expires REAL, enabled INTEGER, ready INTEGER, target TEXT, point TEXT, mode TEXT,
            baseline TEXT, next_check REAL, error TEXT, PRIMARY KEY(channel,sender))"""
        )
        db.execute(
            "UPDATE flood_location_subscriptions SET enabled=0 WHERE channel=? AND identity IS NOT ?",
            (channel, identity),
        )
        if not allowed() or not self.config["enabled"]:
            db.execute(
                "UPDATE flood_location_subscriptions SET enabled=0 WHERE channel=?",
                (channel,),
            )
        legacy = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='flood_subscriptions'"
        ).fetchone()
        if legacy:
            for row in db.execute(
                "SELECT channel,sender,location,last_heard,sender_timestamp,revision,enabled,ready,next_check FROM flood_subscriptions WHERE channel=?",
                (channel,),
            ).fetchall():
                db.execute(
                    "INSERT OR IGNORE INTO flood_location_subscriptions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        row[0],
                        row[1],
                        identity,
                        row[5],
                        row[4],
                        row[3] + 4 * 3600,
                        row[6],
                        row[7],
                        row[2],
                        None,
                        "alerts",
                        None,
                        row[8],
                        None,
                    ),
                )
            db.execute(
                "UPDATE flood_subscriptions SET enabled=0 WHERE channel=?", (channel,)
            )
        if not allowed() or not self.config["enabled"]:
            db.execute(
                "UPDATE flood_location_subscriptions SET enabled=0 WHERE channel=?",
                (channel,),
            )
        db.commit()

    def row(self, sender):
        """Read one subscription without changing the shared connection's row factory."""
        cursor = self.db.execute(
            "SELECT * FROM flood_location_subscriptions WHERE channel=? AND sender=?",
            (self.channel, sender),
        )
        row = cursor.fetchone()
        return dict(zip((c[0] for c in cursor.description), row)) if row else None

    def remember(self, request, now):
        """Reserve ordered subscribe/stop revisions at acceptance; stop invalidates pending lookups immediately."""
        if request["command"] != "!floodalarm" or not self.allowed():
            return False
        query = parse_query("floodalarm", request["arguments"][0])
        if query["action"] not in {"subscribe", "stop"}:
            return True
        old = self.row(request["sender"])
        if old and request["sender_timestamp"] <= old["sender_timestamp"]:
            return False
        # Reservation immediately invalidates queued output from the previous revision.
        for key in list(self.pending):
            if key[0] == request["sender"]:
                del self.pending[key]
        for key in list(self.initial_notices):
            if key[0] == request["sender"]:
                del self.initial_notices[key]
        self.db.execute(
            "INSERT OR REPLACE INTO flood_location_subscriptions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.channel,
                request["sender"],
                self.identity,
                request["id"],
                request["sender_timestamp"],
                now + self.config["subscription_hours"] * 3600,
                0,
                0,
                query["target"],
                None,
                query["mode"],
                None,
                now,
                None,
            ),
        )
        self.db.commit()
        return True

    def current(self, reading):
        """Recheck expiry, identity, revision and assignment after awaits and inside the radio queue."""
        row = self.row(reading["sender"])
        return bool(
            self.allowed()
            and self.config["enabled"]
            and row
            and row["enabled"]
            and row["ready"]
            and row["identity"] == self.identity
            and row["revision"] == reading["revision"]
            and self.clock() < row["expires"]
        )

    def control_current(self, request):
        """Suppress obsolete control acknowledgments while allowing status/help without enrollment."""
        action = parse_query("floodalarm", request["arguments"][0])["action"]
        if action not in {"subscribe", "stop"}:
            return self.allowed()
        row = self.row(request["sender"])
        return bool(
            self.allowed()
            and row
            and row["identity"] == self.identity
            and row["revision"] == request["id"]
            and (action == "stop" or self.clock() < row["expires"])
        )

    async def control(self, request):
        """Baseline an enrollment before acknowledgment; keep monitoring disabled on lookup failure."""
        query = parse_query("floodalarm", request["arguments"][0])
        row = self.row(request["sender"])
        if query["action"] == "help":
            return (
                "Use !floodalarm LOCATION, conditions LOCATION, status, or stop. Coordinates, ZIP, or city [state]; bare cities default CA.",
                "",
            )
        if query["action"] == "stop":
            return "Flood monitoring stopped.", ""
        if query["action"] == "status":
            if not row or not self.current(row):
                return "No active flood subscription.", ""
            baseline = json.loads(row["baseline"]) if row["baseline"] else {}
            unavailable = [
                v["label"] + ": " + v["state"]
                for key, v in baseline.get("conditions", {}).items()
                if v["state"]
                in {
                    "unavailable",
                    "stale",
                    "invalid",
                    "future",
                    "out_of_service",
                    "stale_or_unverified_time",
                    "threshold_unavailable",
                    "outside_published_domain",
                }
            ]
            if baseline.get("official_status") == "unavailable":
                unavailable.insert(0, "NWS unavailable")
            status = "Flood monitoring active."
            if row["error"] or unavailable:
                status += " Data limited; status may be unknown."
            return compact_fields(status, [f"{max(0, int((row['expires']-self.clock())/60))}m left", row["mode"], short_label(row["target"], 25)]), ""
        if not self.config["enabled"]:
            return "Flood monitoring is disabled in configuration.", ""
        if not self.control_current(request):
            return "Flood request expired or superseded.", ""
        try:
            snapshot = checked_snapshot(
                await self.read(query["target"], query["mode"]),
                self.config,
                self.clock(),
            )
            if snapshot["official"]["status"] != "available":
                raise ValueError("NWS location coverage/alerts unavailable")
        except Exception as exc:
            return "Flood monitoring was not started: " + str(exc), str(exc)
        if not self.control_current(request):
            return "Flood request expired or superseded.", ""
        self.db.execute(
            """UPDATE flood_location_subscriptions SET enabled=1,point=?,baseline=?,next_check=?
            WHERE channel=? AND sender=? AND revision=?""",
            (
                json.dumps(snapshot["point"]),
                json.dumps(compact(snapshot)),
                self.clock() + self.config["subscription_interval"],
                self.channel,
                request["sender"],
                request["id"],
            ),
        )
        self.db.commit()
        self.initial_notices[(request["sender"], request["id"])] = (
            official_notifications(None, snapshot, self.clock()),
            snapshot["official"]["data"].get("fetched", snapshot["fetched"]),
        )
        return compact_fields(
            f"Flood monitoring set; {self.config['subscription_hours']:g}h. Stop: !floodalarm stop.",
            [short_label(query["target"], 25), query["mode"],
             condition_summary(snapshot["conditions"]) if query["mode"] == "conditions" else ""]), ""


    def acknowledge(self, request):
        """Permit scheduled checks only after all acknowledgment parts have been sent."""
        self.db.execute(
            """UPDATE flood_location_subscriptions SET ready=1
            WHERE channel=? AND sender=? AND revision=? AND enabled=1""",
            (self.channel, request["sender"], request["id"]),
        )
        self.db.commit()
        initial = self.initial_notices.pop((request["sender"], request["id"]), None)
        if initial:
            reading = self.row(request["sender"])
            if reading and self.current(reading):
                self.queue_notices(reading, *initial)

    def queue_notices(self, reading, notices, checked_at):
        """Replace pending notices by sender/revision/key; queued state is current-only and in memory."""
        for notice in notices:
            key = (reading["sender"], reading["revision"], notice["key"])
            self.pending[key] = {
                "reading": reading,
                "notice": notice,
                "checked_at": checked_at,
            }

    def reconcile_pending(self, reading, snapshot):
        """Refresh queued evidence and follow replacement IDs even when content is unchanged."""
        current = snapshot["official"].get("data", {}).get("alerts", {})
        checked_at = (
            snapshot["official"].get("data", {}).get("fetched", snapshot["fetched"])
        )
        for key, item in list(self.pending.items()):
            if key[:2] != (reading["sender"], reading["revision"]):
                continue
            notice = item["notice"]
            if notice["kind"] == "alert" and notice["alert"]["id"] not in current:
                old_id = notice["alert"]["id"]
                successors = [a for a in current.values() if old_id in a["references"]]
                if len(successors) == 1:
                    del self.pending[key]
                    self.queue_notices(
                        reading,
                        [active_notice(successors[0], notice["change"])],
                        checked_at,
                    )
                    continue
            item["checked_at"] = checked_at
            if not self.notice_valid(item):
                self.pending.pop(key, None)

    def notice_valid(self, item):
        """Reject obsolete source state, expired alerts and invalid subscriptions without network I/O."""
        reading, notice = item["reading"], item["notice"]
        if not self.current(reading):
            return False
        row = self.row(reading["sender"])
        baseline = json.loads(row["baseline"]) if row["baseline"] else {}
        available = not row["error"] and baseline.get("official_status") == "available"
        if notice["kind"] == "status":
            return available == notice["available"] and (
                notice["alert_ids"] is None
                or sorted(baseline.get("alerts", {})) == notice["alert_ids"]
            )
        if row["error"]:
            return False
        if notice["kind"] == "derived":
            return baseline.get("conditions") == notice["conditions"]
        if not available:
            return False
        alerts = baseline.get("alerts", {})
        if notice["kind"] == "lifecycle":
            return notice["alert_id"] not in alerts and not any(
                notice["alert_id"] in a.get("references", []) for a in alerts.values()
            )
        alert = notice["alert"]
        latest = alerts.get(alert["id"], {})
        return (
            latest.get("fingerprint") == alert["fingerprint"]
            and alert["effective"] <= self.clock() < alert["expires"]
        )

    def notification_current(self, reading):
        """Guard each radio chunk after the shared send-slot wait, including source freshness."""
        item = reading.get("_notification")
        if item is None:
            return self.current(reading)
        key = (reading["sender"], reading["revision"], item["notice"]["key"])
        return (
            self.pending.get(key) is item
            and self.notice_valid(item)
            and self.notification_fresh(item)
        )

    def notification_fresh(self, item):
        """Outage notices describe unknown state; other notices require a recent source check."""
        notice = item["notice"]
        if notice["kind"] == "status" and not notice["available"]:
            return True
        return 0 <= self.clock() - item["checked_at"] <= self.config["cache_seconds"]

    async def send_one(self):
        """Send one independent response; the five-second gap begins after all its chunks finish."""
        for key, item in list(self.pending.items()):
            if not self.notice_valid(item):
                self.pending.pop(key, None)
        if not self.pending or self.monotonic() < self.next_send:
            return False
        ordered = sorted(
            self.pending.items(),
            key=lambda pair: (priority(pair[1]["notice"]), pair[0]),
        )
        for key, item in ordered:
            if self.notification_fresh(item):
                break
            # Polling continues while delivery waits for fresh evidence. No stale
            # notification is silently promoted to a current observation.
            self.db.execute(
                "UPDATE flood_location_subscriptions SET next_check=MIN(next_check,?) WHERE channel=? AND sender=?",
                (self.clock(), self.channel, item["reading"]["sender"]),
            )
            self.db.commit()
        else:
            return False
        reading = dict(item["reading"], _notification=item)
        try:
            await self.notify(
                reading,
                format_notification(item["notice"], reading["target"], self.clock()),
            )
        finally:
            # Preserve the existing no-replay policy for uncertain radio sends.
            if self.pending.get(key) is item:
                del self.pending[key]
            self.next_send = self.monotonic() + NOTIFICATION_PAUSE_SECONDS
        return True

    async def check_one(self):
        """Check one due fixed point; retain baselines on failure and report outage/recovery once."""
        now = self.clock()
        self.db.execute(
            "UPDATE flood_location_subscriptions SET enabled=0 WHERE expires<=?", (now,)
        )
        if not self.allowed() or not self.config["enabled"]:
            self.db.execute(
                "UPDATE flood_location_subscriptions SET enabled=0 WHERE channel=?",
                (self.channel,),
            )
        self.db.commit()
        due = self.db.execute(
            """SELECT sender FROM flood_location_subscriptions
            WHERE channel=? AND enabled=1 AND ready=1 AND next_check<=? ORDER BY next_check LIMIT 1""",
            (self.channel, now),
        ).fetchone()
        if not due:
            return False
        reading = self.row(due[0])
        self.db.execute(
            "UPDATE flood_location_subscriptions SET next_check=? WHERE channel=? AND sender=?",
            (
                now + self.config["subscription_interval"],
                self.channel,
                reading["sender"],
            ),
        )
        self.db.commit()
        try:
            point = json.loads(reading["point"]) if reading["point"] else None
            target = " ".join(map(str, point)) if point else reading["target"]
            snapshot = checked_snapshot(
                await self.read(target, reading["mode"]), self.config, self.clock()
            )
            if point is None and snapshot["official"]["status"] != "available":
                raise ValueError("Legacy location coverage verification unavailable")
            if point is not None and snapshot["point"] != point:
                raise ValueError("Flood monitor location changed unexpectedly")
        except Exception as exc:
            if self.current(reading):
                self.db.execute(
                    "UPDATE flood_location_subscriptions SET error=? WHERE channel=? AND sender=?",
                    (str(exc), self.channel, reading["sender"]),
                )
                self.db.commit()
                if reading["error"] is None:
                    self.queue_notices(
                        reading,
                        [
                            status_notice(
                                "NWS alerts unavailable; status unknown.", False
                            )
                        ],
                        self.clock(),
                    )
            return True
        if not self.current(reading):
            return True
        old = json.loads(reading["baseline"]) if reading["baseline"] else None
        comparison = old
        if reading["error"]:
            comparison = dict(
                old or {"alerts": {}, "conditions": {}}, official_status="unavailable"
            )
        baseline, notices = changes(comparison, snapshot, self.clock(), structured=True)
        # Commit before delivery, matching the service's policy against replay of uncertain sends.
        self.db.execute(
            "UPDATE flood_location_subscriptions SET baseline=?,point=?,error=NULL WHERE channel=? AND sender=?",
            (
                json.dumps(baseline),
                json.dumps(snapshot["point"]),
                self.channel,
                reading["sender"],
            ),
        )
        self.db.commit()
        self.reconcile_pending(reading, snapshot)
        self.queue_notices(
            reading,
            notices,
            snapshot["official"].get("data", {}).get("fetched", snapshot["fetched"]),
        )
        return True

    async def poll(self):
        """Poll independently of notification delays and radio transmission waits."""
        while True:
            try:
                worked = await self.check_one()
            except Exception:
                LOG.exception("Flood subscription check/delivery failed")
                worked = False
            await asyncio.sleep(0 if worked else 1)

    async def deliver(self):
        """Serialize independent responses on this channel without blocking polling."""
        while True:
            try:
                worked = await self.send_one()
            except Exception:
                LOG.exception("Flood notification delivery failed")
                worked = False
            await asyncio.sleep(0 if worked else 0.1)

    async def run(self):
        """Keep polling and paced delivery in the existing service's task lifetime."""
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(self.poll())
            tasks.create_task(self.deliver())
