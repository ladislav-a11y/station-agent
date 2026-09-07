import unittest
from unittest.mock import MagicMock

from station_agent.app_state import AppState
from station_agent.config import AppConfig
from station_agent.log4om_lookup import QSOVerificationResult, QSOVerificationStatus
from station_agent.models import Candidate, ScoreResult
from station_agent.web.server import _build_status


def candidate(callsign="OK1ABC", mode="SSB", freq_hz=14_195_000):
    return Candidate(
        callsign=callsign,
        mode=mode,
        freq_hz=freq_hz,
        band="20m",
        first_seen=1.0,
        last_seen=1.0,
        score=ScoreResult(total=90),
    )


class MappingChecker:
    def __init__(self, results):
        self.results = results

    def check(self, callsign, mode, freq_hz):
        return self.results.get(
            (callsign, mode, freq_hz),
            QSOVerificationResult(QSOVerificationStatus.NO_MATCH, "ověřená neshoda"),
        )


def build_state(candidates, checker):
    config = AppConfig()
    config.propagation.enabled = False
    config.autotune.enabled = True
    config.scoring.min_score = 0
    db = MagicMock()
    db.recent_band_openings.return_value = []
    aggregator = MagicMock()
    aggregator.build_candidates.return_value = candidates
    return AppState(config, db, MagicMock(), aggregator, log4om_checker=checker)


class Log4OMCandidateIntegrationTests(unittest.TestCase):
    def test_exact_match_is_removed_but_other_mode_and_frequency_remain(self):
        exact = candidate()
        other_mode = candidate(mode="CW")
        other_frequency = candidate(freq_hz=14_196_000)
        checker = MappingChecker({
            (exact.callsign, exact.mode, exact.freq_hz): QSOVerificationResult(
                QSOVerificationStatus.MATCH, "ověřená přesná shoda"
            )
        })
        state = build_state([exact, other_mode, other_frequency], checker)

        visible = state.refresh_candidates(now=100.0)

        self.assertEqual(visible, [other_mode, other_frequency])
        self.assertTrue(state.log4om_verification.verified)

    def test_unavailable_database_keeps_candidates_visible_and_autotune_fail_open(self):
        original = candidate()
        unavailable = QSOVerificationResult(
            QSOVerificationStatus.UNAVAILABLE, "Databáze Log4OM2 není dostupná."
        )
        state = build_state(
            [original], MappingChecker({(original.callsign, original.mode, original.freq_hz): unavailable})
        )

        self.assertEqual(state.refresh_candidates(now=100.0), [original])
        decision = state.run_autotune_cycle(now=100.0)

        self.assertEqual(decision.action, "TUNE")

        status = _build_status(state)["log4om_verification"]
        self.assertFalse(status["verified"])
        self.assertFalse(status["autotune_blocked"])
        self.assertEqual(status["status"], "unavailable")
        self.assertEqual(status["diagnostic"], unavailable.diagnostic)

    def test_verified_no_match_allows_existing_autotune_path(self):
        original = candidate()
        state = build_state([original], MappingChecker({}))
        state.refresh_candidates(now=100.0)

        decision = state.run_autotune_cycle(now=100.0)

        self.assertEqual(decision.action, "TUNE")


if __name__ == "__main__":
    unittest.main()
