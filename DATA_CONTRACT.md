# Datový kontrakt a zdroje evidence

Tento dokument je závazný popis toho, co která vrstva datového modelu smí
a nesmí obsahovat, a odkud přesně (z jaké evidence) se každé pole bere.
Cíl: žádné pole v GUI se nikdy nevyplní vymyšlenou/nafingovanou hodnotou --
buď existuje reálná evidence, nebo je pole `None`/prázdné a GUI to musí
zobrazit jako "neznámé", ne jako věrohodně vyhlížející číslo (viz AGENTS.md
pravidlo 6 "Nefalšuj externí služby").

Mechanicky je kontrakt vynucen testy v `tests/test_data_contract.py`.

## 1. `Spot` (station_agent/models.py) -- jedno pozorování z jednoho zdroje

| Pole | Typ | Zdroj pravdy | Poznámka |
|---|---|---|---|
| `callsign` | `str` | adaptér | normalizuje se v `__post_init__` (strip + upper) |
| `freq_hz` | `int` | adaptér | v Hz; u digitálních módů se kanonizuje na dial-frekvenci (`bandplan.canonical_digital_dial_frequency`) |
| `mode` | `str` | adaptér | normalizuje se přes `modes.normalize_mode()` na jednu z `SUPPORTED_MODES` |
| `timestamp` | `float` | adaptér | unix epoch sekundy UTC -- musí to být čas, kdy zdroj spot ohlásil, ne čas parsování; na tom stojí časové okno slučování v `aggregator._cluster_by_freq_and_time` |
| `source` | `str` | adaptér | MUSÍ se rovnat `self.name` adaptéru, který spot vytvořil (`mock`, pojmenovaný `dx_cluster*`, `rbn`, `pskreporter`) -- to je jediný identifikátor evidence použitý ve `confirming_sources` |
| `snr_db` | `float \| None` | adaptér | `None` = zdroj SNR nehlásí; nikdy se nedopočítává ani neodhaduje |
| `spotter` | `str` | adaptér | volající/skimmer/přijímač, který stanici ohlásil; `""` když to zdroj nerozlišuje |
| `band` | `str` | odvozeno | pokud adaptér nevyplní, dopočítá se z `freq_hz` přes `bandplan.freq_to_band` |
| `comment` | `str` | adaptér | volný text ze zdroje, `""` pokud žádný není |
| `country` | `str \| None` | adaptér | země uvedená zdrojem; chybějící se doplní až u kandidáta podle prefixu |
| `locator` | `str \| None` | adaptér | Maidenhead lokátor konkrétní stanice, pokud jej zdroj poskytuje |
| `bearing_deg`, `distance_km` | `float \| None` | adaptér | přímá evidence ze zdroje; jinak se dopočítá u kandidáta |

## 2. `Candidate` (station_agent/models.py) -- sloučený pohled napříč zdroji

Vzniká v `aggregator.group_spots_into_candidates()` sloučením `Spot` se
stejným callsign + band + kompatibilním módem + přibližnou frekvencí +
časovým oknem (viz `aggregator.py` hlavičkové komentáře).

| Pole | Odvozeno z | Poznámka |
|---|---|---|
| `confirming_sources` | `{s.source for s in cluster}` | přímá evidence, nikdy odhad |
| `spotters` | `{s.spotter for s in cluster if s.spotter}` | množina nezávislých pozorovatelů -- vstup pro `_reliability_reason` |
| `best_snr_db` | `max()` z nenulových `snr_db` v clusteru | `None`, pokud žádný spot SNR nehlásí |
| `dxcc` | `dxcc_lookup(callsign)` v `aggregator.attach_dxcc_and_bearing()`, produkčně `country_lookup.CountryLookup.lookup` | jediný řetězec zdrojů, každý krok se zkusí jen když ten předchozí vrátí `None`: (1) read-only Log4OM2 country databáze (`ctyfile.json`/`country.xml`, pokud je na disku nalezená -- viz `country_lookup._country_file_candidates()`), (2) volitelný `pyhamtools` country-file backend, (3) vestavěná offline `dxcc.PREFIX_TABLE`, (4) volitelný síťový `network_fallback` (typicky `adapters/qrz.py::QRZClient.lookup`, zapojen jen když `qrz.enabled`), viz README "DXCC/země fallback přes QRZ.com". Žádný krok nevrací nic mimo tento řetězec ani nedopočítává hodnotu -- neúspěch celého řetězce zůstává `None` ("?" v GUI) |
| `country` | nejnovější neprázdná hodnota ze spotů, jinak DXCC dle prefixu | dodanou zemi nepřepisuje odhad |
| `locator` | nejnovější neprázdná hodnota ze spotů | původní hodnota se zachová i tehdy, když ji Maidenhead převodník odmítne; jde o evidenci zdroje, ne o konfigurované QTH |
| `bearing_deg`, `distance_km` | přímá evidence ze spotu, jinak `bearing.bearing_and_distance()` z QTH + platného lokátoru stanice; při odmítnutí lokátoru z bodu DXCC entity | Odmítnutý lokátor se nepoužije jako souřadnice a vyvolá vysvětlující varování; `None`, pokud chybí QTH nebo použitelný cíl -- nikdy se nedosazuje placeholder |
| `score` | `scoring.score_candidate()` | viz sekce 3 |

