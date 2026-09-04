# Diagnóza -- selhání určení země/DXCC u stanic jako 4L5O

Rozsah tohoto dokumentu: **analýza a zdokumentování mezery**, ne oprava.
Zadání explicitně žádá jen "zanalyzovat, proč ... selhává" a "zdokumentovat
konkrétní mezeru ve zdroji dat", s dovětkem "zachovat chování mimo tento
rozsah" -- proto tato iterace neupravuje `station_agent/dxcc.py` ani
žádný jiný produkční soubor. Přidání konkrétních chybějících prefixů je
navazující, ale odlišná (implementační) práce.

## Skutečná příčina

`station_agent/dxcc.py::PREFIX_TABLE` je -- podle vlastního modulového
docstringu -- "záměrně NEúplná" ruční tabulka, která má aktuálně **95
položek** oproti reálným **~340 DXCC entitám** dle oficiálního seznamu
ARRL/DXCC. `callsign_to_dxcc()` dělá longest-prefix-match čistě nad touto
tabulkou a bez výjimky vrací `None`, když žádný prefix callsignu v tabulce
není -- to je zdokumentované, záměrné a bezpečné chování (`AGENTS.md`
pravidlo 6 "Nefalšuj externí služby": raději `None`/"?" v GUI než
vymyšlená země), ale zdrojem dat samotné mezery je neúplnost tabulky.

`4L` je ITU/DXCC prefixový blok přidělený **Gruzii (Georgia)**. V
`PREFIX_TABLE` neexistuje žádný klíč začínající na `4L` (ověřeno přímo:
`[k for k in PREFIX_TABLE if k.startswith("4L")] == []`), takže pro
libovolný callsign s tímto prefixem (`4L5O`, `4L7T`, ...) projde
`_iter_prefix_candidates()` postupně `4L5O -> 4L5 -> 4L -> 4` a žádný z
nich se v tabulce nenajde -> `callsign_to_dxcc()` vrací `None`.

### Živý důkaz z dnešního běhu (2026-09-04)

Přímo produkční funkcí `adapters/pskreporter.py::fetch_pskreporter_xml` +
`parse_pskreporter_report` (stejná dvojice, kterou volá
`PSKReporterAdapter.fetch()`) proti `https://retrieve.pskreporter.info/query`
(`flowStartSeconds=-3600`, posledních 60 minut globální aktivity, dotaz
proveden **2026-09-04**):

```
Spot(callsign='4L7T', freq_hz=14074000, mode='FT8',
     timestamp=1788554220.0  # 2026-09-04T20:37:00Z
     source='pskreporter', snr_db=-9.0, spotter='OE2XZR',
     band='20m', country=None, locator='LN21JR42', ...)
```

`callsign_to_dxcc('4L7T')` i `callsign_to_dxcc('4L5O')` (přesně zadaný
příklad z DoD) obě vrací `None`:

```
>>> callsign_to_dxcc("4L5O")
None   # prefix candidates tried: ['4L5O', '4L5', '4L', '4']
>>> callsign_to_dxcc("4L7T")
None   # prefix candidates tried: ['4L7T', '4L7', '4L', '4']
```

`4L7T` je reálná, právě dnes živě přijatá stanice se stejným prefixem jako
zadaný `4L5O` -- ne fixture/mock data (viz `country=None` v samotném
spotu, `Spot.country` se u žádného adaptéru nikdy nevyplňuje přímo, viz
`DATA_CONTRACT.md` sekce 1 a `NEXT_DOD.md` bod 6). Downstream v
`aggregator.attach_dxcc_and_bearing()` se u tohoto kandidáta `candidate.dxcc`
nastaví na `None` a `candidate.country` zůstane `None` (GUI zobrazí "?"),
přesně podle zdokumentovaného fallback chování -- selhání tedy není bug v
logice fallbacku, ale v obsahu zdrojové tabulky, ze které fallback čerpá.

## Kvantifikace mezery (širší, ne jen "4L")

Stejný živý dotaz (1 hodina PSKReporter provozu, **1498 spotů / 473
distinct callsignů**) ukázal, že mezera je systémová, ne izolovaný
jednopísmenný případ:

- **124 z 473 distinct callsignů (≈26 %)** v této jedné hodině nemělo
  žádnou shodu v `PREFIX_TABLE` a skončilo s `dxcc=None`.
