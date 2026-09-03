# Station Agent - Project Notes

## Prostředí

* OS: Windows 11
* Projekt: D:\\orchestrator\\station-agent
* Shell: PowerShell
* Python: 3.14.7

## Známé problémy

### PowerShell a YAML

* Nevkládat YAML bloky přímo do PowerShell konzole.
* Nepoužívat složité replace příkazy s vloženými `n a escapovanými uvozovkami.
* Při úpravách YAML kontrolovat odsazení.

### Kódování

* Soubory ukládat jako UTF-8.
* Pozor na špatné zobrazení češtiny v PowerShell výpisu.

## DX Cluster

* Server: dxc.w3lpl.net
* Port: 7373
* Login: callsign
* Stanice: OK1RPL
* Jméno: Ladislav
* QTH: Pilsen
* Locator: JN69QR

## Aktuální stav

* TCP spojení DX Cluster ověřeno.
* Přihlášení OK1RPL funguje.
* DX spoty se načítají ručně.
* Probíhá dokončení integrace DXClusterAdapter.

\## DX Cluster integrace - dokončeno 25.08.2026



\- Připojení k dxc.w3lpl.net:7373 funkční.

\- Login OK1RPL funkční.

\- Automatické odeslání sh/dx po připojení.

\- Parser podporuje:

&#x20; - původní DXSpider formát "DX de CALL:"

&#x20; - aktuální W3LPL živý formát bez prefixu.

\- Spoty se převádí do interního modelu Spot.

\- Kompletní testy: 192 passed.

## Přepnutí na reálný provoz -- 03.09.2026

* Vyřízen Inbox požadavek "Station agent -- přepnutí na reálný režim".
* Lokální `config.yaml` (gitignored, mimo repozitář) přepnut na připravené
  a živě ověřené části (viz `LIVE_EVIDENCE.md`): `station.callsign: OK1RPL`,
  `station.qth_locator: JN69QR`, `rig.mode: live`, `sources.mock.enabled:
  false`, `sources.dx_cluster/rbn/pskreporter.enabled: true`.
* `log4om.enabled` zůstává `false` -- payload proti reálné instanci Log4OM2
  není ověřený (viz `AUDIT_MOCK_MODE.md` bod 3), tedy není "připravená
  část" ve smyslu Inbox požadavku.
* Alternativní DX Cluster uzly (`dx_cluster_hamserve/ea7jxh/m0mhx`) zůstávají
  vypnuté -- jde o volitelné náhrady primárního uzlu, ne o další povinný
  souběžný zdroj.
* Žádná změna kódu v `station_agent/` -- vše potřebné bylo už dřív hotové a
  živě ověřené, šlo jen o konfigurační přepnutí v uživatelově vlastním
  souboru.

## Live test v PowerShell -- 03.09.2026

* Vyřízen Inbox požadavek "Station agent -- live test v PowerShell" v
  rozsahu, který jde ověřit bez fyzicky připojeného IC-7300 (viz
  `LIVE_EVIDENCE.md` bod 6): `python -m station_agent --config config.yaml`
  s ostrým `config.yaml` (rig.mode live, dx_cluster/rbn/pskreporter
  enabled) skutečně naběhl, GUI i `/api/status`/`/api/candidates`
  odpověděly, chybějící rigctld se odbrzdil korektně (fail-open, ne pád).
* Nalezen a opraven reálný bug objevený jen díky živým datům:
  `bearing.py::maidenhead_to_latlon` odmítal validní 8/10znakové rozšířené
  Maidenhead locatory, které PSKReporter reálně posílá u části stanic --
  bearing se tak ztrácel u ~10 % živých kandidátů. Opraveno + regresní
  testy v `tests/test_bearing.py`.
* Fyzické připojení IC-7300 přes `rigctld` zůstává na uživateli -- v tomto
  prostředí není žádný rig k dispozici, jde o nutně manuální krok mimo
  dosah agenta.

## Diagnostika nestandardního chování z live testu -- 03.09.2026

* Vyřízen Inbox požadavek "Station agent -- diagnostika nestandardního
  chování". Nestandardní chování: po hodinách nepřetržitého live provozu
  (viz sekce výše) `station_agent.sqlite3` narostl na **295 MB**, přestože
  `app_state.refresh_candidates()` volá `db.purge_older_than()` při každém
  refresh cyklu a v tabulce `spots` reálně zůstávalo jen 8210 řádků
  odpovídajících oknu `spot_max_age_minutes`.
* Kořenová příčina: `Database` nikdy nezapínal SQLite `auto_vacuum`. Bez
  něj DELETE jen přesune uvolněné stránky do interního freelistu souboru,
  ale OS je nedostane zpět -- ověřeno přímo na souboru: `PRAGMA page_count`
  72051, `PRAGMA freelist_count` 71817 (99,7 % souboru byla mrtvá volná
  místa, ne data). Existující komentář v `app_state.py` u volání
  `purge_older_than` mylně předpokládal, že pravidelné mazání řádků samo
  o sobě zabrání růstu souboru na disku.
* Oprava v `station_agent/db.py`: nová `Database._enable_incremental_vacuum()`
  jednorázově (jen pro soubor, ne `:memory:`) přepne `PRAGMA auto_vacuum =
  INCREMENTAL` a provede `VACUUM` (u existující databáze je to jediný
  způsob, jak režim aktivovat a zároveň hned zkomprimovat nahromaděný
  freelist). `purge_older_than()` navíc po každém smazání zavolá `PRAGMA
  incremental_vacuum` (a `.fetchall()` na kurzoru -- sqlite3 modul jinak
  stepuje jen první uvolněnou stránku na `.execute()`, zbytek freelistu by
  bez fetchall zůstal neuvolněný), aby stránky uvolněné dalším provozem
  nečekaly na příští restart.
* Ověřeno na reálném `station_agent.sqlite3` z tohoto live provozu: po
  otevření přes opravenou `Database` klesla velikost souboru z 295 120 896
  na 913 408 bajtů, `freelist_count` na 0.
* Nové regresní testy `tests/test_db.py::DatabaseFileGrowthTests` (nová
  databáze má `auto_vacuum=INCREMENTAL`; vložení a smazání 500 spotů
  soubor na disku skutečně zmenší, ne jen vyprázdní řádky).
* Mimo rozsah beze změny -- žádný adaptér, scoring, rig ani web GUI kód
  nebyl dotčen.

## Nezávislé opětovné ověření opravy pod živou zátěží -- 03.09.2026

* Vyřízen Inbox požadavek "Station agent -- oprava nalezeného problému":
  nezávisle ověřeno, že oprava růstu `station_agent.sqlite3` (sekce výše,
  `Database._enable_incremental_vacuum()` + `purge_older_than()` volající
  `PRAGMA incremental_vacuum`) skutečně drží soubor na disku malý i po
  reálném běhu celého procesu, ne jen v testech na `:memory:`/dočasném
  souboru.
* Postup: `python -m station_agent --config config.yaml` (ostrý config,
  `rig.mode: live`, `sources.dx_cluster/rbn/pskreporter.enabled: true`)
  spuštěn jako reálný proces, `/api/status` a `/api/candidates` dotázány
  přes `urllib.request` v běhu. PSKReporter doručil 1509 živých spotů,
  `dx_cluster`/`rbn` korektně `status: pending` během navazování telnet
  spojení (žádný pád, žádná nová anomálie v logu -- jediný log řádek byl
  startovní `Station Agent GUI na http://127.0.0.1:8765 (rig mode=live)`).
