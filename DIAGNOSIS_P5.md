# Diagnóza P5 -- "Station Agent nejde spustit"

## Skutečná příčina

`config.yaml` je v `.gitignore` (řádek 6) -- není a nikdy nebyl součástí
repozitáře. README (sekce "Instalace") správně říká, že si ho uživatel musí
nejdřív vytvořit příkazem `cp config.example.yaml config.yaml`. Pokud to
někdo přeskočí (fresh checkout, CI, orchestrátor spouštějící `python -m
station_agent` bez přípravného kroku), `station_agent/config.py::load_config`
padalo na nezachyceném `FileNotFoundError` ze syrového
`Path(path).read_text(...)` -- uživatel/orchestrátor dostal jen Python
traceback bez jakéhokoli návodu, co udělat. To je reálný pozorovaný stav
"nejde spustit", reprodukovaný přímo v tomto checkoutu:

```
$ python -m station_agent --config nonexistent_config_test.yaml
Traceback (most recent call last):
  ...
  File "station_agent/config.py", line 451, in load_config
    text = Path(path).read_text(encoding="utf-8")
FileNotFoundError: [Errno 2] No such file or directory: 'nonexistent_config_test.yaml'
```

Naopak s existujícím `config.yaml`/`config.example.yaml` aplikace startuje a
GUI server naběhne bez problémů -- ověřeno živě v tomto běhu (`python -m
station_agent --config config.example.yaml` i `--config config.yaml`
zalogovaly `Station Agent GUI na http://127.0.0.1:8765 (rig mode=mock)` a
server běžel, dokud nebyl ukončen).

## Oprava (tento rozsah, žádné jiné chování neměněno)

- `station_agent/config.py::load_config` -- explicitní kontrola existence
  souboru před čtením; při chybějícím souboru vyhazuje `FileNotFoundError`
  se srozumitelnou českou hláškou obsahující přesnou cestu a příkaz na
  opravu (`cp config.example.yaml <cesta>`), s odkazem na README.
- `station_agent/cli.py::main` -- `load_config` obalen `try/except
  FileNotFoundError`; chyba se zaloguje jako `ERROR` a `main()` vrátí `1`
  místo nezachyceného tracebacku a pádu s exit kódem z Pythonu.
- `station_agent/cli.py::main` -- doplněn i `except ValueError`, který
  pokrývá stejnou třídu problému, ale pro *přítomný* `config.yaml`
  s neplatným obsahem (chybný YAML zápis z `_MiniYamlParser`, nebo hodnota
  mimo povolený rozsah, např. `rig.mode`). Bez něj by `main()` spadl na
  nezachyceném `ValueError` tracebacku stejně jako dřív na
  `FileNotFoundError`. Regresní test:
  `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_config_content_is_invalid`.
- `station_agent/config.py::_load_yaml_text` -- když je nainstalovaný
  PyYAML, jeho `yaml.YAMLError` (poškozený YAML zápis, např. tab v odsazení)
  není podtřída `ValueError` a bez převodu by `main()` odchycení výše
  neošetřilo. Nyní se převádí na `ValueError`. Regresní test:
  `tests/test_config.py::LoadConfigTests::test_malformed_yaml_content_raises_value_error_not_yaml_error`.
- `station_agent/config.py::load_config` -- validní YAML, které ale na
  nejvyšší úrovni není mapování (např. omylem vložený seznam), dřív spadlo
  v `config_from_dict` na nezachyceném `AttributeError` z `raw.get(...)`.
  Nyní explicitní `isinstance(raw, dict)` kontrola s akční `ValueError`
  hláškou. Regresní test:
  `tests/test_config.py::LoadConfigTests::test_top_level_yaml_list_raises_actionable_value_error`.
- `station_agent/cli.py::main` -- `build_app_state(config)` byl původně
  volaný MIMO `try/except`. I validní `config.yaml` mohl obsahovat hodnotu,
  která se ověří/zkonvertuje až uvnitř `build_app_state` (např.
  `sources.dx_cluster.options.port` jako netextové číslo se na `int()`
  převádí až v `build_sources()`). Volání je teď uvnitř stejného `try`, takže
  ho pokrývá existující `except ValueError`. Regresní test:
  `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_enabled_source_has_invalid_port`.