- Část mezery jsou zcela chybějící DXCC entity (např. `4L` Georgia, `E7`
  Bosna a Hercegovina -- viz živě zachycený `E77SR`, `EK` Arménie -- viz
  `EK7WF`/`EK0JV`, `TK` Korsika, `EW` Bělorusko).
- Část mezery je jemnější a zasahuje i země, které tabulka **částečně**
  pokrývá: tabulka má jen jeden kanonický prefix na entitu (např. `"JA"`
  pro Japonsko, `"G"` pro Anglii), ale reálné callsigny v dané DXCC entitě
  legálně používají i další prefixová písmena, která v tabulce chybí:

  ```
  JA1XYZ -> Japan          (v tabulce je "JA")
  JE3GUG -> None           (živě přijato jako 'JE3GUG', prefix "JE" chybí)
  JR4KVI -> None           (živě přijato jako 'JR4KVI', prefix "JR" chybí)
  JH1ABC -> None           (Japonsko běžně přiděluje i JB-JS, žádné není v tabulce)

  G0ABC  -> England        (v tabulce je "G")
  M0KTC  -> None           (živě přijato jako 'M9KTC'/'M0...', prefix "M0"/"M1"/"M5" chybí)
  2E0XYZ -> None           (moderní britský "Foundation" prefix, taky chybí)
  ```

  Tzn. i operátor s dobře pokrytou DXCC entitou (Japonsko, Anglie) může
  v GUI vidět "?" místo země jen kvůli tomu, že jeho konkrétní přidělené
  písmeno prefixu není v tabulce vyjmenované -- ne proto, že by jeho země
  byla neznámá.
- Podobně `UA` (European Russia) je v tabulce, ale živě přijaté ruské
  stanice v jednopísmenném formátu (`R7ZY`, `R1BBG`, `RI1FJL`, `RN2F`) mají
  prefix `R`, ne `UA` -- žádný klíč `"R"` v tabulce není, takže i běžné
  ruské volačky bez „UA/UB/...“ tvaru selžou stejným způsobem.

## Důsledky v datovém toku (beze změny, jen popis)

Podle `DATA_CONTRACT.md`:

- `Candidate.dxcc = None` -> `candidate.country` zůstane `None`, pokud ho
  nedodá zdroj (žádný adaptér ho nikdy nedodává, viz sekce 1) -- GUI
  zobrazí "?", ne vymyšlenou hodnotu (správné, zamýšlené chování).
- `scoring.needed_dxcc`: neznámá DXCC entita se **vždy** považuje za
  "potřebnou" (`db.is_worked(dxcc.name)` nemá co zavolat) -- operátor tak
  nemůže rozlišit "vzácná, potvrzeně nepracovaná entita" od "entita, kterou
  prefixová tabulka prostě nezná". Skóre samo o sobě chybu nemaskuje, jen
  ji promítá jako falešně vysokou prioritu.
- `bearing`/`distance` fallback na referenční bod DXCC entity
  (`aggregator.attach_dxcc_and_bearing`) je u těchto kandidátů taky
  nedostupný, pokud navíc chybí platný Maidenhead lokátor -- u `4L7T` v
  tomto konkrétním živém spotu lokátor `LN21JR42` byl přítomný, takže
  bearing/distance šly dopočítat i bez DXCC bodu; u kandidátů bez lokátoru
  by ale selhaly obě věci najednou.

## Závěr

Konkrétní zdokumentovaná mezera ve zdroji dat: `station_agent/dxcc.py::PREFIX_TABLE`
neobsahuje žádný záznam pro prefix `4L` (DXCC entita Georgia), což je
přímá příčina, proč `4L5O`/`4L7T` v dnešním živém běhu nedostanou zemi/DXCC.
Šířeji je tabulka omezena na 95 z ~340 DXCC entit a navíc i u pokrytých
entit vyjmenovává jen jeden kanonický prefix místo celého přiděleného
rozsahu, což způsobuje stejný symptom (`None`) i u řady jinak dobře
známých zemí (živě doloženo na Japonsku, Anglii a Rusku výše).

Chování mimo tento rozsah nebylo měněno -- žádný soubor v `station_agent/`
nebyl touto iterací upraven, ověřeno `git status --porcelain`.
