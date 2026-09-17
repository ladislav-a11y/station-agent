import time
import unittest

from station_agent.dxcc import PREFIX_TABLE
from station_agent.models import Candidate
from station_agent.scoring import DEFAULT_WEIGHTS, ScoringConfig, score_candidate
from station_agent.propagation import PropagationContext


def make_candidate(**overrides) -> Candidate:
    now = time.time()
    defaults = dict(
        callsign="OK1ABC",
        freq_hz=14_195_000,
        mode="SSB",
        band="20m",
        first_seen=now,
        last_seen=now,
        confirming_sources={"mock"},
        best_snr_db=None,
        dxcc=PREFIX_TABLE["OK"],
    )
    defaults.update(overrides)
    return Candidate(**defaults)


REASON_FACTORS = {
    "freshness",
    "sources",
    "needed_dxcc",
    "signal",
    "reliability",
    "propagation",
    "path_dx",
}


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.cfg = ScoringConfig(weights=dict(DEFAULT_WEIGHTS), spot_max_age_minutes=15)

    def test_weights_sum_to_100(self):
        self.assertEqual(sum(DEFAULT_WEIGHTS.values()), 100)

    def test_fresh_needed_high_snr_scores_high(self):
        candidate = make_candidate(
            best_snr_db=30,
            confirming_sources={"mock", "dx_cluster", "rbn"},
            spotters={"OK1KT", "DL2ABC"},
            distance_km=18_000.0,
            bearing_deg=90.0,
        )
        result = score_candidate(
            candidate,
            self.cfg,
            is_needed_dxcc=lambda c: True,
            band_activity={"20m": 6},
        )
        self.assertGreaterEqual(result.total, 90)
        self.assertEqual(len(result.reasons), 7)
        self.assertEqual({r.factor for r in result.reasons}, REASON_FACTORS)

    def test_stale_spot_loses_freshness_points(self):
        now = time.time()
        candidate = make_candidate(last_seen=now - 20 * 60)  # 20 min > 15 min limit
        result = score_candidate(candidate, self.cfg, is_needed_dxcc=lambda c: True, now=now)
        freshness = next(r for r in result.reasons if r.factor == "freshness")
        self.assertEqual(freshness.points, 0)

    def test_already_worked_scores_lower_than_needed(self):
        needed = score_candidate(make_candidate(), self.cfg, is_needed_dxcc=lambda c: True)
        worked = score_candidate(make_candidate(), self.cfg, is_needed_dxcc=lambda c: False)
        self.assertGreater(needed.total, worked.total)

    def test_missing_snr_gives_neutral_signal_score(self):
        candidate = make_candidate(best_snr_db=None)
        result = score_candidate(candidate, self.cfg, is_needed_dxcc=lambda c: True)
        signal = next(r for r in result.reasons if r.factor == "signal")
        self.assertAlmostEqual(signal.points, self.cfg.weights["signal"] * 0.5, places=1)

    def test_score_is_clamped_between_0_and_100(self):
        candidate = make_candidate(best_snr_db=1000)
        result = score_candidate(candidate, self.cfg, is_needed_dxcc=lambda c: True)
        self.assertLessEqual(result.total, 100)
        self.assertGreaterEqual(result.total, 0)

    def test_more_confirming_sources_increase_score(self):
        one_source = score_candidate(
            make_candidate(confirming_sources={"mock"}), self.cfg, is_needed_dxcc=lambda c: True
        )
        three_sources = score_candidate(
            make_candidate(confirming_sources={"mock", "dx_cluster", "rbn"}),
            self.cfg,
            is_needed_dxcc=lambda c: True,
        )
        self.assertGreater(three_sources.total, one_source.total)

    def test_more_independent_spotters_increase_reliability_points(self):
        one_spotter = score_candidate(
            make_candidate(spotters={"OK1KT"}), self.cfg, is_needed_dxcc=lambda c: True
        )
        two_spotters = score_candidate(
            make_candidate(spotters={"OK1KT", "DL2ABC"}), self.cfg, is_needed_dxcc=lambda c: True
        )
        r1 = next(r for r in one_spotter.reasons if r.factor == "reliability")
        r2 = next(r for r in two_spotters.reasons if r.factor == "reliability")
        self.assertGreater(r2.points, r1.points)

    def test_unknown_spotter_gives_neutral_reliability_not_penalty(self):
        result = score_candidate(make_candidate(spotters=set()), self.cfg, is_needed_dxcc=lambda c: True)
        reliability = next(r for r in result.reasons if r.factor == "reliability")
        self.assertAlmostEqual(reliability.points, self.cfg.weights["reliability"] * 0.5, places=1)

    def test_one_confirmed_spotter_outscores_unknown_spotter(self):
        """Regrese: jeden potvrzený spotter musí dát VÍC bodů než neznámý
        spotter (neutrální 0.5 podíl váhy) -- skutečná evidence nesmí
        skórovat stejně jako placeholder pro chybějící kontext."""
        unknown = score_candidate(make_candidate(spotters=set()), self.cfg, is_needed_dxcc=lambda c: True)
        one = score_candidate(make_candidate(spotters={"OK1KT"}), self.cfg, is_needed_dxcc=lambda c: True)
        r_unknown = next(r for r in unknown.reasons if r.factor == "reliability")
        r_one = next(r for r in one.reasons if r.factor == "reliability")
        self.assertGreater(r_one.points, r_unknown.points)

    def test_busier_band_increases_propagation_points(self):
        quiet = score_candidate(
            make_candidate(band="20m"), self.cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 1}
        )
        busy = score_candidate(
            make_candidate(band="20m"), self.cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 6}
        )
        p_quiet = next(r for r in quiet.reasons if r.factor == "propagation")
        p_busy = next(r for r in busy.reasons if r.factor == "propagation")
        self.assertGreater(p_busy.points, p_quiet.points)

    def test_missing_band_activity_gives_neutral_propagation_not_penalty(self):
        result = score_candidate(make_candidate(), self.cfg, is_needed_dxcc=lambda c: True, band_activity=None)
        propagation = next(r for r in result.reasons if r.factor == "propagation")
        self.assertAlmostEqual(propagation.points, self.cfg.weights["propagation"] * 0.5, places=1)

    def test_hourly_snapshot_is_the_propagation_input(self):
        context = PropagationContext(
            kp=2.0, solar_flux=150.0, observed_at=1_700_000_000.0,
            source="fixture", qth_locator="JN79FG",
            band_quality={"20m": 0.8}, explanation="všechny vstupy",
        )
        result = score_candidate(
            make_candidate(band="20m"), self.cfg, is_needed_dxcc=lambda c: True,
            band_activity={"20m": 1}, propagation=context,
        )
        reason = next(r for r in result.reasons if r.factor == "propagation")
        self.assertEqual(reason.points, self.cfg.weights["propagation"] * 0.8)
        self.assertIn("hodinový model 20m=0.800", reason.detail)

    def test_farther_distance_increases_path_dx_points(self):
        near = score_candidate(make_candidate(distance_km=500.0), self.cfg, is_needed_dxcc=lambda c: True)
        far = score_candidate(make_candidate(distance_km=15_000.0), self.cfg, is_needed_dxcc=lambda c: True)
        p_near = next(r for r in near.reasons if r.factor == "path_dx")
        p_far = next(r for r in far.reasons if r.factor == "path_dx")
        self.assertGreater(p_far.points, p_near.points)

    def test_missing_distance_gives_neutral_path_dx_not_penalty(self):
        result = score_candidate(make_candidate(distance_km=None), self.cfg, is_needed_dxcc=lambda c: True)
        path_dx = next(r for r in result.reasons if r.factor == "path_dx")
        self.assertAlmostEqual(path_dx.points, self.cfg.weights["path_dx"] * 0.5, places=1)

    def test_open_band_outranks_many_spotters_without_conditions(self):
        """Propagace/band opening musí být dominantním faktorem: kandidát
        s mnoha spottery, ale bez otevřeného pásma (propagace) nesmí skórovat
        výš než kandidát s málo spottery na otevřeném pásmu. Bez slyšitelnosti
        je počet spotterů irelevantní -- viz DEFAULT_SCORING_WEIGHTS."""
        many_spotters_closed_band = score_candidate(
            make_candidate(spotters={"OK1KT", "DL2ABC", "W1AW", "G3ABC", "JA1XYZ"}),
            self.cfg,
            is_needed_dxcc=lambda c: True,
            band_activity={"20m": 1},  # kandidát sám, pásmo zavřené
        )
        few_spotters_open_band = score_candidate(
            make_candidate(spotters={"OK1KT"}),
            self.cfg,
            is_needed_dxcc=lambda c: True,
            band_activity={"20m": 6},  # otevřené pásmo
        )
        self.assertGreater(few_spotters_open_band.total, many_spotters_closed_band.total)

    def test_propagation_dominates_even_when_other_factors_favor_many_spotters(self):
        """Silnější varianta předchozího testu: kandidát bez podmínek pro
        spojení má navíc maximalizované VŠECHNY ostatní na propagaci
        nezávislé faktory (SNR, zdroje, vzdálenost) -- i tak musí prohrát
        s kandidátem na otevřeném pásmu, který má jinak jen výchozí hodnoty."""
        many_spotters_no_conditions = score_candidate(
            make_candidate(
                spotters={"OK1KT", "DL2ABC", "W1AW", "G3ABC", "JA1XYZ"},
                best_snr_db=30,
                confirming_sources={"mock", "dx_cluster", "rbn"},
                distance_km=15_000.0,
            ),
            self.cfg,
            is_needed_dxcc=lambda c: True,
            band_activity={"20m": 1},
        )
        open_band_default_otherwise = score_candidate(
            make_candidate(spotters={"OK1KT"}),
            self.cfg,
            is_needed_dxcc=lambda c: True,
            band_activity={"20m": 6},
        )
        self.assertGreater(open_band_default_otherwise.total, many_spotters_no_conditions.total)


