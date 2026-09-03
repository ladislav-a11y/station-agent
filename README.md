# Station Agent

Radioamatérský DX asistent pro **IC-7300**. Agreguje spoty z DX clusteru,
Reverse Beacon Network (RBN), PSKReporteru a dalších budoucích zdrojů,
spočítá transparentní skóre 0–100 pro každého kandidáta, spočítá směr
(bearing) z tvého QTH a volitelně (v režimu AUTO TUNE) přeladí IC-7300 přes
Hamlib/`rigctld` na nejlepší stanici. Nikdy nezasahuje do PTT/vysílání a
nikdy neovládá anténní rotátor — pouze zobrazuje vypočtený bearing.

## Bezpečnostní invarianty (nejde je vypnout konfigurací)

- **Žádné PTT.** V celém zdrojovém stromu `station_agent/` se nikde
  nevyskytuje kód, který by uměl zapnout vysílání. Ověřuje to
  `tests/test_rig_safety.py` (grep na `ptt` case-insensitive + kontrola, že
  žádná třída rigu nemá metodu spojenou s vysíláním).
- **Žádné ovládání anténního rotátoru.** Existuje pouze výpočet bearing (viz
  `station_agent/bearing.py`) pro zobrazení v GUI. Žádný modul anténu
  fyzicky nenatáčí.
- **Log4OM2 se jen předvyplňuje.** `station_agent/log4om.py` umí sestavit a
  poslat "prefill" packet, ale nikde neexistuje funkce, která by QSO
  automaticky uložila do deníku.
- **Hamlib je defaultně v mock režimu.** `rig.mode: mock` v konfiguraci je
  výchozí. Přechod na `live` je explicitní volba uživatele.
- **Web GUI běží jen na localhost.** HTTP server se váže výhradně na
  `127.0.0.1` (viz `station_agent/web/server.py`), adresa je i tvrdě
  ošetřená v kódu (nelze nakonfigurovat na `0.0.0.0`).

## Instalace

Žádné povinné závislosti — stačí Python 3.10+.

```bash
python -m venv .venv
# volitelně: pip install -r requirements.txt   (PyYAML/pytest, nepovinné)
cp config.example.yaml config.yaml
python -m station_agent --config config.yaml
```

GUI pak najdeš na `http://127.0.0.1:8765` (port dle configu).

`config.yaml` je v `.gitignore` a musí ho mít každý checkout vlastní. Pokud
krok `cp config.example.yaml config.yaml` vynecháš, nebo bude výsledný
`config.yaml` obsahovat neplatný zápis či hodnotu mimo povolený rozsah
(např. `rig.mode` jiné než `mock`/`live`), Station Agent to teď nahlásí
čitelnou chybou (v druhém případě s popisem, co přesně v configu nesedí) a
skončí s nenulovým návratovým kódem (`station_agent/config.py::load_config`,
`station_agent/cli.py::main`) — ne nezachyceným Python tracebackem.

## Instalace a spuštění na Windows 11 (krok za krokem)

