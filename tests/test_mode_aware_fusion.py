"""Ověřuje mode-aware evidence fusion napříč zdroji spotů (DX Cluster,
RBN, PSKReporter, mock).

Důležité: slučování kandidátů NENÍ povinné napříč všemi zdroji. DX Cluster
je hlavní evidence pro SSB/CW/digi, RBN hlavně pro CW a podporované
digitální spoty, PSKReporter hlavně pro digitální módy. Víc zdrojů je
bonus/potvrzení, ne podmínka existence kandidáta -- SSB kandidát vidět
jen DX Clusterem (RBN/PSKReporter SSB nedetekují) musí zůstat plnohodnotným
kandidátem a nesmí být penalizován jen za to, že chybí v PSKReporteru.

Spoty se slučují do jednoho kandidáta, pouze pokud sedí callsign, pásmo
a mód (viz ``group_spots_into_candidates`` v aggregator.py) -- odlišný mód
vždy zůstává samostatným kandidátem, i pro stejnou stanici/pásmo.
"""

from __future__ import annotations

import time
import unittest

from station_agent.aggregator import group_spots_into_candidates
from station_agent.dxcc import PREFIX_TABLE
from station_agent.models import Candidate, Spot
from station_agent.scoring import DEFAULT_WEIGHTS, ScoringConfig, score_candidate


class ModeAwareGroupingTests(unittest.TestCase):
    def setUp(self):
        self.now = time.time()

    def test_ssb_spot_seen_only_by_dx_cluster_forms_its_own_candidate(self):
        spots = [
            Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="SSB", timestamp=self.now, source="dx_cluster"),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].confirming_sources, {"dx_cluster"})
        self.assertEqual(candidates[0].mode, "SSB")

    def test_cw_spot_seen_by_dx_cluster_and_rbn_merges(self):
        spots = [
            Spot(callsign="OK1ABC", freq_hz=7_030_000, mode="CW", timestamp=self.now, source="dx_cluster"),
            Spot(callsign="OK1ABC", freq_hz=7_030_100, mode="CW", timestamp=self.now, source="rbn", snr_db=15),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].confirming_sources, {"dx_cluster", "rbn"})

    def test_ft8_spot_seen_only_by_pskreporter_forms_its_own_candidate(self):
        spots = [
            Spot(callsign="OK1ABC", freq_hz=14_074_000, mode="FT8", timestamp=self.now, source="pskreporter"),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].confirming_sources, {"pskreporter"})

    def test_ssb_and_ft8_from_same_callsign_never_merge_across_modes(self):
        spots = [
            Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="SSB", timestamp=self.now, source="dx_cluster"),
            Spot(callsign="OK1ABC", freq_hz=14_074_000, mode="FT8", timestamp=self.now, source="pskreporter"),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates), 2)
        modes = {c.mode: c.confirming_sources for c in candidates}
        self.assertEqual(modes["SSB"], {"dx_cluster"})
        self.assertEqual(modes["FT8"], {"pskreporter"})

    def test_all_three_sources_confirming_same_cw_station_merge_into_one(self):
        spots = [
            Spot(callsign="OK1ABC", freq_hz=7_030_000, mode="CW", timestamp=self.now, source="dx_cluster"),
            Spot(callsign="OK1ABC", freq_hz=7_030_050, mode="CW", timestamp=self.now, source="rbn"),
            Spot(callsign="OK1ABC", freq_hz=7_030_100, mode="CW", timestamp=self.now, source="mock"),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].confirming_sources, {"dx_cluster", "rbn", "mock"})

    def test_same_callsign_band_mode_but_far_apart_frequency_stays_separate(self):
        """DoD: slučovat jen při shodě callsign+band+PŘIBLIŽNÉ frekvence+
        časového okna+kompatibilního módu -- dvě CW QSO stejné stanice na
        stejném pásmu, ale desítky kHz od sebe, jsou dvě různá pozorování
        (např. přeladění jinam v pásmu), ne jeden kandidát."""
        spots = [
            Spot(callsign="OK1ABC", freq_hz=7_010_000, mode="CW", timestamp=self.now, source="dx_cluster"),
            Spot(callsign="OK1ABC", freq_hz=7_040_000, mode="CW", timestamp=self.now, source="rbn"),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates), 2)
        freqs = {c.freq_hz for c in candidates}
        self.assertEqual(freqs, {7_010_000, 7_040_000})
        for c in candidates:
            self.assertEqual(len(c.confirming_sources), 1)

    def test_same_callsign_band_freq_mode_but_far_apart_in_time_stays_separate(self):
        """Dvě pozorování stejné stanice/frekvence/módu hodinu od sebe jsou
        dvě různá volání (stanice zmizela a objevila se znovu), ne jedno
        průběžné pozorování -- first_seen/last_seen by se jinak uměle
        natáhlo přes celou tu dobu."""
        spots = [
            Spot(callsign="OK1ABC", freq_hz=7_030_000, mode="CW", timestamp=self.now, source="dx_cluster"),
            Spot(callsign="OK1ABC", freq_hz=7_030_000, mode="CW", timestamp=self.now + 3600, source="rbn"),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates), 2)
        for c in candidates:
            self.assertEqual(len(c.confirming_sources), 1)

    def test_ssb_tolerates_wider_frequency_spread_than_cw(self):
        """SSB má širší toleranci sloučení (typická šířka hlasového kanálu)
        než CW/digi -- spoty stejné SSB stanice hlášené s rozdílem pár kHz
        (běžné u ručního zápisu do DX clusteru) musí zůstat jeden kandidát."""
        spots = [
            Spot(callsign="OK1ABC", freq_hz=14_195_000, mode="SSB", timestamp=self.now, source="dx_cluster"),
            Spot(callsign="OK1ABC", freq_hz=14_197_000, mode="SSB", timestamp=self.now, source="mock"),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].confirming_sources, {"dx_cluster", "mock"})

    def test_chained_frequency_drift_still_merges_transitively(self):
        """Union-find musí slučovat i řetězením přes víc spotů (A blízko B
        blízko C), ne jen porovnáním proti jedinému pevnému bodu -- tři
        spoty s postupným driftem 0/600/1200 Hz (každý sousední pár do
        700 Hz tolerance pro CW/digi) patří k jedné probíhající relaci."""
        spots = [
            Spot(callsign="OK1ABC", freq_hz=7_030_000, mode="CW", timestamp=self.now, source="dx_cluster"),
            Spot(callsign="OK1ABC", freq_hz=7_030_600, mode="CW", timestamp=self.now + 60, source="rbn"),
            Spot(callsign="OK1ABC", freq_hz=7_031_200, mode="CW", timestamp=self.now + 120, source="mock"),
        ]
        candidates = group_spots_into_candidates(spots)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].confirming_sources, {"dx_cluster", "rbn", "mock"})