## 3. Scoring (station_agent/scoring.py) -- transparentní 0-100

`score_candidate()` vrací `ScoreResult(total, reasons)`, kde `reasons`
obsahuje **přesně jeden `ScoreReason` na každý klíč** v
`config.DEFAULT_SCORING_WEIGHTS` (jediný zdroj pravdy pro výchozí váhy,
`scoring.DEFAULT_WEIGHTS` je jen re-export). Váhy musí dát dohromady 100.

| Faktor | Evidence | Chování při chybějícím kontextu |
|---|---|---|
| `freshness` | `now - candidate.last_seen` vs `spot_max_age_minutes` | vždy dostupné |
| `sources` | počet `confirming_sources` | vždy dostupné |
| `needed_dxcc` | `db.is_worked(dxcc.name)` | neznámá DXCC entita -> považuje se za potřebnou (raději upozornit) |
| `signal` | `best_snr_db` | chybí -> neutrálních 50 % váhy |
| `reliability` | počet `spotters` | žádný spotter -> neutrálních 50 % váhy |
| `propagation` | hodinový `PropagationContext.band_quality` připravený z aktuálního NOAA Kp/SFI, QTH lokátoru a lokálního slunečního času; scoring sám síť nikdy nevolá. Po chybě zdroje se starý snapshot zahodí a stav API je `verified=false`, aby se žádná hodnota nevydávala za ověřenou. Při nedostupném snapshotu slouží jako fallback `aggregator.band_activity` | chybí snapshot i `band_activity` -> neutrálních 50 % váhy |
| `path_dx` | `candidate.distance_km` | chybí (QTH nenakonfigurováno) -> neutrálních 50 % váhy |

Chybějící evidence tedy nikdy nepenalizuje kandidáta pod neutrální
polovinu dané váhy -- viz `tests/test_scoring.py` (`test_*_gives_neutral_*`)
a `tests/test_mode_aware_fusion.py`.

## 4. Zdroje evidence (adaptéry) -- živé vs. pending

Viz README.md "Stav externích zdrojů" pro plnou tabulku. Shrnutí kontraktu:

- **mock** -- offline demo data, nikdy se netváří jako živá evidence (v GUI
  vždy viditelně "mock" ve `confirming_sources`).
- **dx_cluster***, **rbn** -- `LiveTelnetSpotSource` (`adapters/telnet_source.py`);
  každý pojmenovaný DX Cluster uzel zachovává vlastní identitu zdroje,
  reálný TCP telnet socket; dokud se spojení skutečně nenaváže, `fetch()`
  hlásí `SourceNotReadyError` (GUI stav "pending"). Jakmile je spojení
  navázané a login odeslaný, přechází rovnou na "ok" i bez právě přijatého
  spotu -- nikdy nevrací vymyšlená data.
- **pskreporter** -- reálný HTTP GET (`adapters/pskreporter.py`), stejné
  pravidlo: síťová chyba/rate-limit se propaguje jako výjimka, ne jako
  tichý prázdný/nafingovaný výsledek.
- Parsovací vrstva (`parse_spot_line`, `parse_rbn_line`,
  `parse_pskreporter_report`) je u všech tří oddělená od síťové vrstvy a
  100% testovaná na fixture datech (`tests/test_adapters_parsing.py`).

## 5. Co GUI smí zobrazit

`web/serialization.candidate_to_dict()` je jediné místo, které převádí
`Candidate` na JSON pro GUI -- žádné jiné pole se nesmí dopočítávat na
frontendu. Pole musí odpovídat DoD sekci "Skóre a zobrazované údaje":
`callsign`, `dxcc`, `freq_hz`/`freq_mhz`, `mode`, `age_seconds`,
`confirming_sources`, `spotters`, `best_snr_db`, `bearing_deg`,
`distance_km`, `score.total`, `score.reasons[]`.

## 6. Rešerše read-only historie Log4OM2

