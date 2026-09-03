from __future__ import annotations

import unittest

from station_agent.propagation import (
    PropagationContext,
    PropagationService,
    _latest_numeric,
    calculate_band_quality,
)


class PropagationTests(unittest.TestCase):
    def test_current_noaa_dict_payload_accepts_capitalized_kp_key(self):
        rows = [
            {"time_tag": "2026-08-31T12:00:00", "Kp": 2.0},
            {"time_tag": "2026-08-31T15:00:00", "Kp": 1.67},
        ]

        self.assertEqual(_latest_numeric(rows, ("kp_index", "kp")), 1.67)

    def test_hourly_cache_calls_fetcher_only_once(self):
        calls = []

        def fetcher(**kwargs):
            calls.append(kwargs)
            quality, detail = calculate_band_quality(2.0, 150.0, "JN79FG", kwargs["now"])
            return PropagationContext(
                2.0, 150.0, kwargs["now"], "fixture", "JN79FG", quality, detail,
            )

        service = PropagationService("JN79FG", refresh_seconds=3600, fetcher=fetcher)
        first = service.refresh_if_due(1_700_000_000.0)
        second = service.refresh_if_due(1_700_003_599.0)
        self.assertIs(first, second)
        self.assertEqual(len(calls), 1)

    def test_outlook_is_band_specific_and_bounded(self):
        quality, detail = calculate_band_quality(2.0, 160.0, "JN79FG", 1_700_000_000.0)
        self.assertEqual(
            set(quality),
            {"160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"},
        )
        self.assertTrue(all(0.0 <= value <= 1.0 for value in quality.values()))
        self.assertGreater(len(set(quality.values())), 1)
        self.assertIn("QTH JN79FG", detail)

    def test_failed_fetch_is_not_retried_before_hour_expires(self):
        calls = []

        def failing_fetcher(**kwargs):
            calls.append(kwargs)
            raise OSError("offline")

        service = PropagationService("JN79FG", refresh_seconds=3600, fetcher=failing_fetcher)
        self.assertIsNone(service.refresh_if_due(1_700_000_000.0))
        self.assertIsNone(service.refresh_if_due(1_700_000_005.0))
        self.assertEqual(len(calls), 1)

    def test_higher_kp_reduces_all_band_quality(self):
        quiet, _ = calculate_band_quality(1.0, 150.0, "JN79FG", 1_700_000_000.0)
        storm, _ = calculate_band_quality(8.0, 150.0, "JN79FG", 1_700_000_000.0)
        self.assertTrue(all(storm[band] < quiet[band] for band in quiet))


if __name__ == "__main__":
    unittest.main()
