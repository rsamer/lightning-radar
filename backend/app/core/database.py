"""Database management for Lightning Radar."""
import logging
import os
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)

NUMERIC_KEYS = {"target_lat", "target_lon", "alert_radius_km", "obs_radius_km"}

class Database:
    """SQLite database manager for lightning strikes."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True) if os.path.dirname(db_path) else None
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._write_lock = threading.Lock()
        self.init_db()

    def init_db(self):
        """Initialize database with required tables."""
        with self._write_lock:
            cursor = self._conn.cursor()

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strikes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time_ms INTEGER NOT NULL,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    source TEXT DEFAULT 'blitzortung',
                    country TEXT DEFAULT 'SEA',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Add country column to existing tables that predate this schema
            try:
                cursor.execute("ALTER TABLE strikes ADD COLUMN country TEXT DEFAULT 'SEA'")
                self._conn.commit()
            except Exception:
                pass  # Column already exists

            # Create index for faster queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_strikes_time
                ON strikes(time_ms DESC)
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS app_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            ''')

            # Seed default settings (INSERT OR IGNORE so existing values are kept)
            cursor.executemany(
                "INSERT OR IGNORE INTO app_settings VALUES (?, ?)",
                [
                    ('target_name',     'Graz'),
                    ('target_lat',      '47.07'),
                    ('target_lon',      '15.44'),
                    ('alert_radius_km', '50.0'),
                    ('obs_radius_km',   '500.0'),
                ]
            )

            self._conn.commit()
        logger.info(f"Database initialized: {self.db_path}")

    def load_settings(self) -> dict:
        """Load all app_settings rows and return as {key: value} dict.

        Numeric keys are automatically cast to float.
        """
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT key, value FROM app_settings")
            result = {}
            for row in cursor.fetchall():
                k, v = row["key"], row["value"]
                result[k] = float(v) if k in NUMERIC_KEYS else v
            return result
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
            return {}

    def save_settings(self, data: dict) -> None:
        """Persist a dict of settings into app_settings via INSERT OR REPLACE."""
        try:
            with self._write_lock:
                cursor = self._conn.cursor()
                cursor.executemany(
                    "INSERT OR REPLACE INTO app_settings VALUES (?, ?)",
                    [(k, str(v)) for k, v in data.items()]
                )
                self._conn.commit()
        except Exception as e:
            logger.error(f"Error saving settings: {e}")

    def add_strike(
        self, lat: float, lon: float, time_ms: int,
        source: str = "blitzortung", country: str = "SEA",
    ) -> bool:
        """Add a strike to the database."""
        try:
            with self._write_lock:
                cursor = self._conn.cursor()
                cursor.execute(
                    "INSERT INTO strikes (time_ms, lat, lon, source, country) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (time_ms, lat, lon, source, country)
                )
                self._conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding strike: {e}")
            return False

    def get_total_strikes(self) -> int:
        """Get total number of strikes."""
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM strikes")
            return cursor.fetchone()['count']
        except Exception as e:
            logger.error(f"Error getting total strikes: {e}")
            return 0

    def get_strikes_last_hour(self) -> int:
        """Get strikes in last hour."""
        try:
            one_hour_ago = int((time.time() - 3600) * 1000)
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) as count FROM strikes WHERE time_ms > ?", (one_hour_ago,)
            )
            return cursor.fetchone()['count']
        except Exception as e:
            logger.error(f"Error getting strikes last hour: {e}")
            return 0

    def get_recent_strikes(self, limit: int = 100) -> list:
        """Get recent strikes."""
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT lat, lon, time_ms, source, country FROM strikes "
                "ORDER BY time_ms DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting recent strikes: {e}")
            return []

    def get_strikes_by_timerange(self, from_ms: int, to_ms: int, limit: int = 2000) -> list:
        """Get strikes within a time range for historical playback."""
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT lat, lon, time_ms, source, country FROM strikes "
                "WHERE time_ms >= ? AND time_ms <= ? "
                "ORDER BY time_ms DESC LIMIT ?",
                (from_ms, to_ms, limit)
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting strikes by timerange: {e}")
            return []
