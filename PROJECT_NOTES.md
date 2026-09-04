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

## Opakované nezávislé ověření -- iterace 2/10 -- 03.09.2026

* Přístup k Trello Inbox (`trelloReadInbox`/`trelloSearch`) byl v tomto
  běhu opět zamítnut oprávněním (stejně jako minulou iteraci) -- přesný
  text/scénář karty tedy nelze z Trello přímo dohledat. Postupováno podle
  runtime contractu (agent nesmí Trello číst sám -- řízení je `AI Project
  Manager -> ai-orchestrator -> agents`, PM zadání už předal v promptu).
* Znovu nezávisle ověřen scénář popsaný v `DIAGNOSIS_P5.md`/
  `AUDIT_EVIDENCE_P5.md` ("Station Agent nejde spustit"): všech 20
  jmenovaných regresních testů (`tests/test_config.py`,
  `tests/test_cli_sources.py`) v checkoutu skutečně existuje přesně
  jednou, `station_agent/cli.py::build_app_state`/`main` obsahují
  odpovídající `try/except` větve pro všech 11 popsaných tříd chyb
  (`FileNotFoundError`, `ValueError`, `TypeError`, `sqlite3.DatabaseError`,
  `OSError`) s úklidem `db`/`rig`/`aggregator` přesně podle dokumentu.
  `ast.parse` nad `config.py`/`cli.py`/oběma testovacími soubory bez chyby.
  Žádný z 5 commitů mezi HEAD `6512676` (kdy vznikla `AUDIT_EVIDENCE_P5.md`)
  a aktuálním HEAD se `cli.py`/`config.py` vůbec nedotkl (viz `git log
  --stat`), takže scénář P5 zůstává neporušený.
* Nejnovější popsaný scénář v projektu -- AUTO TUNE HOLD auto-expiry (sekce
  výše) -- byl touto iterací opět staticky ověřen (`autotune.py::decide`,
  `tests/test_autotune.py`, `tests/test_manual_tune.py`): beze změny od
  minulé iterace, logika i testy zůstávají konzistentní.
* Výsledek testů z minulé iterace (`python -m pytest -q`), ověřeno
  orchestrátorem: PROŠLY.
* Žádná změna produkčního kódu v `station_agent/` touto iterací -- oba
  nezávisle ověřené scénáře jsou funkčně beze změny a bez nalezené regrese;
  jde čistě o doplnění důkazního záznamu pro nezávislý audit
  ai-orchestrátoru, který jediný smí vynést verdikt `accepted`/`rejected`.

## Nesoulad rozsahu zadání -- iterace 1/10 -- 04.09.2026

