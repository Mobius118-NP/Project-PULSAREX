import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, RLock, Thread

from .events import EventDetector as EventDetector


@dataclass
class ArchiveClear:
    done: Event = field(default_factory=Event)
    deleted: int = 0
    error: Exception | None = None

    def result(self, timeout=6):
        if not self.done.wait(timeout):
            raise RuntimeError('Archive clearing is still pending; refresh the archive shortly')
        if self.error:
            raise self.error
        return self.deleted


class EventWriter:
    """Bounded persistence worker: a slow disk cannot block live DSP on an event write."""
    def __init__(self, store, warnings, capacity=128):
        self.store, self.warnings = store, warnings
        self.queue = Queue(maxsize=capacity)
        self.stopping = Event()
        self.dropped = 0
        self.thread = Thread(target=self._run, name="pulsarex-event-writer", daemon=True)
        self.thread.start()

    def submit(self, event):
        try:
            self.queue.put_nowait(event)
        except Full:
            self.dropped += 1
            self.warnings['event_queue'] = f"Slow storage: {self.dropped} event updates dropped"

    def request_clear(self):
        request = ArchiveClear()
        try:
            self.queue.put_nowait(request)
        except Full as exc:
            raise RuntimeError('Event storage is busy; retry clearing the archive shortly') from exc
        return request

    def _run(self):
        while not self.stopping.is_set() or not self.queue.empty():
            try:
                event = self.queue.get(timeout=.05)
            except Empty:
                continue
            try:
                if isinstance(event, ArchiveClear):
                    event.deleted = self.store.clear()
                else:
                    self.store.add(event)
                self.warnings.pop('events', None)
            except (OSError, sqlite3.Error) as exc:
                self.warnings['events'] = f"Event persistence unavailable: {exc}"
                if isinstance(event, ArchiveClear):
                    event.error = exc
            finally:
                if isinstance(event, ArchiveClear):
                    event.done.set()
                self.queue.task_done()

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=6)
        if self.thread.is_alive():
            raise RuntimeError("Storage worker is still finishing; database left open to avoid a race")


class EventStore:
    def __init__(self, path, retention=5000):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = RLock()
        self.retention = retention
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
        )
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(events)")}
        if "event_key" not in columns:
            self.connection.execute("ALTER TABLE events ADD COLUMN event_key TEXT")
        self.connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS event_key ON events(event_key)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS signatures (id INTEGER PRIMARY KEY, label TEXT, features TEXT)")
        self.connection.execute('CREATE TABLE IF NOT EXISTS archive_meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)')
        next_id = self.connection.execute('SELECT COALESCE(MAX(id),0)+1 FROM events').fetchone()[0]
        self.connection.execute("INSERT OR IGNORE INTO archive_meta VALUES ('next_event_id', ?)", (next_id,))
        self.connection.execute("UPDATE archive_meta SET value=MAX(value,?) WHERE key='next_event_id'", (next_id,))
        self.connection.commit()

    def add(self, event):
        with self.lock, self.connection:
            key = event.get("event_id")
            row = self.connection.execute("SELECT id,payload FROM events WHERE event_key=?", (key,)).fetchone() if key else None
            if row:
                old = json.loads(row[1])
                event = {**event, "annotation": old.get("annotation", "")}
                self.connection.execute("UPDATE events SET payload=? WHERE id=?",
                                        (json.dumps(event, allow_nan=False), row[0]))
                return {**event, "id": row[0]}
            next_id = self.connection.execute("SELECT value FROM archive_meta WHERE key='next_event_id'").fetchone()[0]
            cursor = self.connection.execute(
                "INSERT INTO events(id,payload,event_key) VALUES (?,?,?)", (next_id, json.dumps(event, allow_nan=False), key))
            self.connection.execute("UPDATE archive_meta SET value=? WHERE key='next_event_id'", (next_id+1,))
            event = {**event, "id": cursor.lastrowid}
            self.connection.execute("DELETE FROM events WHERE id <= ?", (cursor.lastrowid - self.retention,))
        return event

    def recent(self, limit=100, category=None):
        # At most retention rows are examined; never interpolate external SQL.
        with self.lock:
            rows = self.connection.execute(
                "SELECT id,payload FROM events ORDER BY id DESC LIMIT ?",
                (self.retention if category else limit,),
            ).fetchall()
        events = [{**json.loads(payload), "id": event_id} for event_id, payload in rows]
        return [event for event in events if category is None or event["category"] == category][:limit]

    def count(self):
        with self.lock:
            return self.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def clear(self):
        """Delete event records/annotations; retain independent signatures and ID sequence."""
        with self.lock, self.connection:
            count = self.connection.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            self.connection.execute('DELETE FROM events')
        return count

    def get(self, event_id):
        with self.lock:
            row = self.connection.execute("SELECT payload FROM events WHERE id=?", (event_id,)).fetchone()
        if not row:
            raise KeyError(event_id)
        return {**json.loads(row[0]), "id": event_id}

    def annotate(self, event_id, annotation):
        with self.lock, self.connection:
            event = self.get(event_id)
            event["annotation"] = annotation
            self.connection.execute("UPDATE events SET payload=? WHERE id=?", (json.dumps(event), event_id))
        return event

    def save_signature(self, event_id, label):
        with self.lock, self.connection:
            event = self.get(event_id)
            features = event.get("features")
            if not features:
                raise ValueError("This older event has no compact feature signature")
            if len(self.signatures()) >= 256:
                raise ValueError("Signature library limit (256) reached")
            cursor = self.connection.execute("INSERT INTO signatures(label,features) VALUES (?,?)",
                                             (label, json.dumps(features, allow_nan=False)))
        return {"id": cursor.lastrowid, "label": label, "features": features, "human_reviewed": True}

    def signatures(self):
        with self.lock:
            rows = self.connection.execute("SELECT id,label,features FROM signatures ORDER BY id DESC LIMIT 256").fetchall()
        return [{"id": i, "label": label, "features": json.loads(features), "human_reviewed": True}
                for i, label, features in rows]

    def compare(self, event_id):
        import numpy as np

        features = self.get(event_id).get("features")
        if not features:
            return []
        matches = []
        for signature in self.signatures():
            if len(features) != len(signature["features"]):
                continue
            distance = float(np.linalg.norm(np.asarray(features)-signature["features"]))
            matches.append({"id": signature["id"], "label": signature["label"],
                            "feature_distance": round(distance, 5), "source_identity_confirmed": False})
        return sorted(matches, key=lambda m: m["feature_distance"])[:5]

    def close(self):
        with self.lock:
            self.connection.close()