* Přímo na `station_agent.sqlite3` použitém tímto živým během (5000 vložených
  spotů přes reálný `insert_spots`/`purge_older_than` cyklus): `PRAGMA
  auto_vacuum` vrátilo `2` (INCREMENTAL), `PRAGMA freelist_count` `0`,
  velikost souboru na disku `626 688` bajtů -- oprava tedy funguje i mimo
  jednorázový test, freelist se nehromadí ani po opakovaném vkládání a
  mazání pod reálným provozem.
* Žádný nový bug nebyl touto nezávislou live verifikací odhalen -- proces
  startuje čistě, GUI/API odpovídají, zdroje se chovají podle
  `DATA_CONTRACT.md` (fail-open `pending`/`ok` přechody). Žádný kód v
  `station_agent/` touto iterací nebyl měněn, jde čistě o dokumentované
  nezávislé ověření již existující opravy pod skutečnou zátěží.

## Oprava logiky spouštění AUTO TUNE po vypršení doby držení -- 03.09.2026

* Vyřízen Inbox požadavek "Station Agent -- oprava logiky spouštění
  autotune po vypršení doby držení": po ručním NALADIT (tlačítko v GUI)
  `AppState.manual_tune()` natrvalo vypínal AUTO TUNE (`enabled=False`) a
  zapínal HOLD (`hold=True`), ale nic HOLD nikdy automaticky nevypnulo --
  `AutoTuneEngine.decide()` se na `cfg.enabled` ptal ještě před kontrolou
  HOLD, takže AUTO TUNE zůstal navždy vypnutý i po libovolně dlouhé době
  (dávno za `min_hold_seconds`), dokud operátor ručně neklikl na AUTO TUNE
  v GUI.
* Oprava (commit `9672bb9`): `AutoTuneEngine.decide()`
  (`station_agent/autotune.py`) na začátku vyhodnocení zkontroluje, jestli
  je HOLD aktivní a od `current.tuned_at` uplynulo aspoň
  `min_hold_seconds` -- pokud ano, `cfg.hold=False`/`cfg.enabled=True` a
  pokračuje běžným vyhodnocením. `PollingLoop._run()` volá
  `run_autotune_cycle()` v každém cyklu, takže se auto-expirace HOLD
  vyhodnotí i bez zásahu operátora, ne jen při další ruční akci.
* Cosmetic API pole `hold_remaining_seconds` (vždy `None`,
  `web/server.py::_build_status`) zůstává záměrně beze změny -- GUI během
  aktivního HOLD schválně nezobrazuje odpočet (`test_manual_tune.py::
  test_manual_tune_reports_no_countdown_while_hold_active`), to je mimo
  rozsah tohoto bugu.
* Regresní testy (beze změny od commitu `9672bb9`, touto iterací pouze
  znovu ověřeny): `tests/test_autotune.py::AutoTuneEngineTests::
  test_hold_blocks_until_min_hold_seconds_elapses_since_current_tuned_at`,
  `::test_hold_auto_expires_after_min_hold_seconds_and_autotune_resumes`,
  `::test_hold_expiry_ignored_when_no_current_station`;
  `tests/test_manual_tune.py::ManualTuneAppStateTests::
  test_manual_tune_then_hold_expiry_autoresumes_autotune_without_manual_action`.
* Žádná další změna kódu v `station_agent/` touto iterací -- oprava byla
  funkčně kompletní už v `9672bb9`, jde o doplnění chybějícího záznamu o
  vyřízení tohoto konkrétního Inbox požadavku do `PROJECT_NOTES.md`.
