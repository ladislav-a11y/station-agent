import time
import unittest

from station_agent.autotune import AutoTuneEngine, apply_decision
from station_agent.config import AutoTuneConfig
from station_agent.db import Database
from station_agent.models import Candidate, RigState, ScoreResult
from station_agent.rig.mock_rig import MockRig


def make_candidate(callsign: str, score: int, band: str = "20m", mode: str = "SSB") -> Candidate:
    now = time.time()
    return Candidate(
        callsign=callsign,
        freq_hz=14_195_000,
        mode=mode,
        band=band,
        first_seen=now,
        last_seen=now,
        score=ScoreResult(total=score, reasons=[]),
    )


class AutoTuneEngineTests(unittest.TestCase):
    def test_disabled_returns_none(self):
        cfg = AutoTuneConfig(enabled=False)
        engine = AutoTuneEngine(cfg, min_score=50)
        decision = engine.decide([make_candidate("OK1ABC", 90)], current=None)
        self.assertEqual(decision.action, "NONE")

    def test_hold_returns_none_even_with_great_candidate(self):
        cfg = AutoTuneConfig(enabled=True, hold=True)
        engine = AutoTuneEngine(cfg, min_score=50)
        decision = engine.decide([make_candidate("OK1ABC", 95)], current=None)
        self.assertEqual(decision.action, "NONE")
        self.assertIn("HOLD", decision.reason)

    def test_no_eligible_candidate(self):
        cfg = AutoTuneConfig(enabled=True, hold=False)
        engine = AutoTuneEngine(cfg, min_score=80)
        decision = engine.decide([make_candidate("OK1ABC", 40)], current=None)
        self.assertEqual(decision.action, "NONE")

    def test_tunes_when_no_current_station(self):
        cfg = AutoTuneConfig(enabled=True, hold=False)
        engine = AutoTuneEngine(cfg, min_score=50)
        best = make_candidate("OK1ABC", 90)
        decision = engine.decide([make_candidate("W1AW", 60), best], current=None)
        self.assertEqual(decision.action, "TUNE")
        self.assertEqual(decision.candidate.callsign, "OK1ABC")

    def test_same_station_returns_none(self):
        cfg = AutoTuneConfig(enabled=True, hold=False, min_hold_seconds=0, min_score_delta=0)
        engine = AutoTuneEngine(cfg, min_score=50)
        now = time.time()
        current = RigState(freq_hz=14_195_000, mode="SSB", tuned_at=now, callsign="OK1ABC", score=90)
        decision = engine.decide([make_candidate("OK1ABC", 90)], current=current, now=now)
        self.assertEqual(decision.action, "NONE")

    def test_min_hold_time_blocks_switch(self):
        cfg = AutoTuneConfig(enabled=True, hold=False, min_hold_seconds=300, min_score_delta=0)
        engine = AutoTuneEngine(cfg, min_score=50)
        now = time.time()
        current = RigState(freq_hz=14_195_000, mode="SSB", tuned_at=now - 60, callsign="W1AW", score=60)
        decision = engine.decide([make_candidate("OK1ABC", 95)], current=current, now=now)
        self.assertEqual(decision.action, "NONE")
        self.assertIn("doba držení", decision.reason)

    def test_insufficient_score_delta_blocks_switch(self):
        cfg = AutoTuneConfig(enabled=True, hold=False, min_hold_seconds=0, min_score_delta=20)
        engine = AutoTuneEngine(cfg, min_score=50)
        now = time.time()
        current = RigState(freq_hz=14_195_000, mode="SSB", tuned_at=now - 600, callsign="W1AW", score=70)
        decision = engine.decide([make_candidate("OK1ABC", 80)], current=current, now=now)  # delta=10 < 20
        self.assertEqual(decision.action, "NONE")

    def test_sufficient_score_delta_after_hold_time_tunes(self):
        cfg = AutoTuneConfig(enabled=True, hold=False, min_hold_seconds=100, min_score_delta=10)
        engine = AutoTuneEngine(cfg, min_score=50)
        now = time.time()
        current = RigState(freq_hz=14_195_000, mode="SSB", tuned_at=now - 600, callsign="W1AW", score=70)
        decision = engine.decide([make_candidate("OK1ABC", 90)], current=current, now=now)
        self.assertEqual(decision.action, "TUNE")
        self.assertEqual(decision.candidate.callsign, "OK1ABC")


class ApplyDecisionTests(unittest.TestCase):
    def test_apply_tune_calls_rig_and_logs_db(self):
        rig = MockRig()
        db = Database(":memory:")
        cfg = AutoTuneConfig(enabled=True, hold=False, min_hold_seconds=0, min_score_delta=0)
        engine = AutoTuneEngine(cfg, min_score=50)
        candidate = make_candidate("OK1ABC", 90, mode="FT8")
        decision = engine.decide([candidate], current=None)

        new_state = apply_decision(rig, decision, db)

        self.assertEqual(rig.get_frequency(), 14_195_000)
        self.assertEqual(rig.get_mode(), "FT8")
        self.assertEqual(new_state.callsign, "OK1ABC")
        history = db.autotune_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["callsign"], "OK1ABC")
        db.close()

    def test_apply_none_decision_does_nothing(self):
        rig = MockRig()
        cfg = AutoTuneConfig(enabled=False)
        engine = AutoTuneEngine(cfg, min_score=50)
        decision = engine.decide([make_candidate("OK1ABC", 90)], current=None)
        result = apply_decision(rig, decision)
        self.assertIsNone(result)
        self.assertEqual(rig.set_frequency_calls, [])


if __name__ == "__main__":
    unittest.main()
