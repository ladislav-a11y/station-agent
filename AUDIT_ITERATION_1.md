# Návrh zpřehlednění živého GUI — iterace 1

## Rozsah a ověřený stav

Dne 10. 9. 2026 byl Station Agent spuštěn s aktivním `config.yaml` v režimu
`rig.mode: live` na `http://127.0.0.1:8765`. Po dokončení inicializace nebyl
žádný DX provider ve stavu `pending`: `dx_cluster`, tři pojmenované clusterové
uzly, `rbn` i `pskreporter` hlásily `ok`. Vizuální kontrola proběhla v živém
Windows GUI (Edge, 1500 px široké okno). Tento dokument je pouze návrh; žádný
GUI kód ani chování nebylo změněno.

## Zjištění a návrh

### 1. Provozní souhrn v hlavičce

**Problém:** Hlavička má čtyři stejně silné karty. Karta `Zdroje` obsahuje až
šest dlouhých technických názvů a vytlačuje čitelnou odpověď na nejdůležitější
otázku operátora: „je vše připravené k práci?“. Stav riggu je zase dlouhý,
zalomený řetězec, kde je live režim, frekvence, stanice, země a cesta bez
hierarchie.

**Návrh:** Nahradit kartu `Zdroje` kompaktním souhrnem `Zdroje: 6/6 v pořádku`
se zeleným stavovým bodem. Po rozbalení nebo v tooltipu zobrazit jednotlivé
poskytovatele, jejich poslední úspěch a případnou chybu. Kartu riggu rozdělit
na hlavní řádek `14,074 MHz · FT8 · CX1AR` a sekundární řádek `Uruguay · 233°
· 11 630 km`; výrazný štítek `LIVE` má být samostatný, ne součástí textu.
Propagaci a Log4OM zobrazit jako krátké kontrolní indikátory se stavem a časem
posledního ověření.

### 2. Jednoznačný stav automatického ladění

**Problém:** Aktivní `AUTO TUNE`, `HOLD`, odpočet, poslední rozhodnutí a tři
prahy jsou rozdělené do více řádků. Tlačítka s textem `OK` nepopisují akci;
není na první pohled zřejmé, zda jimi stav pouze potvrzuji, zapínám nebo
vypínám.

**Návrh:** Vytvořit nahoře v sekci jeden dominantní stavový pruh:
`AUTO TUNE aktivní — další vyhodnocení za 50 s` nebo `HOLD aktivní — ruční
ladění`. Vedle něj použít dvě explicitní přepínací akce `Zapnout AUTO TUNE` a
`Zapnout HOLD`; neaktivní akce má být vizuálně sekundární. Práhy přesunout do
rozbalovacího bloku `Nastavení ladění` a poslední rozhodnutí označit titulkem
`Proč se nyní neladí` / `Poslední naladění`, podle výsledku.

### 3. Pořadí ploch podle pracovní priority

**Problém:** Na první obrazovce zabírá celou šířku pasivní legenda a velký
panel propagace, zatímco kandidáti, tedy hlavní pracovní seznam, jsou až níže.
Filtry jsou roztříštěné do jedenácti pásem a osmi módů bez rychlého přehledu,
co je právě aktivní.

**Návrh rozvržení (desktop):**

1. hlavička: souhrn riggu, AUTO TUNE, zdrojů a bezpečnostních kontrol;
2. hlavní levý sloupec: `Kandidáti` včetně výběru a akcí;
3. pravý sloupec: `Rychlé filtry` s předvolbami, počtem zobrazených kandidátů
   a odkazem `Pokročilé filtry` pro jednotlivá pásma/módy;
4. pod kandidáty: kompaktní `Propagace` a `Historie / notifikace`;
5. legenda jako ikona nápovědy u stavů, ne jako samostatný panel v běžném
   pracovním toku.

Na užších oknech má být toto pořadí zachováno ve sloupci: provozní stav,
kandidáti, rychlé filtry, AUTO TUNE a až potom podpůrné informace.

### 4. Kandidáti a akce nad výběrem

**Problém:** Instrukce „Klikni … pak naladi tlačítkem NALADIT. Poklikej …“
spojuje dvě odlišné interakce do jedné věty a tlačítko `ZAPSAT QSO DO
HISTORIE` vedle ladění vypadá jako stejně běžná následná akce. U živých dat je
nutné zřetelně odlišit výběr, naladění a vědomé zapsání místní historie.

