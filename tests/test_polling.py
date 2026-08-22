"""Testy pro station_agent/adapters/polling.py -- odděluje frekvenci
GUI refreshe od frekvence dotazování živých zdrojů (PSKReporter atd.),
viz i modul docstring v polling.py.

Ověřuje se zde:
- throttling: druhý ``poll()`` uvnitř ``interval_seconds`` nesmí sáhnout
  na síť (to je přímá příčina HTTP 429 z reálného provozu -- PSKReporter
  byl dotazován při každém GUI refreshi, tedy ~ každé 3 s),
- exponenciální backoff a respektování ``Retry-After`` po HTTP 429
  (``RateLimitedError``),
- že se cache posledních úspěšných dat zachová i při chybě/backoffu a
  ``status_dict`` reportuje jejich stáří,
- že úspěšný fetch backoff/chybu resetuje.
"""

from __future__ import annotations

import unittest

from station_agent.adapters.base import RateLimitedError, SpotSource
from station_agent.adapters.polling import PolledSource
from station_agent.models import Spot


def _spot(callsign: str = "OK1ABC", ts: float = 0.0) -> Spot:
    return Spot(callsign=callsign, freq_hz=14_195_000, mode="SSB", timestamp=ts, source="scripted")


class _ScriptedSource(SpotSource):
    """Zdroj, který při každém ``fetch()`` vrátí/vyhodí další naskriptovanou
    odpověď ze seznamu -- pro deterministické testy PolledSource."""

    name = "scripted"

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.call_count = 0

    def fetch(self) -> list[Spot]:
        self.call_count += 1
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _PendingSource(SpotSource):
    name = "pending"

    def fetch(self) -> list[Spot]:
        raise NotImplementedError("pending: zatím neověřeno proti reálné službě")


class PolledSourceIntervalTests(unittest.TestCase):
    def test_first_poll_always_fetches(self):
        source = _ScriptedSource([[_spot(ts=0)]])
        poller = PolledSource(source, interval_seconds=60)
        spots, fresh = poller.poll(now=1000.0)
        self.assertEqual(source.call_count, 1)
        self.assertEqual(len(spots), 1)
        self.assertEqual(len(fresh), 1)
        self.assertEqual(poller.status, "ok")

    def test_second_poll_within_interval_does_not_hit_network(self):
        source = _ScriptedSource([[_spot(ts=0)]])
        poller = PolledSource(source, interval_seconds=60)
        poller.poll(now=1000.0)

        spots, fresh = poller.poll(now=1003.0)  # simuluje GUI refresh o 3s později

        self.assertEqual(source.call_count, 1, "throttling musí zabránit druhému fetch()i")
        self.assertEqual(len(fresh), 0, "nesmí se znovu vkládat stejná data do DB")
        self.assertEqual(len(spots), 1, "kandidáti ale pořád dostanou poslední známá data")

    def test_many_polls_within_interval_still_fetch_only_once(self):
        source = _ScriptedSource([[_spot(ts=0)]])
        poller = PolledSource(source, interval_seconds=60)
        for i in range(20):
            poller.poll(now=1000.0 + i * 3)  # 20x "GUI refresh" po 3s
        self.assertEqual(source.call_count, 1)

    def test_poll_after_interval_elapsed_refetches(self):
        source = _ScriptedSource([[_spot(ts=0)], [_spot(ts=65)]])
        poller = PolledSource(source, interval_seconds=60)
        poller.poll(now=1000.0)
        spots, fresh = poller.poll(now=1065.0)
        self.assertEqual(source.call_count, 2)
        self.assertEqual(len(fresh), 1)


