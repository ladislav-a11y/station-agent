import socket
import time
import unittest

from station_agent import log4om
from station_agent.log4om import Log4OMBridge, build_prefill_fields, build_prefill_xml
from station_agent.models import Candidate, DXCCEntity, ScoreResult


def make_candidate() -> Candidate:
    now = time.time()
    return Candidate(
        callsign="OK1ABC<>",  # obsahuje znaky vyžadující XML escaping
        freq_hz=14_195_000,
        mode="SSB",
        band="20m",
        first_seen=now,
        last_seen=now,
        dxcc=DXCCEntity("Czech Republic", "OK", "EU", 50.0, 14.0),
        bearing_deg=91.2,
        score=ScoreResult(total=80, reasons=[]),
    )


class PrefillBuildingTests(unittest.TestCase):
    def test_build_prefill_fields(self):
        fields = build_prefill_fields(make_candidate(), station_callsign="OK1TEST")
        self.assertEqual(fields["dx_call"], "OK1ABC<>")
        self.assertEqual(fields["operator_call"], "OK1TEST")
        self.assertEqual(fields["band"], "20m")
        self.assertEqual(fields["mode"], "SSB")
        self.assertEqual(fields["dxcc"], "Czech Republic")
        self.assertEqual(fields["bearing_deg"], "91")

    def test_build_prefill_xml_escapes_special_characters(self):
        fields = build_prefill_fields(make_candidate())
        xml_payload = build_prefill_xml(fields)
        self.assertIn("<dx_call>OK1ABC&lt;&gt;</dx_call>", xml_payload)
        self.assertNotIn("<>", xml_payload.split("<dx_call>")[1].split("</dx_call>")[0])


class SendPrefillTests(unittest.TestCase):
    def test_send_prefill_delivers_udp_packet_to_local_listener(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener.bind(("127.0.0.1", 0))
        listener.settimeout(2)
        host, port = listener.getsockname()

        bridge = Log4OMBridge(host=host, port=port, station_callsign="OK1TEST")
        sent = bridge.prefill(make_candidate())

        data, _ = listener.recvfrom(4096)
        listener.close()

        self.assertGreater(sent, 0)
        self.assertIn(b"<dx_call>OK1ABC", data)


class NoAutoSaveTests(unittest.TestCase):
    def test_module_has_no_qso_save_function(self):
        forbidden_substrings = ["save_qso", "log_qso", "commit_qso", "confirm_qso", "write_qso"]
        names = [name.lower() for name in dir(log4om)]
        for forbidden in forbidden_substrings:
            self.assertFalse(
                any(forbidden in name for name in names),
                f"log4om.py nesmí obsahovat funkci pro automatické uložení QSO ({forbidden})",
            )


if __name__ == "__main__":
    unittest.main()
