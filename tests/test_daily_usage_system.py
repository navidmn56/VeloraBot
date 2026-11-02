import asyncio
import sqlite3
import unittest
from datetime import datetime

from daily_usage_system import DailyUsageStore, TEHRAN_TZ


class InMemoryDailyUsageStore(DailyUsageStore):
    def __init__(self):
        self.db_path = ":memory:"
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self._lock = asyncio.Lock()
        self._init_db()

    def _get_connection(self):
        return self.connection


class DailyUsageBaselineTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryDailyUsageStore()
        self.service_id = "test-service"
        self.now = datetime.now(TEHRAN_TZ).replace(
            hour=12, minute=0, second=0, microsecond=0
        ).timestamp()
        self.today = datetime.fromtimestamp(self.now, TEHRAN_TZ).strftime("%Y-%m-%d")

    def tearDown(self):
        self.store.connection.close()

    def test_first_nonzero_snapshot_is_counted_on_observation_day(self):
        self.assertTrue(
            self.store.record_snapshot(
                self.service_id,
                up_bytes=120,
                down_bytes=380,
                timestamp=self.now,
            )
        )

        usage = self.store.get_daily_usage_for_services([self.service_id], days=7)
        self.assertEqual(usage[self.today]["total"], 500)
        self.assertEqual(usage[self.today]["up"], 120)
        self.assertEqual(usage[self.today]["down"], 380)

    def test_traffic_after_zero_baseline_is_counted(self):
        self.store.record_snapshot(
            self.service_id,
            up_bytes=0,
            down_bytes=0,
            timestamp=self.now - 60,
        )
        self.store.record_snapshot(
            self.service_id,
            up_bytes=120,
            down_bytes=380,
            timestamp=self.now,
        )

        usage = self.store.get_daily_usage_for_services([self.service_id], days=7)
        self.assertEqual(usage[self.today]["total"], 500)

    def test_legacy_missing_baseline_is_reconciled_once(self):
        with self.store._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO services (service_id, email, created_at, updated_at)
                VALUES (?, ?, ?, ?);
                """,
                (self.service_id, self.service_id, self.now, self.now),
            )
            conn.execute(
                """
                INSERT INTO traffic_snapshots (
                    service_id, timestamp, recorded_at, up_bytes, down_bytes, total_bytes
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    self.service_id,
                    self.now - 3600,
                    "test",
                    40,
                    53,
                    93,
                ),
            )
            conn.execute(
                """
                INSERT INTO daily_usage (
                    service_id, usage_date, up_bytes, down_bytes, total_bytes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (self.service_id, self.today, 160, 285, 445, self.now),
            )

        self.store.sanitize_service_usage(
            self.service_id,
            panel_total_bytes=538,
            panel_up_bytes=200,
            panel_down_bytes=338,
        )
        usage = self.store.get_daily_usage_for_services([self.service_id], days=7)
        self.assertEqual(usage[self.today]["total"], 445)

        self.store.sanitize_service_usage(
            self.service_id,
            panel_total_bytes=538,
            panel_up_bytes=200,
            panel_down_bytes=338,
            reconcile_missing=True,
        )
        self.store.sanitize_service_usage(
            self.service_id,
            panel_total_bytes=538,
            panel_up_bytes=200,
            panel_down_bytes=338,
            reconcile_missing=True,
        )

        usage = self.store.get_daily_usage_for_services([self.service_id], days=7)
        self.assertEqual(usage[self.today]["total"], 538)
        self.assertEqual(usage[self.today]["up"], 200)
        self.assertEqual(usage[self.today]["down"], 338)

    def test_reconciliation_does_not_cross_a_counter_reset(self):
        with self.store._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO services (service_id, email, created_at, updated_at)
                VALUES (?, ?, ?, ?);
                """,
                (self.service_id, self.service_id, self.now, self.now),
            )
            conn.execute(
                """
                INSERT INTO traffic_snapshots (
                    service_id, timestamp, recorded_at, up_bytes, down_bytes, total_bytes
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (self.service_id, self.now - 3600, "test", 100, 100, 200),
            )
            conn.execute(
                """
                INSERT INTO daily_usage (
                    service_id, usage_date, up_bytes, down_bytes, total_bytes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (self.service_id, self.today, 100, 100, 200, self.now),
            )
            conn.execute(
                """
                INSERT INTO reset_events (
                    service_id, timestamp, previous_up, previous_down, previous_total,
                    new_up, new_down, new_total, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (self.service_id, self.now, 500, 500, 1000, 100, 100, 200, "test reset", "test"),
            )

        self.store.sanitize_service_usage(
            self.service_id,
            panel_total_bytes=250,
            panel_up_bytes=125,
            panel_down_bytes=125,
            reconcile_missing=True,
        )

        usage = self.store.get_daily_usage_for_services([self.service_id], days=7)
        self.assertEqual(usage[self.today]["total"], 200)


if __name__ == "__main__":
    unittest.main()