class ModeAwareScoringTests(unittest.TestCase):
    """Víc potvrzujících zdrojů smí skóre jen zvýšit (bonus) -- absence
    zdroje, který daný mód strukturálně nikdy nevidí (např. PSKReporter
    pro SSB), nesmí kandidáta penalizovat oproti jinému SSB kandidátovi se
    stejnými ostatními vlastnostmi."""

    def setUp(self):
        self.cfg = ScoringConfig(weights=dict(DEFAULT_WEIGHTS), spot_max_age_minutes=15)

    def _candidate(self, confirming_sources):
        now = time.time()
        return Candidate(
            callsign="OK1ABC",
            freq_hz=14_195_000,
            mode="SSB",
            band="20m",
            first_seen=now,
            last_seen=now,
            confirming_sources=confirming_sources,
            best_snr_db=None,
            dxcc=PREFIX_TABLE["OK"],
        )

    def test_single_source_ssb_candidate_scores_are_not_zeroed_out(self):
        candidate = self._candidate({"dx_cluster"})
        result = score_candidate(candidate, self.cfg, is_needed_dxcc=lambda c: True)
        # Freshness/needed_dxcc/signal faktory jsou plně nezávislé na počtu
        # zdrojů -- jediné, co se sníží, je bonusová "sources" složka, ne
        # celkové skóre na nulu/penalizaci.
        self.assertGreater(result.total, 0)
        sources_reason = next(r for r in result.reasons if r.factor == "sources")
        self.assertGreater(sources_reason.points, 0, "1 relevantní zdroj musí pořád dát alespoň nějaké body")

    def test_ssb_candidate_not_penalized_relative_to_itself_for_missing_pskreporter(self):
        # Stejný kandidát, jednou s jen dx_cluster, jednou s dx_cluster + mock
        # (simuluje "další relevantní potvrzení") -- víc zdrojů smí skóre
        # jen zvýšit nebo nechat stejné, nikdy snížit.
        only_dxc = score_candidate(self._candidate({"dx_cluster"}), self.cfg, is_needed_dxcc=lambda c: True)
        dxc_and_mock = score_candidate(
            self._candidate({"dx_cluster", "mock"}), self.cfg, is_needed_dxcc=lambda c: True
        )
        self.assertGreaterEqual(dxc_and_mock.total, only_dxc.total)

    def test_ssb_candidate_scores_equal_to_cw_candidate_with_same_source_count(self):
        """Klíčová záruka mode-aware fusion: kandidát není penalizován za
        MÓD, jen za to, kolik zdrojů ho reálně potvrdilo. SSB kandidát s
        jedním zdrojem (dx_cluster -- jediný, co SSB vůbec vidí) musí mít
        stejné skóre jako CW kandidát se stejným počtem zdrojů, ne nižší jen
        proto, že RBN/PSKReporter na SSB strukturálně nikdy nepřispějí."""
        ssb = self._candidate({"dx_cluster"})
        cw = Candidate(
            callsign="OK1ABC",
            freq_hz=7_030_000,
            mode="CW",
            band="40m",
            first_seen=ssb.first_seen,
            last_seen=ssb.last_seen,
            confirming_sources={"dx_cluster"},
            best_snr_db=None,
            dxcc=PREFIX_TABLE["OK"],
        )
        ssb_result = score_candidate(ssb, self.cfg, is_needed_dxcc=lambda c: True)
        cw_result = score_candidate(cw, self.cfg, is_needed_dxcc=lambda c: True)
        self.assertEqual(ssb_result.total, cw_result.total)

    def test_dx_cluster_alone_is_valid_evidence_for_ssb_cw_and_digital(self):
        """DoD: DX Cluster může být důkaz pro SSB/CW/digi -- samotný
        dx_cluster zdroj musí dát nenulové skóre bez ohledu na mód."""
        for mode, band, freq_hz in (("SSB", "20m", 14_195_000), ("CW", "40m", 7_030_000), ("FT8", "20m", 14_074_000)):
            with self.subTest(mode=mode):
                candidate = Candidate(
                    callsign="OK1ABC",
                    freq_hz=freq_hz,
                    mode=mode,
                    band=band,
                    first_seen=time.time(),
                    last_seen=time.time(),
                    confirming_sources={"dx_cluster"},
                    best_snr_db=None,
                    dxcc=PREFIX_TABLE["OK"],
                )
                result = score_candidate(candidate, self.cfg, is_needed_dxcc=lambda c: True)
                sources_reason = next(r for r in result.reasons if r.factor == "sources")
                self.assertGreater(sources_reason.points, 0)


if __name__ == "__main__":
    unittest.main()
