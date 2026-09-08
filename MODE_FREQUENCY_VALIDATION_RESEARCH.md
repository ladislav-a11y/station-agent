# Rešerše validace módu podle kmitočtu

Stav podkladu: 2026-09-08. Tento dokument je návrh pro následnou implementaci;
nemění běhové chování Station Agentu.

## Závěr

Station Agent má validovat dvojici `(freq_hz, mode)` samostatnou čistou funkcí,
která vrací strukturovaný výsledek, nikoli `bool`. Pravidla mají být verzovaný
datový katalog odvozený z IARU Region 1 HF bandplánu. Národní alokace ČTÚ a
doporučení IARU jsou dvě různé vrstvy: kmitočet mimo českou amatérskou alokaci
je neplatný, kdežto odchylka od doporučeného segmentu nesmí být vydávána za
porušení zákona.

Konkrétně `7_086_000 Hz + SSB` je správná kombinace. Leží v české amatérské
alokaci 7,0–7,2 MHz a v segmentu IARU Region 1 `7_050–7_200 kHz`, označeném
„all modes“ s maximální šířkou pásma 2700 Hz. Současný fallback v
`bandplan.SSB_SEGMENTS_HZ` ji také klasifikuje jako SSB. Hodnota 7,086 MHz tedy
nesmí být odmítnuta ani přepsána na digitální mód.

## Ověřený současný tok

- Adaptéry převádějí vstupní kHz na celé Hz. `Spot.freq_hz` je `int` a
  `Spot.mode` je normalizovaný katalogový řetězec.
- `Spot.__post_init__` normalizuje mód, pro FT8/FT4 může převést spot na známý
  dial kmitočet a z kmitočtu dopočítá `band`. Neověřuje ale vzájemnou
  přípustnost kmitočtu a módu.
- DX Cluster použije explicitní mód z komentáře; pouze když chybí, volá
  `infer_mode_from_frequency()`. Ta rozpoznává FT8 v úzkých oknech a SSB v
  hrubých hlasových segmentech, jinak vrátí prázdný řetězec. Prázdný nebo
  neznámý mód se následně normalizuje na `OTHER_DIGITAL`, což je odhad, ne
  ověřený fakt.
- Kandidát přebírá celé Hz, normalizovaný mód a pásmo ze spotu. Agregace slučuje
  pouze stejný callsign, pásmo a mód v kmitočtové a časové toleranci.
- Ruční ladění vyžaduje přesnou shodu kandidáta; AUTO TUNE filtruje povolené
  pásmo/mód. Ani jedna cesta dnes nekontroluje bandplanovou kombinaci těsně před
  voláním uzavřeného rig rozhraní.
- Backend `rigctld` převádí katalogové `SSB` pod 10 MHz na LSB a od 10 MHz na
  USB. Při kontrole hrany segmentu je proto nutné počítat i s obsazeným spektrem,
  ne pouze s dial kmitočtem.
- `freq_to_band()` používá inkluzivní obě meze. Pro pravidla sousedních segmentů
  je vhodnější konvence `[lower_hz, upper_hz)`, aby hraniční kmitočet patřil
  právě do jednoho segmentu. Jen poslední horní mez pásma má být inkluzivní.

Existující užitečné mechanismy jsou `normalize_mode()`, `freq_to_band()`,
`canonical_digital_dial_frequency()` a přesná kontrola kandidáta v
`AppState.manual_tune()`. Žádný z nich však není validátorem dvojice.

## Doporučené rozhraní

Umístit veřejné rozhraní do `station_agent/bandplan.py`; katalog lze později
oddělit do `station_agent/bandplan_region1.py`, pokud naroste.

```python
@dataclass(frozen=True)
class ModeFrequencyValidation:
    valid: bool
    band: str | None
    normalized_mode: str
    rule_id: str | None
    reason: str
    source: str

def validate_mode_frequency(
    freq_hz: int,
    mode: str,
    *,
    region: str = "IARU-R1",
) -> ModeFrequencyValidation:
    ...
```

Požadované chování:

1. Odmítnout `bool`, `float`, nekladnou hodnotu a kmitočet mimo podporovanou
   amatérskou alokaci; rozhraní přijímá celé Hz bez implicitního odhadu jednotek.
2. Normalizovat mód jednou přes `normalize_mode()`.
3. Najít právě jeden segment pomocí polootevřených intervalů. Překryv nebo díra
   v katalogu je chyba katalogu, nikoli důvod k tichému odhadu.
4. Katalog módových profilů musí konzervativně odvodit obsazený interval. Pro
   nynější rig politiku použít pro SSB pod 10 MHz LSB `[freq_hz - 2700,
   freq_hz]` a od 10 MHz USB `[freq_hz, freq_hz + 2700]`. Bez znalosti potřebné
   šířky nelze poctivě rozhodnout hraniční případ. `CW` povolit v segmentech CW
   i „all modes“, `SSB` pouze v „all modes“, pokud celý odvozený interval leží
   v segmentu, a digitální módy v odpovídajících narrow/all-mode segmentech.
   Střed aktivity nebo dial frekvence je doporučení, ne jediný platný bod.