Tato sekce je návrhový podklad pro případné pozdější doplnění informace o
shodném QSO ke kandidátovi. Není to povolení zapisovat do databáze Log4OM2 ani
měnit současný tok kandidátů. Ověření proběhlo 7. září 2026 pouze čtením dvou
skutečných SQLite logů nakonfigurovaných v lokálním profilu Log4OM2: lokálního
souboru a aktivního souboru na mapovaném disku, jehož kořenem je UNC share.
Dotazy používaly SQLite URI s `mode=ro&immutable=1` a následné
`PRAGMA query_only=ON`; nevznikl žádný pomocný soubor.

### Ověřený kontrakt tabulky `Log`

Oba soubory obsahovaly tabulky `Informations` a `Log` se shodnými relevantními
sloupci:

| Sloupec | Deklarovaný typ | NULL | Ověřený význam |
|---|---|---|---|
| `callsign` | `VARCHAR(50)` | zakázán | volací značka protistanice; v dotazu porovnávat bez ohledu na velikost písmen po `strip + upper` |
| `mode` | `VARCHAR(30)` | zakázán | mód uložený Log4OM2, například `FT8`, `RTTY`, `USB`; pro Station Agent se musí normalizovat stejnou veřejnou funkcí jako spoty |
| `freq` | `DECIMAL(18,3)` | zakázán, default `0` | vysílací/pracovní frekvence v **kHz**, nikoli Hz ani MHz |
| `freqrx` | `DECIMAL(18,3)` | zakázán, default `0` | přijímací frekvence v kHz; hodnota `0` je v reálných řádcích běžná a znamená, že samostatná RX frekvence není uvedena |

SQLite podle hodnoty ukládá `freq`/`freqrx` jako `INTEGER` nebo `REAL`, přestože
schéma deklaruje `DECIMAL`; čtečka proto nesmí vyžadovat jediný runtime storage
class. Pozorované hodnoty (`14076.1`, `18102.446`, `144174.959`) spolu s módy a
pásmy potvrzují kHz. Převod z interního `Candidate.freq_hz` tedy musí být
`freq_hz / 1000.0`. `freqrx = 0` se nesmí zaměnit za 0 Hz ani použít jako
náhrada za `freq`. Pro běžný simplexní dotaz je autoritativní `freq`; nenulové
`freqrx` lze vrátit jen jako doplňkovou evidenci splitu.

Na ověřeném Windows stroji fungovalo stejné immutable read-only otevření i nad
mapovaným diskem směřujícím na UNC share. To dokládá dostupnost této konkrétní
kombinace klienta, share a SQLite souboru, nikoli obecnou bezpečnost souběžného
čtení živé SQLite databáze přes všechny síťové filesystémy. SQLite zamykání a
soudržnost journal/WAL souborů závisí na implementaci share. Produkční čtečka
má proto selhat uzavřeně, nikdy nesmí přepnout na obyčejné zapisovatelné
`sqlite3.connect(path)` a nesmí na share vytvářet journal, WAL ani SHM soubor.

### Navržené rozhraní

Rozhraní má být samostatný read-only adaptér, ne rozšíření `Database` v
`station_agent/db.py`; tím zůstane lokální historie spotů, ladění a ručně
potvrzených QSO fyzicky oddělená od externího logu.

```python
class LogLookupStatus(str, Enum):
    VERIFIED = "verified"
    UNAVAILABLE = "unavailable"
    UNREADABLE = "unreadable"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class LogLookupResult:
    status: LogLookupStatus
    matches: int = 0
    reason: str = ""
    freq_khz: float | None = None
    freqrx_khz: float | None = None

class Log4OMReadOnlyLog:
    def lookup(self, callsign: str, mode: str, freq_hz: int) -> LogLookupResult: ...
```

Význam stavů je záměrně úplný a fail-closed:

- `verified`: databáze i schéma byly čitelné a existuje alespoň jeden řádek,
  který odpovídá normalizované trojici callsign + mód + frekvence;
- `unavailable`: cesta není nakonfigurovaná, soubor/share neexistuje nebo právě
  není dosažitelný;
- `unreadable`: soubor lze otevřít na úrovni filesystemu, ale read-only SQLite
  otevření, kontrola schématu nebo SELECT selže (oprávnění, poškození,
  nepodporovaný formát, chybějící povinné sloupce);
- `unknown`: databáze a schéma jsou čitelné, ale žádný odpovídající řádek
  neexistuje. Tento stav není důkazem, že QSO nikdy neproběhlo.

Vstup se normalizuje jednou: callsign `strip().upper()`, mód přes
`normalize_mode()` a frekvence z kladného celočíselného Hz na kHz. Protože
Log4OM2 ukládá například `USB`/`LSB`, zatímco Station Agent používá `SSB`, musí
SQL dotaz pro SSB přijmout aliasy `USB`, `LSB`, `SSB` a `PHONE`; ostatní známé
aliasy musí používat stejnou mapu jako `modes.normalize_mode()`, ne druhou
ručně udržovanou normalizaci. Frekvenční tolerance musí být explicitní a
testovaná. Doporučený výchozí kontrakt je nejvýše polovina rozlišení uloženého
sloupce, tedy `abs(freq - :freq_khz) <= 0.0005` kHz; širší toleranci nelze bez
produktového rozhodnutí vydávat za přesnou shodu již uskutečněného QSO.

