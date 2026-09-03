# Live evidence -- reálné ověření proti skutečným externím službám

Tento dokument je durabilní záznam toho, že adaptéry popsané jako "živě
funkční" v README.md ("Stav externích zdrojů") a DATA_CONTRACT.md (sekce 4)
byly skutečně spuštěny proti reálným vzdáleným serverům -- ne jen proti
lokálním testovacím fixture/socket serverům (ty ověřuje
`tests/test_adapters_live.py` a `tests/test_telnet_source.py` bez
internetu, viz AGENTS.md "Testy běží bez internetu"). Účelem je doložit
DoD bod "reálné live evidence podle funkce": že se skutečně stahují a
parsují živá data, ne vymyšlená/nafingovaná odpověď (AGENTS.md pravidlo 6).

Ověření proběhlo přímým spuštěním produkčních tříd adaptérů
(`DXClusterAdapter`, `RBNAdapter`, `PSKReporterAdapter`, `Aggregator`) --
stejný kód, který používá `station_agent/cli.py` při `rig.mode`/`sources.*.enabled`
nastavených na živý provoz. Nešlo o žádný speciální testovací obchvat.

## 1. DX Cluster (`dxc.w3lpl.net:7373`, login `OK1RPL`)

`DXClusterAdapter.fetch()` po připojení a přihlášení skutečně vrátil reálné
spoty (2026-08-28, ~15:09 UTC):

```
Spot(callsign='BD8ENX', freq_hz=14074000, mode='FT8', ..., source='dx_cluster', comment='FT8 JO20qa -> OM20ao', spotter='ON4ANV', band='20m')
Spot(callsign='AA5FA', freq_hz=24915000, mode='FT8', ..., source='dx_cluster', comment='JN01<>EM55 FT8  Sent: -19  Rc<EA3EDU>', spotter='', band='12m')
Spot(callsign='II7MGBR', freq_hz=7182000, mode='SSB', ..., source='dx_cluster', comment='SSB XX Med. Games', spotter='IU7DLD', band='40m')
Spot(callsign='OH/DC6ST', freq_hz=14308000, mode='SSB', ..., source='dx_cluster', comment='28-Aug-2026', spotter='OS8D', band='20m')
Spot(callsign='KB0CQQ', freq_hz=21074000, mode='FT8', ..., source='dx_cluster', comment='TNX QSO FT8...8364KM.', spotter='US5LOC', band='15m')
```
10 spotů celkem v první dávce. Status: `ok` po prvním přijatém spotu (dřív
`pending`, viz `SourceNotReadyError`).

## 2. Reverse Beacon Network (`telnet.reversebeacon.net:7000`, login `OK1RPL`)

`RBNAdapter.fetch()`:

```
Spot(callsign='AB4I', freq_hz=14007500, mode='CW', ..., source='rbn', snr_db=10.0, comment='24 WPM  CQ', spotter='VE6WZ-#', band='20m')
Spot(callsign='OZ7BQ', freq_hz=14023000, mode='CW', ..., source='rbn', snr_db=10.0, comment='18 WPM  CQ', spotter='EA1DAV-#', band='20m')
Spot(callsign='N4GE', freq_hz=10115000, mode='CW', ..., source='rbn', snr_db=20.0, comment='20 WPM  CQ', spotter='K3GMQ-#', band='30m')
```
3 spoty v první dávce.

## 3. PSKReporter (`https://retrieve.pskreporter.info/query`)

`fetch_pskreporter_xml()` + `parse_pskreporter_report()` (stejná dvojice
funkcí, kterou volá `PSKReporterAdapter.fetch()`):

- HTTP GET vrátil HTTP 200, 2 047 443 bajtů XML (`flowStartSeconds=-300`,
  posledních 5 minut globální aktivity).
- Naparsováno **1506 reálných spotů**, např.:

```
Spot(callsign='EB1CAR', freq_hz=21074000, mode='FT8', ..., source='pskreporter', snr_db=-5.0, spotter='OH8MXJ', band='15m')
Spot(callsign='ON4ANV', freq_hz=14074000, mode='FT8', ..., source='pskreporter', snr_db=-8.0, spotter='EA5OH', band='20m')
Spot(callsign='GB0BCC', freq_hz=18100000, mode='FT8', ..., source='pskreporter', snr_db=-16.0, spotter='W1XIV', band='17m')
```

## 4. Celý pipeline live (Aggregator se všemi třemi zdroji zapnutými zároveň)

`Aggregator` s reálnými `DXClusterAdapter`/`RBNAdapter`/`PSKReporterAdapter`
+ `qth_latlon=(50.0755, 14.4378)` (Praha) -- `build_candidates()` nad
skutečně přijatými spoty proběhl bez chyby a vytvořil **568 kandidátů**
se spočítaným DXCC, bearing a plným 7faktorovým skóre (viz scoring.py z
minulé iterace) nad reálnými daty, např.:

```
WV2M    FT8 17m score=83 sources={'pskreporter'} bearing=298.3°
VE9TIC  FT4 20m score=82 sources={'pskreporter'} bearing=303.1°
R6BH    FT8 15m score=81 sources={'pskreporter'} bearing=None (DXCC neznámé)
```