class PolledSourceRateLimitTests(unittest.TestCase):
    def test_429_without_retry_after_backs_off_by_interval(self):
        source = _ScriptedSource([RateLimitedError()])
        poller = PolledSource(source, interval_seconds=60, backoff_max_seconds=1800)
        poller.poll(now=0.0)
        self.assertEqual(poller.status, "backoff")
        self.assertAlmostEqual(poller.backoff_until, 60.0, delta=0.01)

    def test_no_requests_sent_during_backoff_window(self):
        source = _ScriptedSource([RateLimitedError(retry_after_seconds=120)])
        poller = PolledSource(source, interval_seconds=60)
        poller.poll(now=0.0)
        poller.poll(now=30.0)
        poller.poll(now=90.0)
        poller.poll(now=119.0)
        self.assertEqual(source.call_count, 1, "žádný další požadavek nesmí odejít během backoffu")

    def test_backoff_grows_exponentially_on_repeated_429(self):
        source = _ScriptedSource([RateLimitedError(), RateLimitedError(), RateLimitedError()])
        poller = PolledSource(source, interval_seconds=60, backoff_max_seconds=100_000)

        now = 0.0
        poller.poll(now=now)
        span1 = poller.backoff_until - now
        self.assertAlmostEqual(span1, 60.0, delta=0.01)

        now = poller.backoff_until + 1
        poller.poll(now=now)
        span2 = poller.backoff_until - now
        self.assertGreater(span2, span1)

        now = poller.backoff_until + 1
        poller.poll(now=now)
        span3 = poller.backoff_until - now
        self.assertGreater(span3, span2)
        self.assertEqual(source.call_count, 3)

    def test_backoff_is_capped_at_backoff_max_seconds(self):
        source = _ScriptedSource([RateLimitedError() for _ in range(6)])
        poller = PolledSource(source, interval_seconds=60, backoff_max_seconds=300)
        now = 0.0
        span = None
        for _ in range(6):
            poller.poll(now=now)
            span = poller.backoff_until - now
            now = poller.backoff_until + 1
        self.assertLessEqual(span, 300)
        self.assertEqual(source.call_count, 6)

    def test_retry_after_header_is_respected_even_if_longer_than_interval(self):
        source = _ScriptedSource([RateLimitedError(retry_after_seconds=900)])
        poller = PolledSource(source, interval_seconds=60)
        poller.poll(now=0.0)
        self.assertAlmostEqual(poller.backoff_until, 900.0, delta=0.01)

    def test_retry_after_shorter_than_interval_still_respects_min_interval(self):
        source = _ScriptedSource([RateLimitedError(retry_after_seconds=5)])
        poller = PolledSource(source, interval_seconds=60)
        poller.poll(now=0.0)
        self.assertGreaterEqual(poller.backoff_until, 60.0)

    def test_success_after_backoff_resets_state(self):
        source = _ScriptedSource([RateLimitedError(retry_after_seconds=10), [_spot(ts=100)]])
        poller = PolledSource(source, interval_seconds=5)
        poller.poll(now=0.0)
        self.assertEqual(poller.status, "backoff")

        spots, fresh = poller.poll(now=11.0)

        self.assertEqual(poller.status, "ok")
        self.assertIsNone(poller.backoff_until)
        self.assertEqual(poller.consecutive_rate_limits, 0)
        self.assertEqual(len(fresh), 1)


class PolledSourceCacheAndStatusTests(unittest.TestCase):
    def test_last_success_cache_survives_subsequent_error(self):
        source = _ScriptedSource([[_spot(ts=1000)], ConnectionError("network unreachable")])
        poller = PolledSource(source, interval_seconds=60)
        poller.poll(now=1000.0)
        self.assertEqual(poller.status, "ok")

        spots, fresh = poller.poll(now=1065.0)

        self.assertEqual(poller.status, "error")
        self.assertEqual(len(fresh), 0)
        self.assertEqual(len(spots), 1, "poslední úspěšná data zůstávají dostupná i při chybě")
        self.assertEqual(spots[0].callsign, "OK1ABC")

    def test_status_dict_reports_age_of_cached_data(self):
        source = _ScriptedSource([[_spot(ts=0)]])
        poller = PolledSource(source, interval_seconds=60)
        poller.poll(now=1000.0)

        status = poller.status_dict(now=1042.0)

        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["last_success_age_seconds"], 42.0)
        self.assertEqual(status["cached_spot_count"], 1)
        self.assertIsNone(status["last_error"])

    def test_status_dict_reports_backoff_remaining_and_error(self):
        source = _ScriptedSource([RateLimitedError(retry_after_seconds=120)])
        poller = PolledSource(source, interval_seconds=60)
        poller.poll(now=0.0)

        status = poller.status_dict(now=30.0)

        self.assertEqual(status["status"], "backoff")
        self.assertAlmostEqual(status["backoff_remaining_seconds"], 90.0, delta=0.01)
        self.assertIsNotNone(status["last_error"])

    def test_pending_source_reports_pending_status_without_cache(self):
        poller = PolledSource(_PendingSource(), interval_seconds=60)
        spots, fresh = poller.poll(now=0.0)
        self.assertEqual(spots, [])
        self.assertEqual(fresh, [])
        self.assertEqual(poller.status, "pending")


if __name__ == "__main__":
    unittest.main()
