import unittest
from datetime import datetime, timezone

from station_agent.adapters.base import SourceNotReadyError
from station_agent.adapters.dx_cluster import DXClusterAdapter, parse_spot_line
from station_agent.adapters.pskreporter import PSKReporterAdapter, parse_pskreporter_report
from station_agent.adapters.rbn import RBNAdapter, parse_rbn_line

FIXED_NOW = datetime(2024, 1, 1, 12, 34, 30, tzinfo=timezone.utc).timestamp()


class DXClusterParsingTests(unittest.TestCase):
    def test_parses_standard_line(self):
        line = "DX de OK1KT:     14195.0  JA1XYZ       SSB nice signal          1234Z"
        spot = parse_spot_line(line, now=FIXED_NOW)
        self.assertIsNotNone(spot)
        self.assertEqual(spot.callsign, "JA1XYZ")
        self.assertEqual(spot.freq_hz, 14_195_000)
        self.assertEqual(spot.mode, "SSB")
        self.assertEqual(spot.spotter, "OK1KT")
        self.assertEqual(spot.source, "dx_cluster")
        self.assertAlmostEqual(spot.timestamp, FIXED_NOW - 30, delta=1)

    def test_line_without_mode_keyword_falls_back_to_other_digital(self):
        line = "DX de OK1KT:     10136.0  VU2PQR       good sigs             1230Z"
        spot = parse_spot_line(line, now=FIXED_NOW)
        self.assertIsNotNone(spot)
        self.assertEqual(spot.mode, "OTHER_DIGITAL")

    def test_invalid_line_returns_none(self):
        self.assertIsNone(parse_spot_line("this is not a dx spot", now=FIXED_NOW))

    def test_live_dxspider_line_with_bell_terminators(self):
        # Real W3LPL/DXSpider live stream line captured 2026-08-27.
        line = "DX de UR3QCB:    21074.0  EN35UKR      FT8, Independence Day          0804Z\x07\x07"
        spot = parse_spot_line(line, now=FIXED_NOW)
        self.assertIsNotNone(spot)
        self.assertEqual(spot.callsign, "EN35UKR")
        self.assertEqual(spot.freq_hz, 21_074_000)
        self.assertEqual(spot.mode, "FT8")
        self.assertEqual(spot.spotter, "UR3QCB")
    def test_midnight_rollover_goes_to_previous_day(self):
        # now = 00:05 UTC, spot hhmm = 23:59 -> musí to být včerejšek, ne za pár hodin "v budoucnu"
        now = datetime(2024, 1, 2, 0, 5, 0, tzinfo=timezone.utc).timestamp()
        line = "DX de OK1KT:     14195.0  JA1XYZ       SSB                    2359Z"
        spot = parse_spot_line(line, now=now)
        spot_dt = datetime.fromtimestamp(spot.timestamp, tz=timezone.utc)
        self.assertEqual(spot_dt.date(), datetime(2024, 1, 1, tzinfo=timezone.utc).date())

    def test_fetch_without_callsign_raises_source_not_ready(self):
        # Živý telnet klient (viz tests/test_telnet_source.py pro reálný
        # socket round-trip) potřebuje station.callsign pro přihlášení --
        # bez něj se ani nepokusí navázat spojení a fetch() rovnou vyhodí
        # SourceNotReadyError (GUI stav "pending").
        adapter = DXClusterAdapter(host="dxc.example.net", port=7300, callsign="")
        with self.assertRaises(SourceNotReadyError):
            adapter.fetch()


class RBNParsingTests(unittest.TestCase):
    def test_parses_standard_line(self):
        line = "DX de RBN-1-#:    7024.3  DL1ABC       CW    12 dB  25 WPM  CQ      1200Z"
        spot = parse_rbn_line(line, now=FIXED_NOW)
        self.assertIsNotNone(spot)
        self.assertEqual(spot.callsign, "DL1ABC")
        self.assertEqual(spot.freq_hz, 7_024_300)
        self.assertEqual(spot.mode, "CW")
        self.assertEqual(spot.snr_db, 12.0)
        self.assertEqual(spot.source, "rbn")

    def test_invalid_line_returns_none(self):
        self.assertIsNone(parse_rbn_line("garbage", now=FIXED_NOW))

    def test_fetch_without_callsign_raises_source_not_ready(self):
        adapter = RBNAdapter(host="telnet.reversebeacon.net", port=7000, callsign="")
        with self.assertRaises(SourceNotReadyError):
            adapter.fetch()


PSKR_FIXTURE = """<?xml version="1.0"?>
<receptionReports>
<receptionReport senderCallsign="OK1ABC" receiverCallsign="W1AW"
                  frequency="14074000" mode="FT8"
                  flowStartSeconds="1700000000" sNR="-10" />
<receptionReport senderCallsign="INCOMPLETE" mode="FT8" />
</receptionReports>
"""


class PSKReporterParsingTests(unittest.TestCase):
    def test_parses_reception_reports(self):
        spots = parse_pskreporter_report(PSKR_FIXTURE)
        self.assertEqual(len(spots), 1)
        spot = spots[0]
        self.assertEqual(spot.callsign, "OK1ABC")
        self.assertEqual(spot.freq_hz, 14_074_000)
        self.assertEqual(spot.mode, "FT8")
        self.assertEqual(spot.snr_db, -10.0)
        self.assertEqual(spot.spotter, "W1AW")
        self.assertEqual(spot.source, "pskreporter")

    def test_incomplete_entries_are_skipped(self):
        spots = parse_pskreporter_report(PSKR_FIXTURE)
        self.assertTrue(all(s.callsign != "INCOMPLETE" for s in spots))

    def test_adapter_defaults_to_real_pskreporter_endpoint(self):
        # PSKReporterAdapter je jednoduché synchronní HTTP GET -- fetch()
        # rovnou provede reálný požadavek (viz tests/test_adapters_live.py).
        # DXClusterAdapter/RBNAdapter naproti tomu běží na vlastním vlákně
        # (viz tests/test_telnet_source.py) a než přijdou první reálná
        # data, fetch() hlásí SourceNotReadyError (GUI stav "pending").
        adapter = PSKReporterAdapter()
        self.assertEqual(adapter.query_url, "https://retrieve.pskreporter.info/query")


if __name__ == "__main__":
    unittest.main()