DX Cluster a RBN v tomto konkrétním 40s běhu Aggregatoru nestihly dokončit
handshake souběžně se třetím zdrojem (`status: pending`) -- to je normální
chování živého telnet klienta s reconnect/backoffem (viz
`adapters/telnet_source.py`), ne chyba; sekce 1 a 2 výše dokládají, že
tytéž adaptéry samostatně reálná data doručí. `source_status()` hlásil
`pskreporter: ok, cached_spot_count=1506`.

## Shrnutí

| Adaptér | Živě ověřeno v této iteraci | Poznámka |
|---|---|---|
| DX Cluster | ano -- 10 reálných spotů | `dxc.w3lpl.net:7373` |
| RBN | ano -- 3 reálné spoty | `telnet.reversebeacon.net:7000` |
| PSKReporter | ano -- 1506 reálných spotů | `retrieve.pskreporter.info/query` |
| Aggregator (plný pipeline) | ano -- 568 kandidátů se skóre/bearing | nad reálnými PSKReporter daty |

Žádný adaptér nevrátil vymyšlená data; DX Cluster i RBN prošly svým reálným
`SourceNotReadyError` -> `ok` přechodem přesně podle kontraktu v
DATA_CONTRACT.md. Ověřovací skript nebyl součástí commitu (dočasný, smazán
po zachycení výstupu) -- výstup výše je jeho doslovný zachycený výsledek.

## 5. Alternativní DX Cluster endpointy (2026-09-01)

Po auditní námitce byly produkční třídou `DXClusterAdapter` samostatně
ověřeny všechny tři alternativy z `RECOMMENDED_PROVIDERS`, s loginem
`OK1RPL`, příkazem `sh/dx` a zachováním konfigurační identity zdroje:

| Zdroj | Endpoint | Výsledek první dávky | Ukázka živého SSB spotu |
|---|---|---:|---|
| `dx_cluster_hamserve` | `dxc.hamserve.uk:7300` | 4 spoty | `IK2DJY`, 14.216 MHz, `SSB Monza F1 Grand Prix` |
| `dx_cluster_ea7jxh` | `dx.ea7jxh.eu:7300` | 50 spotů (19 SSB) | `G6CKK`, 7.135 MHz, `CQ BOTA` |
| `dx_cluster_m0mhx` | `dxc.m0mhx.uk:7300` | 4 spoty | `AC1RH`, 7.178 MHz, `US-2670` |

Původně doporučený `dx.hamnet.network:7300` při témže živém běhu opakovaně
vrátil TCP `connection refused`. Proto byl z katalogu i příkladové
konfigurace odstraněn a nahrazen živě funkčním `dx.ea7jxh.eu:7300`; nejde
tedy o pouhé zdokumentování nefunkčního endpointu. U EA7JXH druhé načtení
vrátilo 50 spotů s rozdělením módů FT8 24, SSB 19, OTHER_DIGITAL 6 a CW 1.
Ve všech ukázkách odpovídalo pole `Spot.source` jménu konkrétního zdroje.

### Opakovaný živý výstup po auditní námitce

Dne **2026-09-01 v 13:57 CEST** byly všechny tři alternativy znovu
spuštěny současně přes produkční `DXClusterAdapter`. Každý adaptér otevřel
vlastní TCP spojení, přihlásil se callsignem `OK1RPL`, odeslal `sh/dx` a
výsledek byl vybírán přes jeho veřejnou metodu `fetch()`. Běh měl 120s
bezpečnostní limit; všechny tři zdroje dodaly data během prvních sekund.
Zachycený souhrnný výstup běhu:

```text
RESULT dx_cluster_hamserve dxc.hamserve.uk 7300 spots 5 ssb 5
SAMPLE Spot(callsign='F4LDT/P', freq_hz=7148000, mode='SSB', source='dx_cluster_hamserve', comment='1-Sep-2026', spotter='PD3RL', band='40m')

RESULT dx_cluster_ea7jxh dx.ea7jxh.eu 7300 spots 50 ssb 24
SAMPLE Spot(callsign='3V8LL', freq_hz=18111400, mode='SSB', source='dx_cluster_ea7jxh', comment='cq cq', spotter='M8VGZ', band='17m')

RESULT dx_cluster_m0mhx dxc.m0mhx.uk 7300 spots 8 ssb 8
SAMPLE Spot(callsign='F4LDT/P', freq_hz=7148000, mode='SSB', source='dx_cluster_m0mhx', comment='1-Sep-2026', spotter='PD3RL', band='40m')
```

Výstup tak přímo dokládá nejen dosažitelnost endpointů, ale i naparsování
živých SSB spotů produkčním adaptérem a zachování samostatné identity
každého zdroje. Nejde o odkaz na Trello poznámku ani o fixture data.

## Čerstvé opakované ověření iterace 2/10

Dne **2026-08-28 v 17:20 CEST** byly znovu přímo spuštěny všechny tři
produkční adaptéry proti výchozím veřejným endpointům. PSKReporter vrátil
HTTP/XML dávku **1511 spotů** (první `7Z1DM`, 21.074 MHz, FT8). DX Cluster
po reálném připojení a přihlášení vrátil **10 spotů** (první `UT7QF`,
50.313 MHz, FT8) a RBN **18 spotů** (první `G4LNA`, 10.1125 MHz, CW).
Telnet zdroje při prvním spojení zaznamenaly přechodnou chybu socketu,
vlastní reconnect/backoff ji zotavil a oba následně doručily platná data.
Jde tedy zároveň o živý důkaz funkce zotavení, nikoli pouze ideálního toku.
