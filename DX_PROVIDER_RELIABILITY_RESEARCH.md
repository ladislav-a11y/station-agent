# Rešerše reliability metadat DX providerů

Stav k 12. září 2026. Dokument mapuje pouze zdroje, které Station Agent
skutečně zapojuje v `station_agent/cli.py::build_sources()`. Mock je uveden pro
úplnost, QRZ a country-file resolvery nejsou spotové providery a do této
integrace nepatří.

## Závěr

Žádný nyní používaný provider neposkytuje číselnou pravděpodobnost nebo
procentní `reliability` spotu. Hodnota tedy nemá zdroj pravdy a nesmí se
odvozovat ze SNR, počtu spotterů ani textového quality tagu a vydávat za údaj
providera -- dřívější pokus zavést takové pole (`Spot.reliability_percent` /
`Candidate.reliability_percent`, práh `RELIABILITY_THRESHOLD_PERCENT = 95.0`
v aggregatoru) byl proto odstraněn, protože se u žádného zapojeného
providera nikdy neplnil reálnou evidencí.

Místo toho se reliabilita spotu počítá podle principu, který pro DX cluster
spoty používá Log4OM2: hodnocení vychází z **vlastností a potvrzení spotu
samotného** (kolik na sobě nezávislých spotterů/skimmerů nahlásilo stejnou
stanici na stejném pásmu/módu v krátkém časovém okně), ne z toho, který
provider/cluster spot poslal. Implementace je v
`station_agent/scoring.py` (`RELIABLE_SPOTTER_COUNT`, `_reliability_reason`,
`is_reliable_spot`) a využívá evidenci, kterou už `aggregator.py` sbírá do
`Candidate.spotters` při slučování spotů do kandidátů.

| Provider | Skutečné rozhraní a dostupnost | Pole podobné reliability | Typ, jednotka, rozsah | Chybějící hodnota | Dnešní převod do modelu |
|---|---|---|---|---|---|
| W3LPL, Hamserve, EA7JXH, M0MHX (`dx_cluster*`) | dlouhé TCP/telnet spojení; login callsignem, u clusteru následně `sh/dx`; veřejné endpointy jsou v `RECOMMENDED_PROVIDERS` | žádné numerické pole; standardní řádek má frekvenci, DX callsign, volný komentář, UTC čas a spottera. Některé clusterové implementace mohou do komentáře přidat skimmer quality tag (`?`, `P`, `V` apod.), není však součástí stabilního procentního kontraktu používaných uzlů | quality tag je kategoriální text, bez jednotky a bez číselného rozsahu | tag typicky chybí; komentář zůstává obyčejným textem | `adapters/dx_cluster.py::parse_spot_line()` vytvoří `Spot`; `aggregator.py::group_spots_into_candidates()` z něj přenese zdroj, spottera a komentář. Reliability pole neexistuje |
| Reverse Beacon Network (`rbn`) | dlouhé TCP/telnet spojení na `telnet.reversebeacon.net:7000`; standardní spotový řádek skimmeru | `snr` v textu `N dB`; není to reliability ani pravděpodobnost správnosti callsignu | parser přijímá desetinné číslice a ukládá `float`, jednotka dB; protokol zde nedefinuje procentní rozsah | řádek bez očekávaného SNR nesplní současný parser a nevznikne z něj `Spot` | `adapters/rbn.py::parse_rbn_line()` -> `Spot.snr_db`; agregace počítá `Candidate.best_snr_db`. Do reliability se nepřevádí |
| PSKReporter (`pskreporter`) | HTTP GET `https://retrieve.pskreporter.info/query`, XML prvky `receptionReport` | atribut `sNR`; není to reliability. Povinný ingest atribut `informationSource=1` popisuje automatické získání reportu, nikoli procentní důvěru jednotlivého spotu | `sNR` se převádí na `float`, jednotka dB; API nedává procentní rozsah reliability | chybějící/prázdné `sNR` -> `Spot.snr_db=None`; report bez callsignu, frekvence nebo času se přeskočí | `adapters/pskreporter.py::parse_pskreporter_report()` -> `Spot`; agregace stejně jako u RBN. Reliability pole neexistuje |
| Mock | lokální deterministická fixture, žádné externí rozhraní | žádné | — | chybí vždy | `adapters/mock.py::sample_spots()` -> `Spot`; nesmí být vydáván za živá metadata |

Rozhraní a formáty odpovídají implementaci a veřejným popisům
[PSKReporter Developer Information](https://www.pskreporter.info/pskdev.html),
[RBN telnet serveru](https://www.reversebeacon.net/pages/telnet) a
[DXSpider připojení](https://wiki.dxcluster.org/wiki/How_to_connect).
Kvalitativní skimmer tagy a jejich neprocentní význam popisuje
[DXLog Additional Information](https://www.dxlog.net/docs/index.php?title=Additional_Information).

## Implementovaný princip: reliabilita spotu podle Log4OM2

Log4OM2 v cluster filtru neřeší, KTERÝ node/provider spot poslal -- spot
označí za "reliable" až od nakonfigurovaného počtu nezávislých potvrzení
(dalších spotů stejné stanice na stejném pásmu v krátkém časovém okně).
Station Agent tento princip mapuje na existující evidenci takto:

- **Vstup** je `Candidate.spotters` -- množina nezávislých spotterů/skimmerů
  napříč všemi zdroji, které `aggregator.group_spots_into_candidates()` už
  sléva do jednoho kandidáta v rámci časového okna slučování
  (`aggregator.DEFAULT_MERGE_TIME_WINDOW_SECONDS`). Žádný nový síťový dotaz
  ani nové pole na `Spot` není potřeba.
- **Práh** je `scoring.RELIABLE_SPOTTER_COUNT` (2 nezávislí spotteři) --
  stejná konstanta, kterou už používal scoring faktor `reliability`
  (`scoring._reliability_reason`).
- **Výstup** je vždy dopočítatelný bool, ne tříhodnotová `None/True/False`
  logika: `scoring.is_reliable_spot(candidate)` vrací `True`/`False` podle
  počtu spotterů. Na rozdíl od dřívějšího `reliability_percent` polu tu
  neexistuje stav "provider neodpověděl", protože se nic neptá providera --
  evidence je vždy lokálně dostupná (i "0 spotterů" je platná, spočítaná
  hodnota).
- `web/serialization.py::candidate_to_dict()` serializuje výsledek jako
  `"reliable"` (bool), GUI detail kandidáta (`app.js`) jej zobrazuje jako
  "Log4OM2 reliabilita: spolehlivý/nepotvrzený spot" -- frontend hodnotu
  nedopočítává, jen zobrazuje to, co vrátí `is_reliable_spot()`.
- Na rozdíl od zrušeného prahu `RELIABILITY_THRESHOLD_PERCENT` se kandidáti
  s nízkou reliabilitou z výsledků nemažou -- Log4OM2 princip zde ovlivňuje
  jen bodové skóre (`_reliability_reason`) a zobrazený štítek, ne to, jestli
  se kandidát vůbec zobrazí. Filtrování celého seznamu podle reliability tak
  zůstává na uživateli (řazení podle skóre), ne na tichém zahození záznamu.
