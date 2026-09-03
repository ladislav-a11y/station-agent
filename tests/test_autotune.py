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

    def test_hold_blocks_until_min_hold_seconds_elapses_since_current_tuned_at(self):
        """Diagnostikovaný bug: po ručním NALADIT (které nastaví HOLD a
        vypne AUTO TUNE, viz app_state.manual_tune) AUTO TUNE nikdy
        nenaskočí zpátky samo, dokud HOLD explicitně nevyprší podle
        ``min_hold_seconds`` od posledního naladění."""
        cfg = AutoTuneConfig(enabled=False, hold=True, min_hold_seconds=120, min_score_delta=0)
        engine = AutoTuneEngine(cfg, min_score=50)
        now = time.time()
        current = RigState(freq_hz=14_195_000, mode="SSB", tuned_at=now - 60, callsign="W1AW", score=60)

        decision = engine.decide([make_candidate("OK1ABC", 95)], current=current, now=now)

        self.assertEqual(decision.action, "NONE")
        self.assertTrue(cfg.hold)
        self.assertFalse(cfg.enabled)

    def test_hold_auto_expires_after_min_hold_seconds_and_autotune_resumes(self):
        """Jakmile od posledního naladění uplyne min_hold_seconds, HOLD se
        sám vypne, AUTO TUNE se sám zapne a rozhodnutí pokračuje normálním
        vyhodnocením kandidátů (tady TUNE na lepšího kandidáta)."""
        cfg = AutoTuneConfig(enabled=False, hold=True, min_hold_seconds=120, min_score_delta=0)
        engine = AutoTuneEngine(cfg, min_score=50)
        now = time.time()
        current = RigState(freq_hz=14_195_000, mode="SSB", tuned_at=now - 120, callsign="W1AW", score=60)

        decision = engine.decide([make_candidate("OK1ABC", 95)], current=current, now=now)

        self.assertEqual(decision.action, "TUNE")
        self.assertEqual(decision.candidate.callsign, "OK1ABC")
        self.assertFalse(cfg.hold)
        self.assertTrue(cfg.enabled)

    def test_hold_expiry_ignored_when_no_current_station(self):
        """Bez current (rig ještě na nic naladěný) nelze uplynulou dobu
        držení spočítat -- HOLD zůstává aktivní, dokud se rig na něco
        nenaladí."""
        cfg = AutoTuneConfig(enabled=False, hold=True, min_hold_seconds=120)
        engine = AutoTuneEngine(cfg, min_score=50)
        decision = engine.decide([make_candidate("OK1ABC", 95)], current=None)
        self.assertEqual(decision.action, "NONE")
        self.assertTrue(cfg.hold)
        self.assertFalse(cfg.enabled)

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

    def test_disallowed_mode_and_band_candidate_never_selected_even_with_higher_score(self):
        """Regrese pro bug z praktického GUI testu: CW vypnuté, 40m vypnuté,
        ale kandidát ZS6DEF 7.030 MHz CW s vyšším skóre stejně vyhrál a
        AUTO TUNE ho naladil. AUTO TUNE musí vybrat nejlepšího POVOLENÉHO
        kandidáta, ne kandidáta s absolutně nejvyšším skóre."""
        cfg = AutoTuneConfig(enabled=True, hold=False)
        engine = AutoTuneEngine(cfg, min_score=50)
        forbidden = make_candidate("ZS6DEF", 95, band="40m", mode="CW")
        best_allowed = make_candidate("OK1ABC", 80, band="20m", mode="SSB")
        worse_allowed = make_candidate("W1AW", 60, band="15m", mode="FT8")

        decision = engine.decide(
            [forbidden, best_allowed, worse_allowed],
            current=None,
            allowed_bands={"20m", "17m", "15m", "12m", "10m"},  # bez 40m
            allowed_modes={"SSB", "FT8", "RTTY", "PSK31", "PSK63", "OTHER_DIGITAL"},  # bez CW
        )

        self.assertEqual(decision.action, "TUNE")
        self.assertEqual(decision.candidate.callsign, "OK1ABC")
        self.assertNotEqual(decision.candidate.callsign, "ZS6DEF")

    def test_filter_change_at_runtime_forces_off_now_forbidden_current_station(self):
        """Když operátor za běhu vypne mód/pásmo, na kterém je rig právě
        naladěný, AUTO TUNE na něm nesmí zůstat -- musí přeladit na
        nejlepšího povoleného kandidáta, i kdyby normálně min_hold_seconds
        nebo min_score_delta přeladění zablokovaly."""
        cfg = AutoTuneConfig(enabled=True, hold=False, min_hold_seconds=300, min_score_delta=50)
        engine = AutoTuneEngine(cfg, min_score=50)
        now = time.time()
        # Rig je právě teď naladěný na 7.030 MHz CW (40m) -- operátor to
        # před chvílí vypnul v GUI.
        current = RigState(freq_hz=7_030_000, mode="CW", tuned_at=now - 5, callsign="ZS6DEF", score=95)
        best_allowed = make_candidate("OK1ABC", 60, band="20m", mode="SSB")

        decision = engine.decide(
            [best_allowed],
            current=current,
            now=now,
            allowed_bands={"20m", "17m", "15m", "12m", "10m"},
            allowed_modes={"SSB", "FT8", "RTTY", "PSK31", "PSK63", "OTHER_DIGITAL"},
        )

        self.assertEqual(decision.action, "TUNE")
        self.assertEqual(decision.candidate.callsign, "OK1ABC")

    def test_filters_do_not_affect_decision_when_current_still_allowed(self):
        """Rule 4b se nesmí spustit, pokud aktuální stanice filtrům
        vyhovuje -- hold/delta gating musí fungovat jako dřív."""
        cfg = AutoTuneConfig(enabled=True, hold=False, min_hold_seconds=300, min_score_delta=5)
        engine = AutoTuneEngine(cfg, min_score=50)
        now = time.time()
        current = RigState(freq_hz=14_195_000, mode="SSB", tuned_at=now - 5, callsign="W1AW", score=70)
        best_allowed = make_candidate("OK1ABC", 90, band="20m", mode="SSB")

        decision = engine.decide(
            [best_allowed],
            current=current,
            now=now,
            allowed_bands={"20m"},
            allowed_modes={"SSB"},
        )

        self.assertEqual(decision.action, "NONE")
        self.assertIn("doba držení", decision.reason)

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
