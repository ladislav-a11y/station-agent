# Evidence pro nezávislý audit -- Station Agent, oprava P5

Tento soubor je **evidence**, ne verdikt. Podle runtime contractu smí
`accepted`/`rejected` vynést výhradně ai-orchestrator; agent (tento běh)
smí pouze shromáždit a zaznamenat ověřitelná fakta o aktuálním stavu
checkoutu pro tuto konkrétní opravu ("Station Agent -- oprava P5").

## Rozsah opravy P5 (viz `DIAGNOSIS_P5.md`)

Skutečná příčina hlášeného "Station Agent nejde spustit" byla řetězec
nezachycených výjimek (`FileNotFoundError`, `ValueError`, `TypeError`,
`sqlite3.DatabaseError`, `OSError`) na cestě `main() -> load_config() ->
build_app_state() -> refresh_candidates() -> create_server()`. Oprava
přidala cílené `try/except` bloky s akčními českými hláškami a úklidem
zdrojů (`db.close()`/`rig.close()`/`aggregator.close()`) a k ní 19
regresních testů.

## Ověření provedené tuto iteraci (read-only, žádná změna chování)

1. **HEAD**: `6512676` (`[ai-orchestrator] Controller finalization: ...`).
   `git status --porcelain` je čistý -- žádné neuložené změny.
2. **Statická kontrola zdrojového kódu** -- ruční průchod
   `station_agent/config.py` (`load_config`, `_load_yaml_text`,
   `_parse_scalar`/`_parse_flow_list`, `WebConfig.__post_init__`) a
   `station_agent/cli.py` (`build_sources`, `build_app_state`, `main`):
   všech 11 tříd chyb popsaných v `DIAGNOSIS_P5.md` má odpovídající
   `try/except` větev s akční hláškou a úklidem zdrojů, přesně podle
   dokumentu.
3. **Syntaxe**: `ast.parse` nad `station_agent/config.py`,
   `station_agent/cli.py`, `tests/test_config.py`,
   `tests/test_cli_sources.py` -- bez chyby.
4. **Existence regresních testů**: všech 10 testů v `tests/test_config.py`
   a všech 10 v `tests/test_cli_sources.py` jmenovaných v
   `DIAGNOSIS_P5.md::Testy` je v souborech přítomno přesně jednou (žádný
   chybí, žádný duplicitní).
5. **Kompletní test suite**: podle výsledku předané orchestrátorem z
   minulé iterace `python -m pytest -q` PROŠLY. Tento agent testy sám
   nespouštěl (spouštění testů je vyhrazeno orchestrátoru).
6. **Bezpečnostní invarianty** (`AGENTS.md`): opravou dotčené soubory
   (`config.py`, `cli.py`) neobsahují žádný zásah do `rig/`, PTT řetězce,
   ovládání rotátoru ani Log4OM auto-save -- mimo rozsah P5 opravy a beze
   změny.

## Závěr evidence (ne verdikt)

Nebyl nalezen žádný rozpor mezi popisem opravy v `DIAGNOSIS_P5.md` a
skutečným stavem souborů v HEAD `6512676`. Implementace i regresní testy
pro "Station Agent -- oprava P5" jsou v checkoutu přítomné, syntakticky
validní a podle poslední zprávy orchestrátora testovaly zeleně. Formální
`accepted`/`rejected` verdikt vynáší výhradně ai-orchestrator na základě
této a případné další evidence.