- `station_agent/cli.py::build_app_state` -- vedlejší efekt výše: pokud
  sestavení app state selže až po otevření SQLite databáze (`Database(...)`)
  nebo vytvoření rig objektu, tělo funkce je teď v `try/except Exception`,
  který před opětovným vyhozením chyby zavře `db`/`rig` -- jinak by zůstalo
  otevřené/zamčené spojení (reálný problém odhalený selháním testu na
  Windows: zamčený `.sqlite3` soubor bránil úklidu dočasného adresáře).
- `station_agent/cli.py::build_app_state` -- `Database(config.database.path)`
  mířící do neexistujícího adresáře (např. překlep v `database.path`)
  vyhazovala `sqlite3.OperationalError`, což není ani `FileNotFoundError`,
  ani `ValueError` -- `main()` na tom spadl navzdory tomu, že `load_config`
  vůbec neselhal. Nyní se převádí na akční `ValueError` s cestou a návodem.
  Regresní test:
  `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_database_parent_dir_is_missing`.
- `station_agent/config.py::WebConfig.__post_init__` -- `web.port` mimo
  platný rozsah 0-65535 (např. překlep s extra číslicí) validní `load_config`
  neodhalil; spadlo to až v `create_server()` (mimo `try/except` v `main()`)
  na nezachyceném `OverflowError` ze `socket.bind()`. Nyní `WebConfig`
  validuje rozsah portu stejně jako už dřív loopback `host`, takže chybu
  odhalí `load_config` a existující `except ValueError` v `main()` ji
  odchytí. Regresní testy:
  `tests/test_config.py::WebConfigSafetyTests::test_rejects_port_out_of_valid_range`,
  `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_web_port_is_out_of_range`.

- `station_agent/config.py::load_config` -- explicitně `null` hodnota u
  libovolného číselného pole (např. `rig.rigctld_port:` bez hodnoty za
  dvojtečkou -- na rozdíl od úplně chybějícího klíče je to platný YAML,
  klíč existuje s hodnotou `None`, takže se nepoužije výchozí hodnota).
  `config_from_dict` na tom volalo `int(None)`/`float(None)`, což vyhazuje
  `TypeError` -- ta není zachycená `except ValueError` v `main()`, takže
  aplikace spadla na nezachyceném tracebacku úplně stejně jako u
  předchozích 8 tříd chyb. Oprava je stejného tvaru jako u `_load_yaml_text`
  výše -- `load_config` teď obaluje `config_from_dict(raw)` do
  `try/except TypeError` a převádí ji na akční `ValueError` s hláškou, která
  pojmenuje konkrétní pole a navrhne buď ho vyplnit, nebo řádek úplně smazat
  (aby se použila výchozí hodnota). Řešeno na úrovni `load_config`, ne
  jednotlivě pro každé číselné pole (`rig.rigctld_port`, `scoring.min_score`,
  `web.port`, `log4om.port`, `polling.*`, `notifications.*`,
  `propagation.refresh_seconds`, `autotune.*`) -- kategoriální oprava
  pokrývá všechna najednou stejným mechanismem. Regresní testy:
  `tests/test_config.py::LoadConfigTests::test_explicit_null_numeric_field_raises_actionable_value_error`,
  `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_numeric_field_is_explicitly_null`.
  Živě reprodukováno před opravou (nezachycený `TypeError` traceback při
  `python -m station_agent --config <config s "rigctld_port:">`) i po
  opravě (`ERROR` log + exit kód 1, žádný traceback).