MANY_SPOTTERS = {"OK1KT", "DL2ABC", "W1AW", "G3ABC", "JA1XYZ", "VK2XYZ", "PY1ABC"}

# Váhy záměrně nastavené PROTI požadované prioritě: spotteři/zdroje mají
# dohromady 65 bodů, propagace jen 5. Kdyby dominance propagace stála jen na
# výchozích vahách (předchozí přístup), tahle konfigurace by ji rozbila --
# hearability gate ve scoring.py ji musí udržet i tady.
ADVERSARIAL_WEIGHTS = {
    "freshness": 10,
    "sources": 25,
    "needed_dxcc": 10,
    "signal": 5,
    "reliability": 40,
    "propagation": 5,
    "path_dx": 5,
}

# Váhy před zavedením dominance (reliability 10 / propagation 15).
LEGACY_WEIGHTS = {**DEFAULT_WEIGHTS, "reliability": 10, "propagation": 15}


class PropagationDominanceTests(unittest.TestCase):
    """Propagace/band opening musí být dominantní STRUKTURÁLNĚ (hearability
    gate ve scoring.py), ne jen výchozími vahami: kandidát bez podmínek pro
    slyšitelnost nesmí získat vysoké skóre jen kvůli počtu spotterů, a to
    pro libovolné váhy v configu."""

    WEIGHT_SETS = {
        "default": dict(DEFAULT_WEIGHTS),
        "legacy": LEGACY_WEIGHTS,
        "adversarial": ADVERSARIAL_WEIGHTS,
    }

    def _cfg(self, weights) -> ScoringConfig:
        return ScoringConfig(weights=dict(weights), spot_max_age_minutes=15)

    @staticmethod
    def _reason(result, factor):
        return next(r for r in result.reasons if r.factor == factor)

    def test_open_band_outranks_many_spotters_for_any_weights(self):
        for name, weights in self.WEIGHT_SETS.items():
            with self.subTest(weights=name):
                cfg = self._cfg(weights)
                closed_many = score_candidate(
                    make_candidate(spotters=MANY_SPOTTERS, confirming_sources={"mock", "dx_cluster", "rbn"}),
                    cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 1},
                )
                open_few = score_candidate(
                    make_candidate(spotters={"OK1KT"}),
                    cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 6},
                )
                self.assertGreater(open_few.total, closed_many.total)

    def test_open_band_outranks_many_spotters_with_all_other_factors_maxed_for_any_weights(self):
        """Silná varianta: kandidát bez podmínek má maximalizované všechny na
        propagaci nezávislé faktory (SNR, zdroje, vzdálenost) -- i tak musí
        prohrát s "obyčejným" kandidátem na otevřeném pásmu, u všech sad vah."""
        for name, weights in self.WEIGHT_SETS.items():
            with self.subTest(weights=name):
                cfg = self._cfg(weights)
                closed_maxed = score_candidate(
                    make_candidate(
                        spotters=MANY_SPOTTERS,
                        best_snr_db=30,
                        confirming_sources={"mock", "dx_cluster", "rbn"},
                        distance_km=15_000.0,
                    ),
                    cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 1},
                )
                open_default = score_candidate(
                    make_candidate(spotters={"OK1KT"}),
                    cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 6},
                )
                self.assertGreater(open_default.total, closed_maxed.total)

    def test_hourly_model_closed_band_outranked_by_open_band_for_any_weights(self):
        """Totéž s hodinovým NOAA modelem místo fallbacku na aktivitu pásma:
        kvalita 0.0 = zavřené pásmo, 1.0 = otevřené."""
        def context(quality):
            return PropagationContext(
                kp=2.0, solar_flux=150.0, observed_at=1_700_000_000.0,
                source="fixture", qth_locator="JN79FG",
                band_quality={"20m": quality}, explanation="fixture",
            )

        for name, weights in self.WEIGHT_SETS.items():
            with self.subTest(weights=name):
                cfg = self._cfg(weights)
                closed_many = score_candidate(
                    make_candidate(spotters=MANY_SPOTTERS, confirming_sources={"mock", "dx_cluster", "rbn"}),
                    cfg, is_needed_dxcc=lambda c: True, propagation=context(0.0),
                )
                open_few = score_candidate(
                    make_candidate(spotters={"OK1KT"}),
                    cfg, is_needed_dxcc=lambda c: True, propagation=context(1.0),
                )
                self.assertGreater(open_few.total, closed_many.total)

    def test_closed_band_zeroes_spotter_evidence_and_explains_it(self):
        """Na zavřeném pásmu (propagace 0.0) nesmí spotteři ani zdroje přidat
        žádné body a rozpis důvodů musí říct proč (transparentní scoring)."""
        cfg = self._cfg(DEFAULT_WEIGHTS)
        result = score_candidate(
            make_candidate(spotters=MANY_SPOTTERS, confirming_sources={"mock", "dx_cluster", "rbn"}),
            cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 1},
        )
        for factor in ("reliability", "sources"):
            with self.subTest(factor=factor):
                reason = self._reason(result, factor)
                self.assertEqual(reason.points, 0)
                self.assertEqual(reason.max_points, cfg.weights[factor])
                self.assertIn("evidence omezena x0.00", reason.detail)

    def test_partially_open_band_scales_spotter_evidence_proportionally(self):
        cfg = self._cfg(DEFAULT_WEIGHTS)
        half_open = score_candidate(
            make_candidate(spotters={"OK1KT", "DL2ABC"}, confirming_sources={"mock", "dx_cluster", "rbn"}),
            cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 3},  # (3-1)/(5-1) = 0.5
        )
        self.assertAlmostEqual(self._reason(half_open, "reliability").points, cfg.weights["reliability"] * 0.5, places=1)
        self.assertAlmostEqual(self._reason(half_open, "sources").points, cfg.weights["sources"] * 0.5, places=1)
        self.assertIn("propagace 0.50", self._reason(half_open, "reliability").detail)

    def test_fully_open_band_leaves_spotter_evidence_untouched(self):
        cfg = self._cfg(DEFAULT_WEIGHTS)
        result = score_candidate(
            make_candidate(spotters={"OK1KT", "DL2ABC"}, confirming_sources={"mock", "dx_cluster", "rbn"}),
            cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 6},
        )
        self.assertEqual(self._reason(result, "reliability").points, cfg.weights["reliability"])
        self.assertEqual(self._reason(result, "sources").points, cfg.weights["sources"])
        self.assertNotIn("evidence omezena", self._reason(result, "reliability").detail)

    def test_unknown_propagation_does_not_gate_spotter_evidence(self):
        """Chybějící kontext nesmí penalizovat (DATA_CONTRACT sekce 3): bez
        snapshotu i bez aktivity pásma dostanou spotteři plné body."""
        cfg = self._cfg(DEFAULT_WEIGHTS)
        result = score_candidate(
            make_candidate(spotters={"OK1KT", "DL2ABC"}, confirming_sources={"mock", "dx_cluster", "rbn"}),
            cfg, is_needed_dxcc=lambda c: True, band_activity=None,
        )
        self.assertEqual(self._reason(result, "reliability").points, cfg.weights["reliability"])
        self.assertEqual(self._reason(result, "sources").points, cfg.weights["sources"])

    def test_propagation_weight_zero_disables_gate(self):
        """Uživatel, který propagaci vypne váhou 0, nesmí dostat skryté
        gatování spotterů (viz tests/test_web_api.py AutoTuneRespectsGuiFiltersTests)."""
        weights = dict(DEFAULT_WEIGHTS)
        weights["signal"] += weights.pop("propagation")
        weights["propagation"] = 0
        cfg = self._cfg(weights)
        result = score_candidate(
            make_candidate(spotters={"OK1KT", "DL2ABC"}, confirming_sources={"mock", "dx_cluster", "rbn"}),
            cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 1},
        )
        self.assertEqual(self._reason(result, "reliability").points, cfg.weights["reliability"])
        self.assertEqual(self._reason(result, "sources").points, cfg.weights["sources"])

    def test_confirmed_spotters_still_outscore_unknown_spotter_on_closed_band(self):
        """Gate se aplikuje i na neutrální fallback "spotter neznámý", jinak
        by na zavřeném pásmu chybějící evidence skórovala VÍC než reálná."""
        cfg = self._cfg(DEFAULT_WEIGHTS)
        unknown = score_candidate(
            make_candidate(spotters=set()), cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 3},
        )
        known = score_candidate(
            make_candidate(spotters={"OK1KT"}), cfg, is_needed_dxcc=lambda c: True, band_activity={"20m": 3},
        )
        self.assertGreater(self._reason(known, "reliability").points, self._reason(unknown, "reliability").points)

    def test_ungated_factors_are_unaffected_by_closed_band(self):
        """Zachování ostatního chování: freshness/needed_dxcc/signal/path_dx
        nezávisí na propagaci -- nová DXCC entita je potřebná i na zavřeném pásmu."""
        cfg = self._cfg(DEFAULT_WEIGHTS)
        now = time.time()
        candidate = make_candidate(best_snr_db=15, distance_km=10_000.0, last_seen=now)
        closed = score_candidate(candidate, cfg, is_needed_dxcc=lambda c: True, now=now, band_activity={"20m": 1})
        opened = score_candidate(candidate, cfg, is_needed_dxcc=lambda c: True, now=now, band_activity={"20m": 6})
        for factor in ("freshness", "needed_dxcc", "signal", "path_dx"):
            with self.subTest(factor=factor):
                self.assertEqual(self._reason(closed, factor).points, self._reason(opened, factor).points)


if __name__ == "__main__":
    unittest.main()
