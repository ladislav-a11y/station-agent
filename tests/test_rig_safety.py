"""Bezpečnostní testy: dokazují, že v projektu neexistuje ŽÁDNÁ cesta k
zapnutí PTT/vysílání, a že rotor se nikdy neovládá (jen se počítá bearing).

Viz AGENTS.md pravidlo 1 a 2. Tyto testy musí projít i po jakémkoli
budoucím refaktoringu -- pokud selžou, něco v kódu porušilo bezpečnostní
invariant a NESMÍ se to slučovat.
"""

from __future__ import annotations

import inspect
import re
import unittest
from pathlib import Path

import station_agent
from station_agent.rig.base import RigControl
from station_agent.rig.mock_rig import MockRig
from station_agent.rig.rigctld import RigctldClient

PACKAGE_ROOT = Path(station_agent.__file__).parent

_PTT_PATTERN = re.compile(r"ptt", re.IGNORECASE)
_ROTOR_CONTROL_PATTERN = re.compile(r"\b(set_rotor|rotor_turn|move_rotor|rotor_set)\b", re.IGNORECASE)


def _all_source_files() -> list[Path]:
    return sorted(PACKAGE_ROOT.rglob("*.py"))


class NoPttStringAnywhereTests(unittest.TestCase):
    def test_no_source_file_mentions_ptt(self):
        offending = []
        for path in _all_source_files():
            text = path.read_text(encoding="utf-8")
            if _PTT_PATTERN.search(text):
                offending.append(str(path.relative_to(PACKAGE_ROOT.parent)))
        self.assertEqual(
            offending,
            [],
            "Nalezena zmínka o PTT ve zdrojovém kódu (i v komentáři) -- to je "
            f"zakázané, viz AGENTS.md pravidlo 1: {offending}",
        )

    def test_no_rotor_control_function_anywhere(self):
        offending = []
        for path in _all_source_files():
            text = path.read_text(encoding="utf-8")
            if _ROTOR_CONTROL_PATTERN.search(text):
                offending.append(str(path.relative_to(PACKAGE_ROOT.parent)))
        self.assertEqual(
            offending,
            [],
            f"Nalezena funkce pro ovládání rotoru -- to je zakázané, viz AGENTS.md pravidlo 2: {offending}",
        )


class RigControlInterfaceTests(unittest.TestCase):
    ALLOWED_PUBLIC_MEMBERS = {
        "get_frequency",
        "get_mode",
        "set_frequency",
        "set_mode",
        "get_status",
        "close",
        "host",
        "port",
        "timeout",
        "model",
        "set_frequency_calls",
        "set_mode_calls",
    }

    def test_rig_control_is_abstract_with_closed_method_set(self):
        abstract_methods = RigControl.__abstractmethods__
        self.assertEqual(abstract_methods, frozenset({"get_frequency", "get_mode", "set_frequency", "set_mode"}))

    def _assert_no_extra_public_members(self, obj) -> None:
        public_members = {name for name in dir(obj) if not name.startswith("_")}
        extra = public_members - self.ALLOWED_PUBLIC_MEMBERS
        self.assertEqual(extra, set(), f"{obj} má neočekávané veřejné členy (možné bezpečnostní riziko): {extra}")

    def test_mock_rig_has_no_extra_methods(self):
        self._assert_no_extra_public_members(MockRig())

    def test_rigctld_client_has_no_extra_methods(self):
        client = RigctldClient(host="127.0.0.1", port=4532)
        self._assert_no_extra_public_members(client)

    def test_no_generic_raw_command_method_exists(self):
        # Univerzální "pošli libovolný příkaz" metoda by šla zneužít k PTT --
        # nesmí existovat ani na klientovi, ani v abstraktním rozhraní.
        for obj in (RigControl, MockRig, RigctldClient):
            members = {name.lower() for name in dir(obj)}
            self.assertNotIn("send_raw_command", members)
            self.assertNotIn("send_command", members)
            self.assertNotIn("raw", members)


class Log4OMNoAutoSaveTests(unittest.TestCase):
    def test_log4om_source_has_no_save_or_commit_wording(self):
        path = PACKAGE_ROOT / "log4om.py"
        text = path.read_text(encoding="utf-8")
        # "uloží"/"uložit" smí být jen v záporném kontextu (dokumentace, že se
        # NEukládá) -- ověříme přímo, že žádná definovaná funkce/metoda se
        # nejmenuje se save/log/commit_qso.
        forbidden_defs = re.findall(r"^\s*def (save_qso|log_qso|commit_qso|confirm_qso)\b", text, re.MULTILINE)
        self.assertEqual(forbidden_defs, [])


if __name__ == "__main__":
    unittest.main()