1. **Nainstaluj Python 3.10+.** Stáhni z
   [python.org/downloads](https://www.python.org/downloads/) a při instalaci
   zaškrtni "Add python.exe to PATH". Ověř v PowerShellu:
   ```powershell
   python --version
   ```
2. **Stáhni/naklonuj projekt** a otevři PowerShell ve složce projektu, např.:
   ```powershell
   cd D:\station-agent
   ```
3. **(Volitelné) vytvoř virtuální prostředí** — doporučeno, ať se závislosti
   neinstalují do systémového Pythonu:
   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```
   Pokud PowerShell odmítne spustit skript kvůli execution policy, spusť
   jednorázově (jen pro aktuální relaci):
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```
4. **(Volitelné) nainstaluj volitelné závislosti** (PyYAML pro plný YAML
   syntax, pytest pro testy). Bez tohoto kroku aplikace i testy fungují —
   config.py má vestavěný minimální YAML parser:
   ```powershell
   pip install -r requirements.txt
   ```
5. **Vytvoř vlastní konfiguraci** zkopírováním příkladu a uprav callsign,
   QTH (locator nebo lat/lon) a případně `rigctld` host/port:
   ```powershell
   copy config.example.yaml config.yaml
   notepad config.yaml
   ```
6. **Spusť aplikaci** (mock režim, bez rádia a bez internetu — funguje hned):
   ```powershell
   python -m station_agent --config config.yaml
   ```
7. **Otevři GUI** v prohlížeči na `http://127.0.0.1:8765` (nebo jiný port,
   pokud jsi ho v configu změnil).
8. **Zastavení**: `Ctrl+C` v okně PowerShellu, kde aplikace běží.

Pro reálný provoz s IC-7300 a Log4OM2 pokračuj sekcemi níže — nejdřív
nastav a ověř `rigctld` (Hamlib), teprve pak v `config.yaml` přepni
`rig.mode: live`.

## Zapojení IC-7300 přes Hamlib/`rigctld`

Station Agent se k rádiu **nikdy** nepřipojuje přímo přes sériový/COM port
— vždy jen jako TCP klient k `rigctld` (Hamlib) na `localhost`/loopback
nebo jiné nakonfigurované adrese v tvé síti. Žádné PTT/vysílání se
neposílá — Station Agent umí jen číst a nastavovat frekvenci a mód.

1. **Nainstaluj Hamlib** (obsahuje `rigctld.exe`):
   - Stáhni Windows build z [Hamlib releases na
     GitHubu](https://github.com/Hamlib/Hamlib/releases) (soubor typu
     `hamlib-w64-<verze>.zip` nebo instalátor) a rozbal/nainstaluj, např. do
     `C:\Hamlib`.
   - Alternativně bývá Hamlib součástí instalace WSJT-X/JTDX/N1MM — pokud
     už jeden z těchto programů máš, `rigctld.exe` může být už na disku
     (hledej v jejich instalační složce).
2. **Připoj IC-7300 k PC** přes USB (virtuální COM port ovladače Icom —
   nainstaluj ovladač Icom USB Driver, pokud ho Windows nenajde samo) a
   zjisti číslo COM portu ve Správci zařízení (Device Manager → Ports
   (COM & LPT)), např. `COM5`.
3. **Nastav na IC-7300** v menu rádia CI-V (Set → Connectors → CI-V):
   - CI-V Baud Rate: shoduj se s tím, co použiješ v `rigctld` (např. 19200).
   - CI-V Transceive: zapnuto.
   - CI-V USB Port: pokud připojuješ přes USB, nech "Unlink from [REMOTE]"
     dle potřeby (viz manuál IC-7300, kapitola CI-V/USB).
4. **Spusť `rigctld`** pro IC-7300 (Hamlib model číslo IC-7300 je `3073`) v
   PowerShellu/cmd:
   ```powershell
   C:\Hamlib\bin\rigctld.exe -m 3073 -r COM5 -s 19200 -t 4532
   ```
   - `-m 3073` — model IC-7300
   - `-r COM5` — COM port, na kterém rádio vidíš (uprav dle kroku 2)
   - `-s 19200` — CI-V baud rate (musí sedět s nastavením v rádiu)
   - `-t 4532` — TCP port, na kterém `rigctld` naslouchá (výchozí Hamlib
     port, odpovídá `rig.rigctld_port` v `config.yaml`)
   - `rigctld` naslouchá defaultně na `127.0.0.1` (loopback) — pokud
     potřebuješ přístup z jiného stroje v síti, přidej `-T 0.0.0.0`, ale
     ponech `config.yaml` → `rig.rigctld_host` nastavený na skutečnou IP.
5. **Ověř spojení** ještě předtím, než spustíš Station Agent — Hamlib má k
   tomu `rigctl` (textový test klient):
   ```powershell
   C:\Hamlib\bin\rigctl.exe -m 2 -r 127.0.0.1:4532 f
   ```
   (`-m 2` = "rigctld network" model, tj. připoj se na běžící `rigctld`
   jako klient). Příkaz by měl vrátit aktuální frekvenci v Hz. Pokud vrátí
   chybu spojení, zkontroluj, že `rigctld` z kroku 4 opravdu běží a že
   COM port/baud rate sedí.
6. **V `config.yaml` nastav**:
   ```yaml
   rig:
     mode: live          # explicitní volba, výchozí je "mock"
     rigctld_host: "127.0.0.1"
     rigctld_port: 4532
     model: "IC-7300"
   ```
7. **Spusť Station Agent** (`python -m station_agent --config config.yaml`)
   — v GUI by se měla objevit aktuální frekvence/mód přečtená z rádia
   (`rig-status` v hlavičce). AUTO TUNE (pokud ho zapneš) bude přes
   `rigctld` měnit jen frekvenci a mód, nikdy nic jiného.

## Propojení s Log4OM2 (UDP prefill)

Station Agent umí do Log4OM2 poslat UDP "prefill" packet, který **jen
předvyplní** rozpracovaný řádek QSO v deníku — nikdy žádné QSO neuloží ani
nepotvrdí automaticky, to musí vždy udělat operátor ručně v Log4OM2.

1. V Log4OM2 najdi nastavení pro příjem externích "spot"/"click to tune"
   UDP paketů (Log4OM2 → Nastavení/Tools → Externí aplikace / Radio
   Control / Broadcast — přesné umístění se liší dle verze Log4OM2) a
   zjisti/nastav UDP port, na kterém Log4OM2 naslouchá (výchozí bývá
   `2333`, ale zkontroluj si to ve svém Log4OM2).
2. V `config.yaml` nastav stejný host/port a zapni integraci:
   ```yaml
   log4om:
     enabled: true
     host: "127.0.0.1"   # Log4OM2 typicky běží na stejném PC
     port: 2333            # musí odpovídat portu nastavenému v Log4OM2
   ```
3. Spusť Log4OM2 i Station Agent současně. Formát a doručení UDP packetu
   (`station_agent/log4om.py`) je implementované a otestované proti
   lokálnímu UDP listeneru (`tests/test_log4om.py`), ale **nebylo ověřeno
   proti běžící instanci Log4OM2** — než integraci zapneš naostro, ověř,
   že se řádek v Log4OM2 skutečně předvyplní podle svého nastavení
   naslouchání. Pokud se nic nestane, zkontroluj shodu portu a to, že
   Log4OM2 má zapnutý příjem externích spot packetů.
4. Prefill nikdy neukládá QSO — v Log4OM2 vždy potvrď/ulož záznam ručně.

## Spuštění testů

```bash
python -m unittest discover -s tests -v
# nebo, pokud je nainstalovaný pytest:
pytest
```

Všechny testy běží **bez internetu a bez připojeného rádia** — používají
mock adaptér spotů (`station_agent/adapters/mock.py`) a mock rig
(`station_agent/rig/mock_rig.py`).

## Architektura

Viz [ARCHITECTURE.md](ARCHITECTURE.md) pro rozpis modulů a datový tok, a
[AGENTS.md](AGENTS.md) pro pravidla vývoje/rozšiřování projektu (zejména
bezpečnostní invarianty, které se nesmí porušit).

## Stav externích zdrojů (adaptérů)

| Adaptér | Parsování / logika | Živé připojení |
|---|---|---|
| Mock (offline testovací data) | ✅ funkční | — |
| DX Cluster (telnet) | ✅ parser řádků otestovaný na fixture datech | ✅ **živě funkční** — `LiveTelnetSpotSource` (`station_agent/adapters/telnet_source.py`) otevře reálný TCP socket, přihlásí se callsignem a streamuje/parsuje řádky s vlastním reconnect/backoffem; při startu respektuje tříminutovou grace period |
| DX Cluster — W3LPL | ✅ stejný produkční parser | ✅ `dxc.w3lpl.net:7373`, výchozí pojmenovaný zdroj `dx_cluster` |
| DX Cluster — Hamserve | ✅ stejný produkční parser | ✅ živě ověřeno `dxc.hamserve.uk:7300`, zdroj `dx_cluster_hamserve`, včetně SSB spotu |
| DX Cluster — EA7JXH | ✅ stejný produkční parser | ✅ živě ověřeno `dx.ea7jxh.eu:7300`, zdroj `dx_cluster_ea7jxh`, včetně SSB spotů |
| DX Cluster — M0MHX | ✅ stejný produkční parser | ✅ živě ověřeno `dxc.m0mhx.uk:7300`, zdroj `dx_cluster_m0mhx`, včetně SSB spotu |
| Reverse Beacon Network | ✅ parser řádků otestovaný na fixture datech | ✅ **živě funkční** — stejný `LiveTelnetSpotSource` klient jako DX Cluster výše, mířený na `telnet.reversebeacon.net:7000` |
| PSKReporter | ✅ parser XML reportu otestovaný na fixture datech | ✅ **živě funkční** — `fetch()` reálně provádí HTTP GET na `query_url` (výchozí `retrieve.pskreporter.info/query`) a parsuje odpověď; síťová vrstva je otestovaná proti skutečnému lokálnímu HTTP serveru v `tests/test_adapters_live.py` |
| Log4OM2 UDP prefill | ✅ sestavení payloadu otestované | ⏳ **pending verifikace** — odeslání UDP paketu je implementované, ale nebylo ověřeno proti běžící instanci Log4OM2 |

DX Cluster a RBN běží na sdíleném telnet klientovi (`station_agent/adapters/telnet_source.py`):
vlastní daemon vlákno na zdroj, skutečný TCP socket, login callsignem
(`station.callsign` z configu, nebo přepsatelné přes `sources.<zdroj>.callsign`),
čtení řádek po řádku a nezávislý reconnect s exponenciálním backoffem --
výpadek jednoho zdroje neovlivní ostatní. DX Cluster a RBN mají po prvním
spuštění tříminutovou grace period: během ní se jejich připojení rozbíhá a
stav "ok" se ještě neočekává. Po jejím uplynutí je aktivní přihlášené telnet
spojení "ok" i v okamžiku, kdy zrovna nepřišel žádný spot; nedostupné spojení
je "error". Po prvních reálných datech se další výpadky hlásí jako "error",
nikdy zpátky "pending". Žádný adaptér nevrací
vymyšlená/nafingovaná data tvářící se jako reálná odpověď (viz AGENTS.md
pravidlo 6). V příkladové konfiguraci jsou všechny síťové zdroje záměrně
`enabled: false`: uživatel si musí zvolit vlastní callsign a výslovně zapnout
jen požadované endpointy; příklad tak po spuštění bez úprav nevytváří žádná
externí síťová spojení.

DX Cluster uzlů lze nakonfigurovat libovolný počet. První se obvykle jmenuje
`sources.dx_cluster`, další musí mít jedinečné jméno začínající
`dx_cluster_` (např. `dx_cluster_hamserve`). Každý uzel má vlastní připojení,
frontu, reconnect a stav v `/api/status`; jeho konfigurační jméno se také
zachová v `confirming_sources`, takže potvrzení od více uzlů zůstávají
samostatnou evidencí.

Distribuovaný příklad nabízí vedle původního `dxc.w3lpl.net:7373` tři
defaultně vypnuté full-feed alternativy vhodné i pro SSB spoty:
`dxc.hamserve.uk:7300`, `dx.ea7jxh.eu:7300` a `dxc.m0mhx.uk:7300`.
Endpoint Hamserve a přihlášení callsignem dokumentuje přímo
[DXSpider wiki](https://wiki.dxcluster.org/wiki/How_to_connect), EA7JXH svůj
telnet endpoint uvádí na [webu clusteru](https://www.ea7jxh.eu/) a M0MHX
publikuje telnet endpoint přímo na
[webovém clusteru](https://dxc.m0mhx.uk/). Nejde o
automaticky zapnutý failover: operátor může zapnout jeden nebo více uzlů
podle polohy a každý zůstane samostatným zdrojem.

Frekvence GUI refreshe (viz `web/static/app.js`, každých 5 s) je záměrně
oddělená od frekvence reálných dotazů na živé zdroje jako PSKReporter --
`Aggregator`/`PolledSource` (`station_agent/adapters/polling.py`) na síť
sáhne nejvýš jednou za `polling.source_interval_seconds` z configu
(výchozí 60 s), mezitím vrací naposledy úspěšně stažená data. Při HTTP 429
(Too Many Requests) se zdroj přepne do backoffu -- respektuje `Retry-After`
hlavičku, jinak čeká exponenciálně rostoucí interval -- a stav/poslední
chybu každého zdroje lze zjistit v `/api/status` (`sources`).

## Konfigurace

Viz [config.example.yaml](config.example.yaml) — obsahuje QTH (locator nebo
lat/lon), `rigctld` host/port, povolená pásma a módy, minimální skóre,
AUTO TUNE, HOLD, minimální dobu držení, požadovaný rozdíl skóre a (pending)
Log4OM2 endpoint.

## Historie QSO, předvolby a notifikace

GUI nabízí konfigurovatelné předvolby filtrů módů/pásem. Vybrané nastavení
se lokálně ukládá do SQLite databáze a při dalším spuštění se automaticky
obnoví. Vybraného kandidáta lze explicitním tlačítkem zapsat do lokální SQLite historie QSO
včetně frekvence, módu, pásma a vypočteného bearingu. Tento krok nikdy
nepotvrzuje ani neukládá záznam v Log4OM2.

Band-opening notifikace vznikají při překročení konfigurovaného počtu
odlišných stanic na pásmu. Od spuštění procesu se pro každé pásmo měří kladný
přírůstek proti předchozímu cyklu a GUI drží pouze jedinou notifikaci s dosud
největším přírůstkem. Historie QSO je viditelná přímo v GUI.

## Propagation a debug skóre

Při zapnuté sekci `propagation` se nejvýše jednou za hodinu načtou aktuální
Kp a SFI z NOAA SWPC. Station Agent z nich, QTH lokátoru a lokálního
slunečního času autonomně vytvoří transparentní výhled 0–1 pro každé
podporované pásmo. Scoring síť nevolá; spotřebuje pouze tento hodinový
snapshot. Aktuální Kp zůstává v pravém horním rohu GUI. Spuštění s
`--verbose` vypíše při každém obnovení kandidátů celý propagation snapshot
i všechny `ScoreReason` faktory každého kandidáta do terminálu/PowerShellu.
