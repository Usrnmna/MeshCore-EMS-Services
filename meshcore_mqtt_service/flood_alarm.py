"""Persistent flood subscriptions. SQLite stays on the event-loop thread.

ALGORITHM MAP: remember = enrollment/renewal; check_one = comparison;
is_current = stale-result/expiry guard; run = scheduler. No background OS service.
"""
import asyncio
import json
import logging
import time

LOG = logging.getLogger('flood_alarm')

# TWEAK HERE: seconds between readings and maximum time since an accepted !floodalarm.
CHECK_INTERVAL = 20 * 60
MAX_AGE = 4 * 60 * 60
POLL_SECONDS = 1
ACKNOWLEDGMENT = 'Flood Alarm is set for requested location.'


class FloodAlarms:
    def __init__(self, db, channel, read_status, notify, clock=time.time):
        """Reuse runtime/bridge.sqlite3; callbacks perform bounded lookup and tagged send."""
        self.db, self.channel = db, channel
        self.read_status, self.notify, self.clock = read_status, notify, clock
        db.execute('''CREATE TABLE IF NOT EXISTS flood_subscriptions (
            channel TEXT, sender TEXT, location TEXT, last_heard REAL,
            sender_timestamp INTEGER, revision TEXT, enabled INTEGER, ready INTEGER,
            next_check REAL, baseline TEXT, checked_at REAL, error TEXT,
            PRIMARY KEY (channel, sender))''')
        db.commit()

    def row(self, sender):
        """Return one subscription as a dict without changing the shared DB row factory."""
        cursor = self.db.execute('SELECT * FROM flood_subscriptions WHERE channel=? AND sender=?',
                                 (self.channel, sender))
        values = cursor.fetchone()
        return dict(zip((column[0] for column in cursor.description), values)) if values else None

    def remember(self, request, now):
        """Start/update one user's alarm; each !floodalarm replaces location and resets expiry."""
        # COMMAND OWNERSHIP: one-shot !floodwarn calls must never change an alarm.
        if request['command'] != '!floodalarm':
            return False
        old = self.row(request['sender'])
        # Delayed radio messages must not replace a newer requested location.
        if old and request['sender_timestamp'] < old['sender_timestamp']:
            return False
        active = bool(old and old['enabled'] and now < old['last_heard'] + MAX_AGE)
        location = request['arguments'][0]
        keep_reading = active and old['location'] == location
        # RENEWAL: overwrite this user's row and last_heard, even for the same location.
        # Retain a same-location baseline; a changed location needs a fresh baseline.
        self.db.execute('''INSERT OR REPLACE INTO flood_subscriptions
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (
            self.channel, request['sender'], location, now, request['sender_timestamp'],
            request['id'], 1, 0,
            old['next_check'] if keep_reading else now,
            old['baseline'] if keep_reading else None,
            old['checked_at'] if keep_reading else None,
            old['error'] if keep_reading else None))
        self.db.commit()
        return True

    def acknowledge(self, request):
        """Allow the first lookup only AFTER the reply was sent; ignore superseded requests."""
        self.db.execute('''UPDATE flood_subscriptions SET ready=1
            WHERE channel=? AND sender=? AND revision=? AND enabled=1''',
            (self.channel, request['sender'], request['id']))
        self.db.commit()

    def is_current(self, reading):
        """Recheck after HTTP and inside the radio queue: no expired/old-location notifications."""
        current = self.row(reading['sender'])
        return bool(current and current['enabled'] and current['ready']
                    and current['revision'] == reading['revision']
                    and self.clock() < current['last_heard'] + MAX_AGE)

    async def check_one(self):
        """Read one due subscription; silently save baseline, then report type-set changes only."""
        now = self.clock()
        # EXPIRY: retain the last location for review, but stop checks at exactly four hours.
        self.db.execute('UPDATE flood_subscriptions SET enabled=0 WHERE last_heard<=?', (now - MAX_AGE,))
        due = self.db.execute('''SELECT sender FROM flood_subscriptions
            WHERE channel=? AND enabled=1 AND ready=1 AND next_check<=?
            ORDER BY next_check, sender LIMIT 1''', (self.channel, now)).fetchone()
        self.db.commit()
        if due is None:
            return False
        reading = self.row(due[0])
        # Schedule before awaiting: a restart/failure does not cause a rapid retry loop.
        self.db.execute('''UPDATE flood_subscriptions SET next_check=?
            WHERE channel=? AND sender=?''', (now + CHECK_INTERVAL, self.channel, reading['sender']))
        self.db.commit()
        try:
            result = await self.read_status(reading['location'])
        except Exception as exc:
            # OUTAGE: preserve the last GOOD reading; one notice per failure episode.
            if self.is_current(reading):
                self.db.execute('''UPDATE flood_subscriptions SET error=?
                    WHERE channel=? AND sender=?''', (str(exc), self.channel, reading['sender']))
                self.db.commit()
                LOG.warning('Flood lookup failed for %s: %s', reading['sender'], exc)
                if reading['error'] is None:
                    await self.notify(reading, f"Flood Alarm for {reading['location']}: {exc}")
            return True
        if not self.is_current(reading):
            return True
        # CHANGE DETECTION: order/duplicate IDs/timestamps are irrelevant; compare alert types.
        status = json.dumps(sorted(set(result['events'])))
        changed = reading['baseline'] is not None and status != reading['baseline']
        self.db.execute('''UPDATE flood_subscriptions SET baseline=?, checked_at=?, error=NULL
            WHERE channel=? AND sender=?''', (status, self.clock(), self.channel, reading['sender']))
        self.db.commit()
        # Commit before sending: interrupted/failed sends are logged, not blindly repeated.
        if changed:
            await self.notify(reading, result['text'])
        return True

    async def run(self):
        """One bounded lookup at a time, alongside the independent immediate-reply worker."""
        while True:
            try:
                worked = await self.check_one()
            except Exception:
                LOG.exception('Flood alarm check/send failed')
                worked = False
            await asyncio.sleep(0 if worked else POLL_SECONDS)