Bezpečné otevření musí sestavit korektní SQLite `file:` URI i pro mezery,
diakritiku a UNC cestu, použít `mode=ro`, ihned nastavit `PRAGMA query_only=ON`
a povolit jen konstantní SELECT/PRAGMA příkazy. `immutable=1` je vhodné pro
neměnný snapshot nebo zálohu. U živé databáze se nesmí použít bez ověření
journal módu a snapshot strategie: SQLite pak předpokládá, že se soubor nemění,
což může při souběhu s Log4OM2 vracet zastaralý obraz. Pokud nelze živý log
otevřít bez vedlejšího zápisu a konzistentně, výsledek je `unreadable` a GUI
nesmí tvrdit `verified`.

### Místo zapojení a zachované chování

Současný tok je `Spot.__post_init__` (normalizace callsignu, módu a Hz) ->
`Aggregator.build_candidates()` (filtrování, slučování, DXCC/bearing, skóre) ->
`AppState.refresh_candidates()` (`latest_candidates`) ->
`GET /api/candidates` -> `candidate_to_dict()` -> tabulka GUI. AUTO TUNE dostává
tentýž filtrovaný seznam, ale kandidáta nabídne k naladění jen při explicitně
zapnutém AUTO TUNE, vypnutém HOLD, povoleném pásmu/módu a dosažení `min_score`;
další přeladění navíc respektuje aktuální stanici, filtry, `min_hold_seconds` a
`min_score_delta` podle `AutoTuneEngine.decide()`.

Případný lookup se má připojit jako volitelná read-only anotace kandidáta po
jeho sestavení, před serializací. Stav externího logu nesmí kandidáta odstranit,
měnit jeho skóre ani sám zapnout/vypnout či jinak ovlivnit AUTO TUNE. Stávající
`database.path` zůstane cestou výhradně k lokální Station Agent SQLite databázi.
Ruční `POST /api/qso/history` musí dál nejprve explicitně zapsat lokální
`qso_history`; volitelný UDP prefill po stejné operátorské akci zůstane
fire-and-forget a nesmí se změnit na zápis do tabulky `Log`.

Externí cesta patří do nové samostatné konfigurační sekce (například
`log4om_readonly.enabled` a `log4om_readonly.database_path`), defaultně vypnuté.
Nesmí se automaticky odvozovat z `database.path`, UDP `log4om.host/port` ani z
první nalezené zálohy. Automatické načtení profilu Log4OM2 může být jen
explicitní strategie s jednoznačným výsledkem; více profilů/cest musí skončit
stavem `unavailable` s vysvětlením, nikoli tichým výběrem.

### Doporučené testovací scénáře

1. Fixture se skutečným minimálním schématem `Log`: přesná shoda, žádná shoda,
   case/whitespace callsignu, `USB`/`LSB` proti `SSB`, desetinná frekvence a
   hranice tolerance.
2. `freqrx=0` i nenulová split hodnota: lookup používá `freq`, ale výsledek
   bezpečně vrací doplňkovou RX hodnotu nebo `None`.
3. Chybějící cesta/share -> `unavailable`; odmítnuté oprávnění, ne-SQLite
   soubor, chybějící tabulka/sloupec a poškozená DB -> `unreadable`; bez úniku
   tracebacku nebo osobních QSO dat do API/logu.
4. Spy/authorizer ověří, že adaptér provádí jen SELECT a read-only PRAGMA a že
   vedle DB nevznikne `-journal`, `-wal` ani `-shm`; pokusy o INSERT, DDL,
   ATTACH a zapisovatelné PRAGMA jsou odmítnuty.
5. Cesty s mezerou, diakritikou a skutečný dočasný SMB/UNC share na Windows;
   odpojení share během dotazu se mapuje na `unavailable` nebo `unreadable`,
   nikdy na `unknown` či `verified`.
6. Souběh s procesem zapisujícím WAL/rollback-journal: pouze konzistentní
   snapshot smí vrátit `verified`; nepodporovaná síťová konfigurace selže
   uzavřeně. `immutable=1` se testuje jen nad neměnnou fixture/zálohou.
7. Integrační regrese: všechny čtyři stavy se pouze zobrazí; seznam a pořadí
   kandidátů, AUTO TUNE rozhodnutí, lokální `qso_history`, ruční QSO endpoint a
   UDP prefill zůstávají při vypnuté i nedostupné integraci beze změny.
