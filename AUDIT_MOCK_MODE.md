# Audit mock režimu — Station Agent

Cíl: projít aktuální konfiguraci a kód a identifikovat **všechna** místa, kde
Station Agent aktuálně běží v mock režimu místo reálného. Read-only audit —
neprovádí žádnou funkční změnu chování (viz AGENTS.md pravidlo 4: přechod na
`live` je vždy explicitní volba uživatele v jeho vlastním `config.yaml`,
nikdy automatický zásah kódu).

## Metoda

- Statická kontrola `station_agent/` (adaptéry spotů, rig, propagation,
  Log4OM2, web) proti tomu, co je zdokumentováno v README "Stav externích
  zdrojů" a v `AGENTS.md`.
- Kontrola skutečného `config.yaml` v pracovním adresáři (gitignored, mimo
  `config.example.yaml`) — tj. jak je Station Agent nakonfigurovaný k běhu
  teď, ne jen jak vypadá distribuovaný příklad.
- Grep na `mock`/`Mock`/`MOCK`, `pending`, `NotImplementedError`, `TODO`,
  `FIXME`, `stub` napříč `station_agent/`.

## Nálezy — místa běžící v mock režimu

### 1. `rig.mode: mock` (aktivní v `config.yaml`)

- `station_agent/config.py::RigConfig.mode` default `"mock"`.
- `station_agent/rig/__init__.py::create_rig_control` vrací `MockRig`
  (`station_agent/rig/mock_rig.py`) — in-memory rig bez jakéhokoli
  reálného spojení.
- Skutečný `config.yaml` v repozitáři má `rig.mode: mock` a placeholder
  `station.callsign: "OK1EXAMPLE"` / `qth_locator: "JN79FG"` — tedy
  Station Agent teď při spuštění reálně běží s mock riggem, ne s IC-7300.
- Reálná alternativa existuje a je plně implementovaná:
  `station_agent/rig/rigctld.py::RigctldClient` (skutečný TCP klient na
  Hamlib `rigctld`, čtení/nastavení frekvence a módu, otestováno proti
  fake TCP serveru v `tests/test_rig_rigctld.py`). Přepnutí je jen změna
  `rig.mode: live` + `rigctld_host`/`rigctld_port` v `config.yaml`.
- Stav: **záměrný, bezpečný default** (AGENTS.md pravidlo 4). Není to bug.

### 2. `sources.mock.enabled: true` a všechny živé spotové zdroje vypnuté

- `station_agent/__main__.py::build_sources` přidává `MockAdapter`
  (`station_agent/adapters/mock.py`, statická demo sada 8 spotů) vždy,
  když `sources.mock` chybí nebo je `enabled: true`.
- Skutečný `config.yaml` má `sources.mock.enabled: true` a všechny živé
  zdroje (`dx_cluster`, `dx_cluster_hamserve`, `dx_cluster_ea7jxh`,
  `dx_cluster_m0mhx`, `rbn`, `pskreporter`) `enabled: false` — Station
  Agent tedy teď reálně vidí jen 8 vymyšlených demo spotů, žádná živá
  data z DX clusteru/RBN/PSKReporteru.
- Reálné alternativy existují a jsou plně implementované a živě ověřené
  (viz README "Stav externích zdrojů" a `LIVE_EVIDENCE.md`):
  `DXClusterAdapter`/`RBNAdapter` nad `LiveTelnetSpotSource`
  (`station_agent/adapters/telnet_source.py`, skutečný TCP socket, login
  callsignem, reconnect/backoff) a `PSKReporterAdapter`
  (`station_agent/adapters/pskreporter.py`, skutečné HTTP GET + XML parse).
  Přepnutí je jen `enabled: true` + reálný callsign u požadovaných zdrojů
  v `config.yaml`.
- Stav: **záměrný, bezpečný default** (příklad i distribuovaný config
  nesmí bez výslovné volby uživatele vytvářet síťová spojení pod cizí
  identitou). Není to bug.

### 3. `log4om.enabled: false` (a i po zapnutí: nezávislé UPOZORNĚNÍ "pending verifikace")

- `station_agent/log4om.py::send_prefill` reálně odesílá UDP paket
  (`socket.socket(..., SOCK_DGRAM).sendto`), sestavení payloadu je plně
  testované (`tests/test_log4om.py`) proti lokálnímu UDP listeneru.
- Skutečný `config.yaml` má `log4om.enabled: false` — funkce je tedy teď
  vypnutá, ne mock: kód není nahrazen fingovanou implementací, jen se
  nevolá.
- I po zapnutí zůstává modul zdokumentovaný jako "pending verifikace proti
  běžící instanci Log4OM2" (README, docstring modulu) — payload/formát
  nebyl nikdy ověřen proti reálnému Log4OM2, protože ten není v tomto
  prostředí k dispozici. Toto je jediné místo v kódu, kde reálná
  implementace existuje, ale její chování proti opravdové cílové službě
  zůstává neověřené (na rozdíl od DX Cluster/RBN/PSKReporter/rigctld, které
  už mají živé ověření zaznamenané v `LIVE_EVIDENCE.md`).
- Stav: **záměrný default vypnuto + čestně označené pending u samotné
  verifikace**, v souladu s AGENTS.md pravidlem 6. Není to bug.

## Místa, kde mock **není** přítomen (ověřeno, aby nechyběla v přehledu)

- `station_agent/propagation.py` — Kp/SFI se natvrdo stahují z reálného
  NOAA SWPC (`urllib.request`), žádný fallback na vymyšlená čísla; při
  chybě sítě se jen podrží poslední platná evidence nebo zůstane `None`.
  `propagation.enabled: true` je v `config.yaml` skutečně zapnuté.
- `station_agent/scoring.py` — `_propagation_reason`/`band_activity`
  používají buď reálný `PropagationContext`, nebo reálnou aktivitu spotů
  jako fallback; nikde není vymyšlená hodnota.
- `station_agent/rig/base.py`, `station_agent/adapters/base.py` —
  `NotImplementedError`/`PendingSpotSource` jsou explicitně označené
  "zatím neověřeno", ne tichý mock výstup (AGENTS.md pravidlo 6 dodržen).
- `station_agent/web/server.py`, `station_agent/app_state.py` — žádný
  výskyt mock logiky; pracují jen s tím, co jim předá `Aggregator`/`rig`
  podle skutečné konfigurace.

## Shrnutí

Station Agent aktuálně (podle skutečného `config.yaml` v pracovním
adresáři, ne jen příkladu) běží **kompletně v mock režimu**: mock rig,
mock zdroj spotů, žádný živý DX Cluster/RBN/PSKReporter, Log4OM2 vypnuto.
To je záměrný, bezpečný stav pro vývoj/testy (AGENTS.md pravidlo 4) — kód
pro plně živý provoz je hotový a zdokumentovaný, jen čeká na explicitní
volbu uživatele (reálný callsign, `rig.mode: live`, zapnutí požadovaných
`sources.*`). Audit nenašel žádné místo, kde by kód tvrdil, že běží živě,
zatímco ve skutečnosti vrací vymyšlená data — to by bylo porušení
AGENTS.md pravidla 6 a v kódu k tomu nedošlo.

Jediná položka vyžadující pozornost uživatele, pokud bude chtít přejít na
reálný provoz: v `config.yaml` je stále placeholder `station.callsign:
"OK1EXAMPLE"` a `qth_locator: "JN79FG"` místo skutečných údajů stanice
(viz `PROJECT_NOTES.md`: OK1RPL, JN69QR) — to je ovšem vlastní data
uživatele v jeho gitignored konfiguraci, mimo rozsah tohoto auditu kódu.