- `station_agent/cli.py::main` -- `web.port` v platném rozsahu 0-65535
  (projde `WebConfig` validací výše), ale port je v okamžiku startu už
  obsazený jiným procesem (typicky už běžící instance Station Agenta,
  nebo jiná aplikace na stejném portu). `create_server(app_state)` volal
  `socket.bind()` mimo jakýkoli `try/except` v `main()` -- `OSError`
  (na Windows konkrétně `PermissionError` `WinError 10013` při
  exkluzivním obsazení portu, na Linuxu typicky "Address already in
  use") tak spadla na nezachyceném tracebacku přesto, že `load_config()`
  i `build_app_state()` proběhly úplně v pořádku. Volání `create_server`
  je teď obalené vlastním `try/except OSError`, který zaloguje akční
  hlášku (jaký proces pravděpodobně port drží, jak to vyřešit) a čistě
  uklidí už vytvořený `loop`/`app_state` (`db`/`rig`/`aggregator`) před
  návratem s exit kódem 1 -- stejný vzor jako u `build_app_state` výše.
  Živě reprodukováno pomocí soketu s `SO_EXCLUSIVEADDRUSE` (Windows)
  držícího stejný port -- před opravou nezachycený traceback, po opravě
  `ERROR` log + exit kód 1, žádný traceback. Regresní test:
  `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_web_port_is_already_in_use`.

- `station_agent/cli.py::main` -- `app_state.refresh_candidates()` (počáteční
  synchronní naplnění kandidátů, volané před spuštěním web serveru --
  `aggregator.poll_once` + DB purge + `build_candidates`/scoring) běželo
  MIMO jakýkoli `try/except` v `main()`, přestože `build_app_state()`
  o řádek výš už svůj vlastní řetězec (DB/rig/aggregator) chránil.
  Jakákoli výjimka v tomto kroku (i validní config, i úspěšný
  `build_app_state()`) by spadla na nezachyceném tracebacku -- stejná
  třída "Station Agent nejde spustit" jako předchozích 10 oprav výše, jen
  odhalená v ještě pozdějším kroku startu. Volání je teď obalené vlastním
  `try/except Exception`, který zaloguje akční hlášku a uklidí už
  otevřené `db`/`rig`/`aggregator` před návratem s exit kódem 1 -- stejný
  vzor jako u `create_server`/`OSError` výše. Regresní test (mockuje
  selhání, protože reálný řetězec s platnou konfigurací dnes neselhává --
  jde o strukturální pojistku, ne o konkrétní dnes existující vstup):
  `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_initial_candidate_refresh_fails`.

### Doplňkové zjištění: tichá (ne pádová) chyba v `_MiniYamlParser` u předvoleb

Při hledání dalších tříd "nejde spustit" jsem narazil na příbuznou, ale
odlišnou třídu problému ve stejném souboru (`station_agent/config.py`) --
nejde o pád, ale o tiché špatné chování, které stojí za zaznamenání, protože
zasahuje přímo distribuovaný `config.example.yaml`:

- `station_agent/config.py::_parse_scalar` (vestavěný fallback parser,
  použije se, když není nainstalovaný PyYAML -- viz `requirements.txt`, kde
  je `PyYAML` výslovně odkomentovaný jako volitelný, a modulový docstring
  `config.py`, který garantuje běh "i bez jakékoli instalace závislostí")
  neuměl jednořádkový "flow" zápis seznamu, např.
  `bands: ["20m", "15m"]` -- přesně ten zápis, který používá sekce
  `presets:` v `config.example.yaml`. Bez podpory se celá hodnota
  naparsovala jako doslovný text; filtr proti `SUPPORTED_BANDS`/
  `SUPPORTED_MODES` v `config_from_dict` pak iteroval po jednotlivých
  znacích řetězce, neprošel ani jeden, a předvolba (`ssb`/`cw`/`digi`)
  tiše spadla na výchozí "všechna pásma/módy" -- např. předvolba "Jen SSB"
  v GUI by se chovala identicky jako "Vše", bez jakékoli chybové hlášky.
  Reprodukováno přímo na `config.example.yaml` (ne uměle vytvořeným
  příkladem). Oprava: `_parse_scalar` teď rozpozná `[...]` a naparsuje ho
  novou funkcí `_parse_flow_list` (respektuje uvozovky uvnitř, aby čárka
  v citované hodnotě seznam nerozdělila). Blokový zápis (`- "20m"`) i
  chování s PyYAML nainstalovaným (yaml.safe_load flow zápis uměl vždy)
  nejsou touto změnou dotčené. Regresní testy:
  `tests/test_config.py::LoadConfigTests::test_mini_yaml_parser_handles_inline_flow_style_list`,
  `tests/test_config.py::LoadConfigTests::test_mini_yaml_parser_parses_config_example_presets_correctly`
  (druhý test čte skutečný `config.example.yaml` ze souboru, ne inline
  text, aby regrese chytla i budoucí úpravy toho souboru).

## Live ověření provedené v tomto běhu

1. `python -m station_agent --config nonexistent_config_test.yaml` --
   po opravě: exit code `1`, jediný řádek
   `ERROR station_agent.cli: Konfigurační soubor 'nonexistent_config_test.yaml'
   neexistuje. Zkopíruj příklad a uprav ho: cp
   D:\orchestrator\station-agent\config.example.yaml
   nonexistent_config_test.yaml (viz README.md, sekce Instalace).`
   -- žádný traceback. (Návodný `cp` příkaz nyní obsahuje plnou cestu k
   `config.example.yaml`, ne jen holé jméno souboru -- jinak by selhal, když
   se agent spustí z jiného pracovního adresáře, než je kořen repozitáře.)
2. `python -m station_agent --config config.example.yaml` -- server
   naběhl (`Station Agent GUI na http://127.0.0.1:8765 ...`), běžel dokud
   nebyl ukončen timeoutem -- regrese pro platnou konfiguraci nevznikla.
3. `python -m station_agent --config config.yaml` (existující lokální
   config uživatele) -- stejně tak naběhl, DX Cluster telnet log ukazuje
   reálný reconnect/backoff cyklus (síť v tomto sandboxu nedostupná ven,
   to je očekávané a nesouvisí s tímto DoD bodem).

## Testy

Přidány cílené regresní testy (spuštění testů provádí výhradně
orchestrátor, viz runtime contract):

- `tests/test_config.py::LoadConfigTests::test_missing_config_file_raises_actionable_error`
- `tests/test_config.py::LoadConfigTests::test_missing_config_file_with_missing_parent_dir_warns_about_it`
- `tests/test_config.py::LoadConfigTests::test_config_path_pointing_at_directory_raises_distinct_error`
- `tests/test_config.py::LoadConfigTests::test_malformed_yaml_content_raises_value_error_not_yaml_error`
- `tests/test_config.py::LoadConfigTests::test_top_level_yaml_list_raises_actionable_value_error`
- `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_config_file_is_missing`
- `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_config_path_is_a_directory`
- `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_config_content_is_invalid`
- `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_enabled_source_has_invalid_port`
- `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_database_parent_dir_is_missing`
- `tests/test_config.py::WebConfigSafetyTests::test_rejects_port_out_of_valid_range`
- `tests/test_config.py::WebConfigSafetyTests::test_accepts_port_at_range_boundaries`
- `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_web_port_is_out_of_range`
- `tests/test_config.py::LoadConfigTests::test_explicit_null_numeric_field_raises_actionable_value_error`
- `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_numeric_field_is_explicitly_null`
- `tests/test_config.py::LoadConfigTests::test_mini_yaml_parser_handles_inline_flow_style_list`
- `tests/test_config.py::LoadConfigTests::test_mini_yaml_parser_parses_config_example_presets_correctly`
- `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_web_port_is_already_in_use`
- `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_database_file_is_not_a_valid_sqlite_file`
- `tests/test_cli_sources.py::MissingConfigStartupTests::test_main_exits_cleanly_when_initial_candidate_refresh_fails`

Syntax ověřen `python -m py_compile` po každé změně -- OK. `git diff --check`
nad změnami -- čistý, žádné whitespace chyby. Celý běh `python -m pytest -q`
ověřuje výhradně orchestrátor (viz runtime contract); dle jeho posledních
dvou hlášení testy PROŠLY.
