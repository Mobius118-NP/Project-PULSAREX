import json
import sqlite3
from pathlib import Path
from threading import RLock


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
        self.connection.commit()

    def add(self, event):
        with self.lock, self.connection:
            cursor = self.connection.execute(
                "INSERT INTO events(payload) VALUES (?)", (json.dumps(event, allow_nan=False),)
            )
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

    def close(self):
        with self.lock:
            self.connection.close()


class EventDetector:
    def __init__(self, threshold=12.0, cooldown=3.0):
        self.threshold = threshold
        self.cooldown = cooldown
        self.last_event = -float("inf")
        self.previous_peak = None
        self.onset = None

    def detect(self, frame, deviation, ready, now, timestamp):
        import numpy as np

        if not ready:
            return None
        absolute = np.abs(np.asarray(deviation))
        changed = absolute >= self.threshold
        fraction = float(changed.mean())
        magnitude = float(np.percentile(absolute[changed], 80)) if changed.any() else 0.0
        peak = frame["peaks"][0]["hz"] if frame["peaks"] else None
        tonal_change = bool(peak and self.previous_peak and abs(peak - self.previous_peak) > 60)
        if peak:
            self.previous_peak = peak
        active = fraction >= 0.025 or (tonal_change and frame["flux"] > 0.15)
        if not active:
            self.onset = None
            return None
        if self.onset is None:
            self.onset = now
        if now - self.last_event < self.cooldown:
            return None
        self.last_event = now
        category = (
            "broadband transient"
            if fraction > 0.35 and frame["flux"] > 0.2
            else ("tonal change" if tonal_change else "spectral change")
        )
        frequencies = np.asarray(frame["frequencies"])
        band = frequencies[changed]
        return {
            "timestamp": timestamp,
            "category": category,
            "band_hz": [round(float(band.min()), 1), round(float(band.max()), 1)] if len(band) else [],
            "change_db": round(magnitude, 2),
            "duration_seconds": round(now - self.onset, 3),
            "score": round(min(1, max(magnitude / (self.threshold * 3), fraction)), 3),
            "source": frame.get("source", "unknown"),
        }
