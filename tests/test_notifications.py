import unittest

from station_agent.config import NotificationsConfig
from station_agent.notifications import BandOpeningTracker


def make_cfg(**overrides) -> NotificationsConfig:
    defaults = dict(enabled=True, min_distinct_stations=5, cooldown_minutes=30.0, max_per_hour=10)
    defaults.update(overrides)
    return NotificationsConfig(**defaults)


class BandOpeningTrackerTests(unittest.TestCase):
    def test_previous_process_events_restore_rate_limits(self):
        previous = [
            {"band": "20m", "ts": 990.0},
            {"band": "40m", "ts": 995.0},
        ]
        tracker = BandOpeningTracker(make_cfg(max_per_hour=2), previous)
        events = tracker.check({"20m": 8}, now=1000.0)
        self.assertEqual(events, [])

    def test_old_previous_event_does_not_suppress_new_opening(self):
        tracker = BandOpeningTracker(make_cfg(), [{"band": "20m", "ts": 1.0}])
        events = tracker.check({"20m": 8}, now=100_000.0)
        self.assertEqual(len(events), 1)

    def test_event_outside_cooldown_but_inside_hour_does_not_mark_band_open(self):
        tracker = BandOpeningTracker(
            make_cfg(cooldown_minutes=30.0, max_per_hour=10),
            [{"band": "20m", "ts": 1000.0}],
        )
        events = tracker.check({"20m": 8}, now=1000.0 + 50 * 60)
        self.assertEqual(len(events), 1)

    def test_no_event_below_threshold(self):
        tracker = BandOpeningTracker(make_cfg())
        events = tracker.check({"20m": 4}, now=1000.0)
        self.assertEqual(events, [])

    def test_event_fires_once_activity_crosses_threshold(self):
        tracker = BandOpeningTracker(make_cfg())
        events = tracker.check({"20m": 6}, now=1000.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].band, "20m")
        self.assertEqual(events[0].station_count, 6)
        self.assertEqual(events[0].station_count_change, 6)

    def test_deduplicated_while_continuously_open(self):
        """DoD: dokud pásmo zůstává otevřené, žádná další notifikace."""
        tracker = BandOpeningTracker(make_cfg())
        first = tracker.check({"20m": 6}, now=1000.0)
        second = tracker.check({"20m": 7}, now=1010.0)
        third = tracker.check({"20m": 9}, now=1020.0)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(third, [])

    def test_equal_reopening_generates_another_event(self):
        tracker = BandOpeningTracker(make_cfg(cooldown_minutes=0.01))
        first = tracker.check({"20m": 6}, now=1000.0)
        closed = tracker.check({"20m": 2}, now=1010.0)
        reopened = tracker.check({"20m": 6}, now=1020.0)
        self.assertEqual(len(first), 1)
        self.assertEqual(closed, [])
        self.assertEqual(len(reopened), 1)
        self.assertEqual(reopened[0].band, "20m")

    def test_equal_reappearance_generates_another_event(self):
        """Pásmo bez žádné aktivity v aktuálním cyklu (chybí v mapě) se
        chová jako zavřené -- při novém výskytu nad prahem se notifikuje
        znovu, ne se to považuje za "pořád otevřené"."""
        tracker = BandOpeningTracker(make_cfg(cooldown_minutes=0.01))
        first = tracker.check({"20m": 6}, now=1000.0)
        gone = tracker.check({}, now=1010.0)
        reopened = tracker.check({"20m": 6}, now=1020.0)
        self.assertEqual(len(first), 1)
        self.assertEqual(gone, [])
        self.assertEqual(len(reopened), 1)
        self.assertEqual(reopened[0].band, "20m")

    def test_cooldown_suppresses_rapid_flapping_reopen(self):
        """I po skutečném uzavření a znovuotevření se cooldown musí
        respektovat -- ochrana proti kolísání aktivity těsně kolem prahu."""
        tracker = BandOpeningTracker(make_cfg(cooldown_minutes=30.0))
        first = tracker.check({"20m": 6}, now=1000.0)
        tracker.check({"20m": 2}, now=1001.0)
        reopened_too_soon = tracker.check({"20m": 6}, now=1002.0)  # 1s later, cooldown je 30 min
        self.assertEqual(len(first), 1)
        self.assertEqual(reopened_too_soon, [])

    def test_hourly_limit_caps_events_across_bands(self):
        tracker = BandOpeningTracker(make_cfg(cooldown_minutes=0.001, max_per_hour=2))
        bands = ["20m", "40m", "15m"]
        now = 1000.0
        fired = 0
        for band in bands:
            events = tracker.check({band: 6}, now=now)
            fired += len(events)
            now += 1.0
        self.assertEqual(fired, 2)

    def test_disabled_config_never_fires(self):
        tracker = BandOpeningTracker(make_cfg(enabled=False))
        events = tracker.check({"20m": 50}, now=1000.0)
        self.assertEqual(events, [])

    def test_multiple_bands_open_simultaneously_all_generate_events(self):
        tracker = BandOpeningTracker(make_cfg())
        events = tracker.check({"20m": 6, "40m": 8, "15m": 3}, now=1000.0)
        self.assertEqual([event.band for event in events], ["20m", "40m"])
        self.assertEqual([event.station_count_change for event in events], [6, 8])

    def test_independent_openings_are_retained_since_start(self):
        tracker = BandOpeningTracker(make_cfg(cooldown_minutes=0.01))
        first = tracker.check({"20m": 6}, now=1000.0)
        smaller = tracker.check({"20m": 0, "40m": 5}, now=1010.0)
        greater = tracker.check({"40m": 5, "15m": 9}, now=1020.0)
        self.assertEqual(first[0].band, "20m")
        self.assertEqual(smaller[0].band, "40m")
        self.assertEqual(greater[0].band, "15m")
        self.assertEqual([event.band for event in tracker.events], ["20m", "40m", "15m"])


if __name__ == "__main__":
    unittest.main()