**Návrh:** Nad tabulkou použít pevný pruh `Vybraný kandidát: žádný` a po
výběru `Vybraný: CALL · frekvence · mód`. Primární akce má být `Naladit
přijímač`; sekundární akce `Zapsat do místní historie` má mít doplňující
popisek „neukládá QSO do Log4OM2“. Detail skóre otevřít jedním označeným
ovladačem v řádku, například `Zobrazit důvody skóre`, namísto poklepání.
Tabulka má mít připnuté záhlaví a zkrácené názvy zdrojů v buňce s plným
seznamem v tooltipu či detailu.

### 5. Stavové indikace a srozumitelné názvy

**Problém:** Barva stavů je dublována obsáhlou legendou. Zdroje používají
implementační jména (`dx_cluster_hamserve`, `rbn`), stav Log4OM je formulovaný
jako technické připojení a v běžném pohledu chybí čas stáří dat. Samotná barva
nepostačí pro rychlou interpretaci ani přístupnost.

**Návrh:** Všude používat kombinaci ikony, textu a barvy: `● V pořádku`,
`◌ Inicializuji`, `◐ Opakuji za 2 min`, `! Vyžaduje pozornost`. V souhrnu
zobrazit nejhorší stav; detail zachová poslední úspěch a konkrétní chybu.
Uživatelské názvy poskytovatelů mají být například `DX Cluster (W3LPL)`,
`DX Cluster (HamServe)`, `Reverse Beacon Network` a `PSK Reporter`, technické
ID jen v detailu. `Log4OM2` přejmenovat na `Kontrola historie Log4OM2` a
zobrazit jednoznačný stav filtru `Zapnuta / Vypnuta`.

### 6. Propagace jako podpůrný kontext

**Problém:** Sekce kombinuje výukový odstavec, číselné vstupy, jedenáct štítků
a diagnostickou větu. To prodlužuje obrazovku, přestože pro operátora je
nejdřív důležitý závěr pro aktuálně vybrané pásmo.

**Návrh:** Výchozí pohled má ukazovat `Podmínky: dobré / střední / slabé` pro
aktuální pásmo, Kp, SFI a stáří měření. Celý rozpad po pásmech a vysvětlení
nechat v rozbalení `Zobrazit výhled pásem`. Zkrátit titul na `Propagace`;
vysvětlující text nabídnout přes nápovědu.

## Dotčené soubory při budoucí implementaci

| Soubor | Předpokládaná role |
| --- | --- |
| `station_agent/web/static/index.html` | Semantické uspořádání hlavičky, prioritních panelů a ovladačů kandidáta. |
| `station_agent/web/static/style.css` | Desktop/mobile grid, vizuální hierarchie, kontrastní textové stavové indikátory a připnuté záhlaví tabulky. |
| `station_agent/web/static/app.js` | Seskupené vykreslení souhrnu poskytovatelů, popisky akcí, rozbalení detailů a dostupné texty stavů. |
| `station_agent/web/static/autotune_controls.js` | Jen pokud se změna přepínačů AUTO TUNE/HOLD projeví v jejich interakci. |
| `station_agent/web/static/selected_score.js` | Jen pokud se sloučí indikátor naladěné a vybrané stanice do nového provozního souhrnu. |
| `station_agent/web/server.py` | Pouze pokud GUI potřebuje nový agregovaný údaj (např. počet zdrojů podle stavu nebo čas poslední změny); stávající kontrakty přednostně zachovat. |
| `tests/test_web_api.py` | Ověření případného rozšíření API kontraktu. |

## Doporučený postup implementace

1. Nejprve nakreslit statický desktopový a úzký mobilní návrh s výše uvedeným
   pořadím; potvrdit texty akcí a stavů s operátorem.
2. Upravit pouze HTML/CSS: přesunout kandidáty výše, legendu nahradit
   kontextovou nápovědou a dát AUTO TUNE jeden stavový pruh. Neměnit API ani
   chování ovladačů.
3. Poté upravit klientské vykreslení souhrnů; zachovat stávající významy
   `ok`, `pending`, `backoff` a `error` a nikdy neukrýt konkrétní chybu.
4. Až případně nakonec přidat minimální odvozená data do `/api/status`, včetně
   regresních testů kontraktu. Neměnit ovládání rigu, rozsah ladění ani tok
   Log4OM prefillu.
5. Ručně zkontrolovat živý režim se všemi providery ve stavech `ok`,
   `pending`, `backoff` a `error`, s AUTO TUNE i HOLD a s prázdným i vybraným
   kandidátem.
