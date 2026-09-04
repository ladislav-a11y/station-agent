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
| `dxcc` | `dxcc.callsign_to_dxcc(callsign)`, při `None` volitelně `dxcc_fallback(callsign)` | offline prefix tabulka má přednost, žádné externí volání; `dxcc_fallback` (typicky `adapters/qrz.py::QRZClient.lookup`) se zavolá jen když tabulka selže a je nakonfigurovaný (`qrz.enabled`), viz README "DXCC/země fallback přes QRZ.com" |
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
| `propagation` | hodinový `PropagationContext.band_quality` připravený z aktuálního NOAA Kp/SFI, QTH lokátoru a lokálního slunečního času; scoring sám síť nikdy nevolá. Při nedostupném snapshotu slouží jako fallback `aggregator.band_activity` | chybí snapshot i `band_activity` -> neutrálních 50 % váhy |
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
