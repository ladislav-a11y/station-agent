# Rešerše reliability metadat DX providerů

Stav k 8. září 2026. Dokument mapuje pouze zdroje, které Station Agent
skutečně zapojuje v `station_agent/cli.py::build_sources()`. Mock je uveden pro
úplnost, QRZ a country-file resolvery nejsou spotové providery a do této
integrace nepatří.

## Závěr

Žádný nyní používaný provider neposkytuje číselnou pravděpodobnost nebo
procentní `reliability` spotu. Hodnota tedy dnes nemá zdroj pravdy a nesmí se
odvozovat ze SNR, počtu spotterů ani textového quality tagu a vydávat za údaj
providera. Současný scoring faktor `reliability` je jiná veličina: lokální,
transparentní bonus podle počtu nezávislých spotterů
(`station_agent/scoring.py::_reliability_reason`).

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

## Konkrétní integrační návrh pro procenta a práh 95 %

Implementace má být aktivována až pro provider, jehož verifikované rozhraní
skutečně dodá číselnou pravděpodobnost. Interní kanonický kontrakt:

```python
@dataclass
class Spot:
    # ... existující pole beze změny
    reliability_percent: float | None = None

@dataclass
class Candidate:
    # ... existující pole beze změny
    reliability_percent: float | None = None
```

- Název interního pole je `reliability_percent`, aby se nezaměnilo s dnešním
  scoring faktorem. Typ je `float | None`, jednotka procenta, uzavřený rozsah
  `0.0..100.0`; konstanta prahu má být
  `RELIABILITY_THRESHOLD_PERCENT = 95.0`.
- Providerův parser převede zdrojové pole právě jednou do procent. Pokud zdroj
  vrací zlomek `0..1`, násobí jej 100; pokud vrací procenta, pouze jej převede
  na `float`. Nečíselné, NaN, nekonečné a mimorozsahové hodnoty se mapují na
  `None` a zalogují bez obsahu celého odpovědního payloadu.
- Správné místo převodu `Spot -> Candidate` je
  `aggregator.group_spots_into_candidates()`, vedle `best_snr_db`. Z dostupných
  hodnot ve shluku se použije minimum. Kandidát tak splní práh pouze tehdy,
  když žádná providerem ohodnocená evidence ve sloučeném shluku neklesne pod
  95 %. Agregace nesmí dopočítat číslo z providerů, kteří údaj nemají.
- Vyhodnocení je tříhodnotové: `None` = provider údaj neposkytl,
  `True` = procento je nejméně 95, `False` = procento je pod 95. `None` se
  nesmí zaměnit za nulu ani za neúspěch.
- Práh se má aplikovat jen v nové, explicitně zapnuté produktové funkci
  (například filtr či nový ScoreReason). Při vypnuté funkci a pro kandidáta s
  `None` zůstávají seznam, pořadí, score, notifikace i AUTO TUNE bitově stejné
  jako dnes. Tím se zachová současné chování všech nynějších providerů.
- `web/serialization.py::candidate_to_dict()` může pole pouze serializovat;
  frontend je nesmí dopočítávat. API hodnota pro chybějící údaj je JSON
  `null`, nikoli `0`, `50` nebo `95`.

## Podmínky před implementací

Pro nový provider je nutné uložit fixture jeho skutečné odpovědi a doložit:
přesný externí název pole, datový typ, jednotku, deklarovaný rozsah a význam
chybějící hodnoty. Cílené testy mají pokrýt obě hrany (`94.999`, `95.0`),
`None`, neplatná čísla, normalizaci jednotek, slučování více spotů a regresi,
že staré providery bez metadat produkují stejné kandidáty a skóre. Bez takto
ověřeného kontraktu zůstane živý fetch podle `AGENTS.md` pending stubem a
procentní pole se nebude plnit odhadem.