5. `OTHER_DIGITAL` v kompatibilním digitálním/all-mode segmentu povolit, protože
   katalogová normalizace ztratila přesný druh emise. V nekompatibilním segmentu
   odmítnout s konkrétním `rule_id` a důvodem.
6. Výsledek používat před vytvořením kandidáta nebo nejpozději při filtrování
   kandidátů. Před samotným laděním zopakovat kontrolu jako ochranu do hloubky.
   Neplatný spot zahodit a diagnostikovat; neměnit mu automaticky mód.

Pro katalog se doporučuje neměnná dataclass s poli `rule_id`, `lower_hz`,
`upper_hz`, `allowed_families`, `max_bandwidth_hz` a `source_revision`.
`rule_id` má být stabilní, například `iaru-r1-2020-40m-7050-7200-all`.

## Zdroj pravidel a omezení

Primární zdroj pro doporučení módů je oficiální **IARU Region 1 HF Bandplan**,
účinný od 2020-10-16, zveřejněný na stránce dokumentů HF Committee:

- https://www.iaru-r1.org/about-us/committees-and-working-groups/hf-committee-c4/documents-hf/

Primární zdroj pro českou alokaci je ČTÚ. Jeho aktuální spektrální přehled
potvrzuje amatérskou službu v 7,000–7,100 MHz a navazující části do 7,200 MHz;
ČTÚ současně upozorňuje, že právně závazné jsou české texty národní tabulky a
plánu využití spektra:

- https://spektrum.ctu.gov.cz/kmitocty/7000-7100-khz
- https://spektrum.ctu.gov.cz/kmitocty/7100-7200-khz
- https://ctu.gov.cz/plan-vyuziti-radioveho-spektra

Katalog musí nést revizi zdroje a být aktualizován vědomou změnou. IARU bandplan
je dobrovolný provozní plán, nikoli úplná právní kontrola oprávnění operátora,
třídy licence, výkonu, šířky skutečného signálu nebo národních výjimek. Bez
takových vstupů funkce nesmí tvrdit celkovou legálnost vysílání.

## Případy pro následnou implementaci

Minimální parametrizovaná sada (očekávání platí pro Region 1 katalog):

| Kmitočet | Mód | Výsledek | Důvod |
|---:|---|---|---|
| 6 999 999 Hz | SSB | neplatný | pod dolní mezí 40 m |
| 7 000 000 Hz | CW | platný | inkluzivní dolní mez 40 m, CW segment |
| 7 000 000 Hz | SSB | neplatný | hlasový mód v CW segmentu |
| 7 039 999 Hz | CW | platný | poslední Hz CW segmentu |
| 7 040 000 Hz | FT8 | platný | začátek narrow-mode segmentu; nevyžadovat jen 7,074 MHz |
| 7 040 000 Hz | SSB | neplatný | začátek narrow-mode segmentu, šířka SSB se nevejde |
| 7 049 999 Hz | RTTY | platný | poslední Hz narrow-mode segmentu |
| 7 050 000 Hz | SSB | neplatný | LSB by zasáhlo pod začátek all-mode segmentu |
| 7 052 699 Hz | SSB | neplatný | konzervativní 2700Hz LSB profil ještě přesahuje hranu |
| 7 052 700 Hz | SSB | platný | první dial kmitočet, jehož celý LSB profil leží v all-mode segmentu |
| 7 074 000 Hz | FT8 | platný | známý FT8 dial uvnitř all-mode segmentu |
| 7 086 000 Hz | SSB | platný | výslovný regresní případ, all modes |
| 7 086 000 Hz | CW | platný | „all modes“ neznamená jen telefonii |
| 7 199 999 Hz | SSB | platný | těsně pod horní hranou pásma |
| 7 200 000 Hz | SSB | platný | horní mez národní alokace; rozhodnout explicitním koncovým pravidlem |
| 7 200 001 Hz | SSB | neplatný | nad horní mezí 40 m |
| 10 100 000 Hz | SSB | neplatný | 30 m není hlasový segment |
| 10 136 000 Hz | FT8 | platný | známý digitální dial na 30 m |
| 14 074 000 Hz | FT8 | platný | známý digitální dial na 20 m |
| 14 195 000 Hz | SSB | platný | all-mode hlasový úsek 20 m |
| 50 000 000 Hz | libovolný | podle rozsahu | současný kód jej záměrně vylučuje; před rozšířením katalogu potvrdit českou 6m mez a odstranit zvláštní guard jen samostatnou změnou |
| libovolný | `""`/neznámý | neurčovat z frekvence jako fakt | zachovat informaci o nejistotě; inference je oddělená od validace |

Test katalogu má navíc automaticky dokazovat seřazení, absenci překryvů,
jednoznačné pokrytí hran a existenci `source_revision` u každého pravidla.
Test integračního toku má prokázat, že neplatná kombinace nedojde do kandidátů
ani k volání metod pro nastavení frekvence/módu, zatímco 7,086 MHz SSB projde
beze změny. Dočasný harness ani stažená kopie zdrojového PDF nejsou pro tuto
rešerši v repozitáři potřeba a nebyly vytvořeny.