* Zadaný cíl iterace ("Oprava Project manager: nezávislý audit
  orchestrátoru musí umět odhalit nesoulad mezi kartou označenou v Trellu
  jako hotovou a skutečným stavem implementace...") popisuje opravu
  auditní logiky samotného `ai-orchestrator`/AI Project Manager. Tento
  repozitář (`D:\orchestrator\station-agent`) ale obsahuje výhradně
  aplikaci Station Agent (`station_agent/` -- rádiový asistent pro
  IC-7300/DX Cluster/RBN/PSKReporter); žádný kód `ai-orchestrator`, AI
  Project Manager ani Trello auditní logiky se v něm nikdy nenacházel a
  ani teď nenachází (ověřeno `grep` přes celý strom -- jediné výskyty
  slova "audit"/"orchestr" jsou existující evidenční `.md` dokumenty a
  komentáře k testům pro dřívější Station Agent opravy, ne implementace
  auditu). Přístup mimo `D:\orchestrator\station-agent` je navíc v tomto
  běhu sandboxem přímo zamítnut (`D:\orchestrator` nelze ani vypsat).
* Podle `AGENTS.md` (jasně vymezený rozsah repozitáře) a runtime
  contractu ("Missing, unknown, or ambiguous project identity fails
  closed: do not dispatch and do not infer a repository from title,
  description, priority, or slug") by přidání auditní logiky
  ai-orchestrátoru do balíčku `station_agent/` bylo přidáním kódu zcela
  mimo rozsah a účel tohoto projektu -- proto touto iterací nebyl přidán
  žádný takový kód.
* Žádná změna produkčního kódu v `station_agent/`. DoD bod zůstává
  nesplněný -- jeho realizace patří do repozitáře `ai-orchestrator`/AI
  Project Manager, ne do Station Agent.

## Opakované ověření nesouladu rozsahu -- iterace 2/10 -- 04.09.2026

* Stejný cíl iterace zadán znovu. Nezávisle znovu ověřeno: `station_agent/`
  ani zbytek repozitáře stále neobsahuje žádný kód ai-orchestrator/AI
  Project Manager/Trello auditu; přístup mimo
  `D:\orchestrator\station-agent` je sandboxem session stále zamítnutý
  (`D:\orchestrator` nelze vypsat). Závěr z iterace 1 se nemění.
* Testy z minulé iterace (`python -m pytest -q`), ověřeno orchestrátorem:
  PROŠLY. Touto iterací žádná změna produkčního kódu, jen doplnění tohoto
  záznamu.

## Nová série -- opakované ověření nesouladu rozsahu -- iterace 1/10 -- 04.09.2026

* Předchozí série (10 iterací) skončila se stejným závěrem: cíl ("Oprava
  Project manager: nezávislý audit orchestrátoru...") je auditní logika
  `ai-orchestrator`/AI Project Manager, ne Station Agent. Tato nová série
  začíná znovu od iterace 1/10 se stejným zadáním -- nezávisle znovu
  ověřeno, že se na okolnostech nic nezměnilo: `grep` přes `station_agent/`
  po `ai-orchestrator|AI Project Manager|independent audit|audit_verdict`
  nenašel žádnou shodu (jen dosavadní evidenční `.md` dokumenty a
  komentáře), a přístup mimo `D:\orchestrator\station-agent` je sandboxem
  této session stále přímo zamítnutý (`ls D:/orchestrator` selhalo s
  "may only list files in the allowed working directories ...
  station-agent").
* Žádná změna produkčního kódu v `station_agent/`. DoD bod zůstává
  nesplněný ze stejného důvodu jako v celé minulé sérii -- jeho realizace
  patří výhradně do repozitáře `ai-orchestrator`/AI Project Manager.
  Doporučení z minulé série trvá: kartu na úrovni orchestrátoru/PM
  přerouteovat na správný projekt nebo ji označit jako nedispatchovatelnou
  pro station-agent, jinak tato nová série jen zopakuje stejný výsledek.

## Nová série -- opakované ověření nesouladu rozsahu -- iterace 2/10 -- 04.09.2026

* Stejné zadání znovu. Nezávisle znovu ověřeno: `git status --porcelain`
  ukazuje jen tuto poznámku, HEAD je stále na commitu s předchozí
  finalizací (`32196e2`), přístup mimo `D:\orchestrator\station-agent` je
  sandboxem stále zamítnutý (`ls D:/orchestrator` selhalo stejnou hláškou
  jako v iteraci 1). Testy z minulé iterace (`python -m pytest -q`),
  ověřeno orchestrátorem: PROŠLY. Závěr se nemění -- viz iterace 1 výše.
* Žádná změna produkčního kódu v `station_agent/`.

## Nová série -- opakované ověření nesouladu rozsahu -- iterace 3/10 -- 04.09.2026

* Stejné zadání znovu. Nezávisle znovu ověřeno: `git status --porcelain`
  ukazuje jen tuto poznámku, přístup mimo `D:\orchestrator\station-agent`
  je sandboxem stále zamítnutý (`ls D:/orchestrator` selhalo stejnou
  hláškou jako v iteracích 1-2). Testy z minulé iterace (`python -m
  pytest -q`), ověřeno orchestrátorem: PROŠLY. Závěr se nemění -- viz
  iterace 1 výše.
* Žádná změna produkčního kódu v `station_agent/`.

## Nová série -- opakované ověření nesouladu rozsahu -- iterace 4/10 -- 04.09.2026

* Stejné zadání znovu. Nezávisle znovu ověřeno: `git status --porcelain`
  ukazuje jen tuto poznámku, přístup mimo `D:\orchestrator\station-agent`
  je sandboxem stále zamítnutý (`ls D:/orchestrator` selhalo stejnou
  hláškou jako v iteracích 1-3). Testy z minulé iterace (`python -m
  pytest -q`), ověřeno orchestrátorem: PROŠLY. Závěr se nemění -- viz
  iterace 1 výše.
* Žádná změna produkčního kódu v `station_agent/`.

## Nová série -- opakované ověření nesouladu rozsahu -- iterace 5/10 -- 04.09.2026

* Stejné zadání znovu. Nezávisle znovu ověřeno: `git status --porcelain`
  ukazuje jen tuto poznámku, přístup mimo `D:\orchestrator\station-agent`
  je sandboxem stále zamítnutý (`ls D:/orchestrator` selhalo stejnou
  hláškou jako v iteracích 1-4). Testy z minulé iterace (`python -m
  pytest -q`), ověřeno orchestrátorem: PROŠLY. Závěr se nemění -- viz
  iterace 1 výše.
* Žádná změna produkčního kódu v `station_agent/`.

## Nová série -- opakované ověření nesouladu rozsahu -- iterace 6/10 -- 04.09.2026

* Stejné zadání znovu. Nezávisle znovu ověřeno: `git status --porcelain`
  ukazuje jen tuto poznámku, přístup mimo `D:\orchestrator\station-agent`
  je sandboxem stále zamítnutý (`ls D:/orchestrator` selhalo stejnou
  hláškou jako v iteracích 1-5). Testy z minulé iterace (`python -m
  pytest -q`), ověřeno orchestrátorem: PROŠLY. Závěr se nemění -- viz
  iterace 1 výše.
* Žádná změna produkčního kódu v `station_agent/`.

## Nová série -- opakované ověření nesouladu rozsahu -- iterace 7/10 -- 04.09.2026

* Stejné zadání znovu. Nezávisle znovu ověřeno: `git status --porcelain`
  ukazuje jen tuto poznámku, přístup mimo `D:\orchestrator\station-agent`
  je sandboxem stále zamítnutý (`ls D:/orchestrator` selhalo stejnou
  hláškou jako v iteracích 1-6). Testy z minulé iterace (`python -m
  pytest -q`), ověřeno orchestrátorem: PROŠLY. Závěr se nemění -- viz
  iterace 1 výše.
* Žádná změna produkčního kódu v `station_agent/`.

## Nová série -- opakované ověření nesouladu rozsahu -- iterace 8/10 -- 04.09.2026

* Stejné zadání znovu. Nezávisle znovu ověřeno: `git status --porcelain`
  ukazuje jen tuto poznámku, přístup mimo `D:\orchestrator\station-agent`
  je sandboxem stále zamítnutý (`ls D:/orchestrator` selhalo stejnou
  hláškou jako v iteracích 1-7). Testy z minulé iterace (`python -m
  pytest -q`), ověřeno orchestrátorem: PROŠLY. Závěr se nemění -- viz
  iterace 1 výše.
* Žádná změna produkčního kódu v `station_agent/`.

## Nová série -- opakované ověření nesouladu rozsahu -- iterace 9/10 -- 04.09.2026

* Stejné zadání znovu (předposlední iterace této série). Nezávisle znovu
  ověřeno: `git status --porcelain` ukazuje jen tuto poznámku, přístup
  mimo `D:\orchestrator\station-agent` je sandboxem stále zamítnutý
  (`ls D:/orchestrator` selhalo stejnou hláškou jako v iteracích 1-8).
  Testy z minulé iterace (`python -m pytest -q`), ověřeno orchestrátorem:
  PROŠLY. Závěr se nemění -- viz iterace 1 výše.
* Žádná změna produkčního kódu v `station_agent/`. Pokud i příští
  (poslední, 10.) iterace této série dopadne stejně, doporučení pro
  orchestrátor/PM zůstává: kartu přerouteovat na `ai-orchestrator` nebo ji
  označit jako nedispatchovatelnou pro station-agent -- opakování dalších
  sérií bez změny okolností přináší nulovou realnou práci.

## Nová série -- poslední (10.) iterace -- 04.09.2026

* Poslední iterace této druhé 10-iterační série. Nezávisle znovu ověřeno:
  `git status --porcelain` ukazuje jen tuto poznámku, přístup mimo
  `D:\orchestrator\station-agent` je sandboxem stále zamítnutý
  (`ls D:/orchestrator` selhalo stejnou hláškou jako po celou tuto sérii).
  `grep` přes `station_agent/` po `ai-orchestrator|AI Project
  Manager|independent audit|audit_verdict` beze shody -- stejně jako v
  iteraci 1. Testy z minulé iterace (`python -m pytest -q`), ověřeno
  orchestrátorem: PROŠLY. Závěr zůstává beze změny od iterace 1 této
  série (a beze změny od celé předchozí 10-iterační série).
* Žádná změna produkčního kódu v `station_agent/` za celou tuto (druhou)
  10-iterační sérii. DoD bod nelze splnit z tohoto repozitáře -- realizace
  patří výhradně do repozitáře `ai-orchestrator`/AI Project Manager.
  Karta byla nyní dispatchnuta do station-agent celkem 20x (dvě po sobě
  jdoucí 10-iterační série) beze změny okolností. Důrazné doporučení pro
  příští kolo: na úrovni orchestrátoru/PM tuto Trello kartu přerouteovat
  na správný projekt (`ai-orchestrator`) nebo ji trvale zablokovat/označit
  jako nedispatchovatelnou pro station-agent -- další automatické série
  do tohoto repozitáře by jen opakovaly stejný zjištěný závěr bez jakékoli
  reálné práce.

## Nová karta -- geolokační fallback (P5) -- iterace 1/10 -- 04.09.2026

* Nové zadání (odlišné od předchozích dvou sérií výše): opravit a live
  ověřit geolokační fallback -- (1) dopočet země z prefixu callsignu, když
  ji DX Cluster/RBN/PSKReporter nedodá, (2) dopočet bearing/distance
  z vlastního QTH a lokátoru protistanice, když je provider nedodá, (3)
  providerová hodnota má vždy přednost, (4) chybějící podklad se
  nevymýšlí. Na rozdíl od předchozích dvou sérií jde o funkčnost přímo
  v `station_agent/` -- ve scope tohoto repozitáře.
* Statickou kontrolou zdrojového kódu ověřeno, že implementace všech
  čtyř bodů už v HEAD existuje a je funkční:
  - `station_agent/dxcc.py::callsign_to_dxcc` -- longest-prefix-match nad
    `PREFIX_TABLE`, vrací `None` (nic nevymýšlí) pro neznámý prefix.
  - `station_agent/aggregator.py::attach_dxcc_and_bearing` -- doplní
    `candidate.country` jen když `not candidate.country` (provider
    hodnotu nikdy nepřepíše), dopočte `bearing_deg`/`distance_km` jen pro
    tu z dvojice, která chybí (`if candidate.bearing_deg is None` /
    `if candidate.distance_km is None`), přednostně z lokátoru
    protistanice (`maidenhead_to_latlon`) a až při jeho absenci/neplatnosti
    z referenčního bodu DXCC entity; neplatný lokátor se zaloguje a
    zachová jako evidence, nepřepíše se.
  - Žádný adaptér (`adapters/dx_cluster.py`, `adapters/pskreporter.py`,
    RBN) nikdy nenastavuje `Spot.country` ani `bearing_deg`/`distance_km`
    přímo -- fallback se tedy v praxi uplatní pro zemi vždy a pro
    bearing/distance vždy, když provider tyto hodnoty nedodá (což pro
    zemi platí u všech tří zdrojů, pro bearing/distance u všech tří
    zdrojů taky, protože ani jeden adaptér tato pole nenaplňuje -- jediné
    pole, které providers dodávají, je `locator` u PSKReporteru).
  - `station_agent/web/serialization.py` a `web/static/app.js` čtou
    `candidate.country`/`bearing_deg`/`distance_km` bez rozlišení
    provider-vs-fallback -- fallbacková hodnota se v GUI zobrazí úplně
    stejně jako providerová (požadavek "zobrazit shodně s providerovou
    zemí" je tedy splněný strukturálně, ne jen nahodile).
  - `tests/test_aggregator.py::DxccBearingTests` pokrývá přesně těchto
    9 scénářů: doplnění země z prefixu, neznámý prefix beze změny,
    zachování dodané země/bearing/distance beze změny, dopočet jen
    chybějící z dvojice bearing/distance oběma směry, preference lokátoru
    protistanice před DXCC referenčním bodem, 8znakový extended locator
    s písmeny na pozici extended square (reálný PSKReporter kandidát),
    neplatný lokátor -> zachování evidence + fallback na DXCC + warning
    log, a žádný bearing bez nakonfigurovaného QTH.
* Žádná změna produkčního kódu v `station_agent/` touto iterací --
  implementace i regresní testy pro všechny čtyři body zadání už v HEAD
  existují, jsou vzájemně konzistentní a žádná mezera nebyla nalezena.
  Výsledek testů z minulé iterace (`python -m pytest -q`) není k dispozici
  (viz zadání); spuštění testů provádí výhradně orchestrátor.
* Zbývající krok podle zadání je výhradně **live** audit (skutečný běh
  Station Agenta v produkčním/ne-mock režimu, živý příjem z DX Cluster/
  RBN/PSKReporter, doložení konkrétního live vzorku bez země -> země
  z prefixu, a live vzorku bez bearing/distance s lokátorem -> dopočtené
  hodnoty) -- to je podle runtime contractu i podle zadání výhradně
  v kompetenci ai-orchestrátoru, ne tohoto agenta. Tento agent proto
  žádný live vzorek nefingoval ani nesimuloval.

## Analýza mezery DXCC prefixové tabulky u stanic jako 4L5O -- iterace 1/10 -- 04.09.2026

* Nové zadání (samostatný rozsah, jen analýza a dokumentace, výslovně
  "zachovat chování mimo tento rozsah" -- žádná oprava): zjistit, proč
  stanice jako `4L5O` v dnešním živém běhu nedostanou určenou zemi/DXCC,
  a zdokumentovat konkrétní mezeru ve zdroji dat.
* Živě ověřeno přímo produkčním `adapters/pskreporter.py` proti
  `retrieve.pskreporter.info` (2026-09-04, `flowStartSeconds=-3600`):
  reálný dnešní spot `4L7T` (stejný prefix jako zadaný příklad `4L5O`)
  s `country=None`. `callsign_to_dxcc("4L5O")` i `callsign_to_dxcc("4L7T")`
  obě vrací `None` -- `station_agent/dxcc.py::PREFIX_TABLE` (95 položek)
  nemá žádný klíč začínající na `4L` (DXCC entita Georgia úplně chybí).
* Šíře: ve stejné hodině živého provozu 124 z 473 distinct callsignů
  (≈26 %) skončilo bez DXCC -- část jsou zcela chybějící entity (Georgia,
  Bosna a Hercegovina `E7`, Arménie `EK`, Korsika `TK`, Bělorusko `EW`),
  část je jemnější mezera i u pokrytých zemí (tabulka má jen `"JA"` pro
  Japonsko, ale živě přijaté `JE3GUG`/`JR4KVI` selžou stejně; jen `"G"`
  pro Anglii, ale `M0`/`M1`/`2E0` prefixy selžou stejně; jen `"UA"` pro
  Rusko, ale jednopísmenné `R7ZY`/`R1BBG`/`RN2F` selžou stejně).
* Plná analýza s reprodukovatelnými příkazy a živými vzorky:
  `DIAGNOSIS_DXCC_PREFIX_GAP.md`.
* Žádná změna produkčního kódu v `station_agent/` -- podle zadání jde
  výhradně o analýzu a zdokumentování mezery, ne o její opravu (ta by
  byla navazující, odlišná práce nad `PREFIX_TABLE`). Ověřeno
  `git status --porcelain`: mimo tuto poznámku a nový diagnostický
  dokument žádný jiný soubor touto iterací dotčen nebyl.

## Obecný QRZ.com fallback pro DXCC/zemi -- iterace 1/10 -- 04.09.2026

* Navazující implementační práce na mezeru zdokumentovanou výše
  (`DIAGNOSIS_DXCC_PREFIX_GAP.md`): nový, **obecný** (ne hard-coded pro
  `4L5O` ani žádný jiný konkrétní prefix/callsign) druhý krok, který se
  zavolá jen když offline `dxcc.py::PREFIX_TABLE` pro daný callsign nic
  nenajde.
* `station_agent/adapters/qrz.py` -- reálný HTTP klient na QRZ.com XML API
  (přihlášení username/password -> session key -> lookup callsignu),
  stejný vzor jako existující `pskreporter.py` (síťová vrstva oddělená od
  parserů, parsery testované na fixture XML v `tests/test_qrz_parsing.py`,
  síťová vrstva proti skutečnému lokálnímu HTTP serveru v
  `tests/test_qrz_live.py`, bez přístupu k internetu). `QRZClient.lookup()`
  nikdy nevyhazuje výjimku (síťová/auth chyba -> zaloguje se a vrátí
  `None`, stejná sémantika jako `callsign_to_dxcc`) a cachuje výsledky
  (i negativní) v paměti, aby opakované volání při každém obnovení
  kandidátů nezatěžovalo QRZ zbytečnými dotazy.
* `aggregator.attach_dxcc_and_bearing()` dostal nový volitelný parametr
  `dxcc_fallback` -- zavolá se jen když offline `callsign_to_dxcc()` vrátí
  `None`, nikdy nepřepisuje offline výsledek ani hodnotu dodanou zdrojem
  spotu (zachováno stávající "provider/offline má přednost" chování,
  regresně pokryto novými testy v `tests/test_aggregator.py`). Bez
  nakonfigurovaného fallbacku (`dxcc_fallback=None`, výchozí) je chování
  bit-přesně stejné jako dřív.
* `config.py::QRZConfig` (nová sekce `qrz:` v config.yaml/config.example.yaml)
  -- defaultně `enabled: false` (stejný princip jako ostatní živé zdroje,
  AGENTS.md pravidlo 4/6), vyžaduje explicitně vyplněné `username`/
  `password` vlastního QRZ.com XML Subscription účtu, jinak `load_config`
  selže srozumitelnou `ValueError` už při startu. `cli.py::build_app_state`
  fallback zapojí do `Aggregator` jen když je `qrz.enabled`.
* Live ověření proti skutečnému QRZ.com (reálné username/password) není v
  tomto sandboxu k dispozici -- žádné QRZ přihlašovací údaje nejsou
  nastavené. Síťová vrstva je proto ověřená stejným způsobem jako u
  živě funkčního PSKReporter adaptéru: skutečný HTTP GET přes loopback
  proti lokálnímu testovacímu serveru (real socket, ne mock v procesu),
  ne proti produkčnímu `xmldata.qrz.com`.
* Drobná doprovodná oprava GUI (`web/static/app.js`): `dxcc.continent` u
  QRZ fallback entit je `""` (QRZ kontinent přímo nevrací, radši prázdné
  než vymyšlené) -- zobrazení upraveno, aby v tom případě nepsalo prázdné
  závorky `Country ()`.
* Mimo rozsah beze změny: `dxcc.py::PREFIX_TABLE` samotná nebyla rozšířena
  o žádné nové prefixy (to by bylo přímé "hard-codování", zadání výslovně
  žádá obecný mechanismus) a žádný jiný adaptér/scoring/rig/log4om kód
  nebyl dotčen.

## Označení nedohledané stanice, i když selže i QRZ fallback -- iterace 1/10 -- 04.09.2026

* Samostatný navazující rozsah k sekci výše: ošetřit případ, kdy ani
  QRZ fallback zemi/DXCC neověřitelně nedohledá -- nic nevymýšlet a
  jasně zachovat/označit stanici jako nedohledanou ("?").
* Řetězec `dxcc.py::callsign_to_dxcc` -> volitelný `dxcc_fallback`
  (`aggregator.attach_dxcc_and_bearing`) už předtím korektně nechává
  `candidate.country`/`candidate.dxcc` na `None`, když oba kroky selžou
  (`tests/test_aggregator.py::DxccBearingTests::
  test_dxcc_fallback_none_result_keeps_country_missing`,
  `test_no_fallback_configured_preserves_existing_behaviour`) -- nic se
  nevymýšlí, beze změny.
* Skutečná mezera byla v zobrazení GUI stavu **naladěné** stanice
  (`web/static/app.js::renderRigStatus`), ne u seznamu kandidátů: řádek
  kandidáta už `?` zobrazoval korektně (`c.country || (c.dxcc &&
  c.dxcc.name) || "?"`, řádek 117), ale stavový řádek naladěné stanice
  při `rig.country` chybějícím (offline tabulka i QRZ fallback selhaly)
  celý segment země mlčky vynechal -- žádné "?", žádná indikace, že
  lookup proběhl a nedohledal se, což neodpovídá požadavku "jasně
  označit".
* Oprava: `country` segment se nyní zobrazí, kdykoli je `rig.callsign`
  známý (stanice je naladěná), s `rig.country || "?"` -- shodná logika
  jako u řádku kandidáta. Když `rig.callsign` chybí (rig zatím nemá
  naladěnou žádnou konkrétní DX stanici, např. čerstvě přečtený stav
  z hardwaru bez odpovídajícího kandidáta), segment země zůstává prázdný
  jako dřív -- tam by "?" bylo zavádějící (nejde o nedohledanou stanici,
  žádná stanice se nezobrazuje).
* Čistě prezentační JS oprava bez přidané logiky lookupu -- projekt nemá
  JS testový runner (`AGENTS.md` vyžaduje jen `python -m unittest
  discover`), stejný precedens jako doprovodná GUI oprava `dxcc.continent`
  v sekci výše. Python testová sada (`python -m pytest -q`) tímto
  nedotčena; spuštění provádí výhradně orchestrátor.
* Mimo rozsah beze změny: `dxcc.py`, `aggregator.py`, `adapters/qrz.py`,
  `autotune.py`/`models.py` (RigState.country zůstává pravdivě `None`,
  "?" je jen prezentační vrstva, stejně jako u kandidátů) nebyly dotčeny.

## Ochrana QRZ hesla proti náhodnému úniku přes repr/log -- iterace 2/10 -- 04.09.2026

* Doplňující zpevnění stejného rozsahu (ochrana credentials k QRZ.com):
  `config.py::QRZConfig` byla obyčejná `@dataclass` bez vlastního
  `__repr__` -- kdyby se instance (nebo obalující `Config`) někdy dostala
  do `repr()`/`str()`/logu/výjimky (např. budoucí debug výpis, traceback
  se zachyceným argumentem), vytisklo by se `qrz.password` v čistém textu.
  Aktuálně k tomu nikde v `cli.py`/`config.py` nedochází (ověřeno), ale
  jde o obecné latentní riziko přesně v rozsahu "ochrana credentials".
* Oprava: `QRZConfig.__repr__` je nyní explicitní a `password` maskuje na
  `"***"` (jen když je vyplněné, jinak `""`, aby prázdný `repr` nepředstíral
  nastavené heslo) -- `username`/ostatní pole zůstávají viditelná pro
  diagnostiku. `enabled`/přihlašovací validace v `__post_init__` beze
  změny.
* Regresní testy (`tests/test_config.py::QRZConfigSafetyTests`):
  `test_repr_never_exposes_plaintext_password` (heslo se nesmí objevit v
  `repr()`/`str()`), `test_repr_of_empty_password_does_not_claim_it_is_set`
  (prázdné heslo se nesmí maskovat na `"***"`, aby log neklamal, že je
  vyplněné).
* Mimo rozsah beze změny: `adapters/qrz.py` (síťová vrstva/cache/backoff
  z iterace 1/10 nedotčena), `aggregator.py`, `cli.py`, žádný jiný
  konfigurační dataclass.

## Ověření funkčnosti u 4L5O a obecnosti QRZ fallbacku -- iterace 1/10 -- 04.09.2026

* Nové zadání (samostatný rozsah): "ověřit funkčnost na stanici 4L5O a
  případně dalších stanicích s '?' z dnešního živého běhu, potvrdit
  obecnost řešení mimo hard-coded případ. Zachovat chování mimo tento
  rozsah."
* Nejdřív ověřeno, že řešení mezery zdokumentované v
  `DIAGNOSIS_DXCC_PREFIX_GAP.md` už existuje a je hotové z předchozích
  iterací (`adapters/qrz.py` + `aggregator.attach_dxcc_and_bearing`
  `dxcc_fallback` + `cli.py`/`config.py` `qrz:` sekce, viz README "Stav
  externích zdrojů"). Zvažoval jsem doplnit chybějící prefixy (`4L`,
  `E7`, `EK`, `JE`/`JR`, `M0`, `R`, ...) přímo do
  `dxcc.py::PREFIX_TABLE`, ale to by bylo přesně to hard-codování, které
  předchozí iterace ("Obecný QRZ.com fallback pro DXCC/zemi") výslovně
  zamítla ve prospěch obecného síťového mechanismu -- takový pokus jsem
  vrátil zpět (`git checkout`/ruční revert), aby zůstalo zachováno
  chování mimo tento rozsah.
* Existující testy (`tests/test_qrz_live.py`,
  `tests/test_aggregator.py::test_dxcc_fallback_used_when_prefix_table_misses`)
  už ověřovaly `4L5O` end-to-end (parser, session/cache, HTTP klient přes
  skutečný lokální socket, i celý `attach_dxcc_and_bearing` pipeline), ale
  všechny úspěšné příklady používaly výhradně stejný jeden callsign
  `4L5O` -- obecnost mechanismu (že nejde o skrytou speciální větev jen
  pro tento jeden příklad ze zadání) tak nebyla přímo dokázána druhým,
  odlišným příkladem.
* Doplněny regresní testy s druhou, zcela odlišnou stanicí/zemí
  (`JE3GUG`/Japan -- další živě přijatá "?" stanice z dnešního běhu
  2026-09-04 podle `DIAGNOSIS_DXCC_PREFIX_GAP.md`, prefix `JE` v offline
  `PREFIX_TABLE` chybí i když `JA` už tam je) přes celý zásobník:
  `tests/test_qrz_parsing.py::test_parses_different_callsign_and_country_generically`,
  `tests/test_qrz_live.py::test_client_lookup_end_to_end_for_different_station_is_not_hard_coded`
  (reálný lokální HTTP socket), `tests/test_aggregator.py::test_dxcc_fallback_used_for_other_station_not_just_the_dod_example`.
  Ručně ověřeno (mimo pytest, který spouští výhradně orchestrátor) přímým
  voláním produkčního kódu proti lokálnímu HTTP serveru: `4L5O -> Georgia`
  i `JE3GUG -> Japan` oba projdou stejným, nezměněným `QRZClient`/
  `attach_dxcc_and_bearing` kódem.
* Mimo rozsah beze změny: `station_agent/dxcc.py::PREFIX_TABLE` zůstává
  záměrně neúplná (offline rychlá tabulka), `adapters/qrz.py` a
  `aggregator.py` nebyly touto iterací nijak upraveny -- jen doplněny
  testy dokazující už existující obecnost. Produkční live ověření proti
  skutečnému `xmldata.qrz.com` s reálnými přihlašovacími údaji zůstává
  mimo možnosti tohoto sandboxu (žádné QRZ.com přihlašovací údaje nejsou
  nastavené v `config.yaml`), stejně jako zdokumentováno u předchozí
  QRZ iterace.
