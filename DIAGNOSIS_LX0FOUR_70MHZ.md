# Diagnostika: „Spot LX0FOUR 70161500 Hz CW vyřazen … (bez pravidla)“ (2026-09-10)

Rešerše k Inbox požadavku „Station Agent – rešerše: ověření vyřazení spotu
LX0FOUR 70161500 Hz CW při živém běhu v PowerShellu“. Produkční kód, testy ani
`config.yaml` nebyly změněny; pokusné soubory (`.lx0four_probe_tmp/`) byly po
ověření odstraněny.

## Závěr

**Nejde o chybu přepočtu kHz→Hz. Spot je skutečně na 70,1615 MHz (pásmo 4 m)
a tabulka alokací v `station_agent/bandplan.py` pásmo 4 m nezná** – zahrnuje
pouze 160 m–6 m. Hláška je tedy správným důsledkem záměrně omezené tabulky
`BAND_LIMITS_HZ`, nikoli poškozeného vstupu.

## Doložení

### 1. Konkrétní vstupní spot (databáze předchozího živého běhu)

`station_agent.sqlite3` z běhu 2026-09-10 10:37–10:50 UTC obsahoval přesně
jeden záznam LX0FOUR:

| id | callsign | freq_hz | mode | band | ts (UTC) | source | snr_db | comment | spotter |
|---|---|---|---|---|---|---|---|---|---|
| 4411059 | LX0FOUR | 70161500 | CW | unknown | 2026-09-10 10:40 | rbn | 15.0 | `10 WPM  BEACON` | DK2GOX-# |

Zdrojem je tedy RBN skimmer DK2GOX (ne DX Cluster) a komentář `BEACON`
odpovídá tomu, že LX0FOUR je majákový volací znak (sufix „FOUR“ = 4 m).
Ve stejné DB byly se stejným `band=unknown` i DB0THE 144 404 050 Hz CW
(RBN, 2 m maják) a W4NAS 144 950 000 Hz (PSKReporter) – tatáž třída.

### 2. Místo přepočtu

- RBN: `station_agent/adapters/rbn.py:44`
  `freq_hz = int(round(float(match.group("freq_khz")) * 1000))`
- DX Cluster: `station_agent/adapters/dx_cluster.py:77` – identický výraz.

RBN vysílá kmitočet v kHz; řádek pro tento spot má tvar
`DX de DK2GOX-#:   70161.5  LX0FOUR  CW  15 dB  10 WPM  BEACON  1040Z`
a přepočet `70161.5 kHz × 1000 = 70 161 500 Hz` je správný.

Alternativa „7016.15 kHz“ byla vyloučena reprodukcí: stejným parserem dává
`7 016 150 Hz` (jiné číslo než v logu), `band=40m` a validace projde jako
`iaru-r1-2020-40m-7000-7040-cw`. Hodnotu `70161500` lze získat jedině ze
vstupu `70161.5` kHz.

### 3. Použitá tabulka alokací a místo vyřazení

- `station_agent/bandplan.py:16-30` `BAND_LIMITS_HZ` – pásma 160m, 80m, 60m,
  40m, 30m, 20m, 17m, 15m, 12m, 10m, 6m; horní hranice 54 000 000 Hz.
- `bandplan.py:130-135` `freq_to_band()` → pro 70 161 500 Hz vrací `None`.
- `bandplan.py:102-104` `validate_mode_frequency()` → při `band is None`
  vrací `valid=False`, `rule_id=None`, důvod „kmitočet je mimo podporovanou
  amatérskou alokaci“; `MODE_FREQUENCY_RULES` (řádky 67-88) se vůbec
  neprohledává, proto v logu „(bez pravidla)“.
- `station_agent/aggregator.py:313-324` `Aggregator.build_candidates()` –
  loguje `INFO "Spot %s %s Hz %s vyřazen: %s (%s)"`.

Offline reprodukce celého řetězce (rekonstruovaný RBN řádek →
`parse_rbn_line` → `Spot` → `build_candidates`) vypsala doslova
`INFO station_agent.aggregator: Spot LX0FOUR 70161500 Hz CW vyřazen: kmitočet je
mimo podporovanou amatérskou alokaci (bez pravidla)` a vrátila prázdný seznam
kandidátů.

### 4. Živý běh (2026-09-10, ~13:31 místního času)

- Plný `python -m station_agent --config config.yaml -v` (stejný config jako
  `start_station_agent.bat`, rig live, všechny zdroje živé). Hned první
  `refresh_candidates()` vypsal stejnou hlášku pro spoty PSKReporteru mimo
  tabulku: `SP9GL 144174806 Hz FT8`, `PA3FWU 144175903 Hz FT8`,
  `DL4SKY 144176241 Hz FT8` (2 m) a `IU2VUD 2400041817 Hz OTHER_DIGITAL`
  (13 cm). Hláška se pro tentýž spot opakuje při každém polling cyklu
  (`--poll-interval`, výchozí 10 s), protože `build_candidates()` čte vždy
  celé okno `spot_max_age_minutes` z DB.
- Souběžně běžela sonda nad skutečným `RBNAdapter` (`LiveTelnetSpotSource`,
  `telnet.reversebeacon.net:7000`, login callsignem z configu) s hookem na
  `parse_line`, který ukládá syrové řádky. Za 240 s přijala 502 řádků /
  497 spotů; LX0FOUR v tomto okně žádný skimmer nespotoval (maják je v DB
  z 10:40Z spotován jediným skimmerem DK2GOX). Jediný spot mimo
  `BAND_LIMITS_HZ` byl syrový řádek
  `DX de DJ3AK-#: 144404.05  DB0THE  CW  6 dB  12 WPM  DX  1134Z`
  → `DB0THE 144404050 Hz CW band=unknown`; tentýž spot poté běžící agent
  logoval jako `Spot DB0THE 144404050 Hz CW vyřazen: kmitočet je mimo
  podporovanou amatérskou alokaci (bez pravidla)` (13:35:19 a dále v každém
  cyklu, 5× za 45 s). RBN tedy prokazatelně posílá kmitočet v kHz
  s desetinnou částí (`144404.05`, u LX0FOUR `70161.5`) a přepočet ×1000 je
  správný; v celém běhu (245 řádků logu, 101 vyřazení) nebyl žádný
  WARNING/ERROR a všech pět vyřazených stanic leželo mimo 160 m–6 m.
- Druhá, delší sonda (`live_rbn_probe2.log`, 540 s) nad týmž `RBNAdapter`
  přijala 954 řádků / 944 spotů; LX0FOUR se v tomto okně opět nevyskytl a
  tentokrát nebyl mimo `BAND_LIMITS_HZ` žádný spot (nulový výskyt VHF/UHF
  majáků v tomto vzorku). Obě sondy skončily stejnou chybou přenosu
  (`WinError 10038`, socket knihovny `telnet.reversebeacon.net:7000`
  ukončil spojení po ~225–525 s), na kterou navazuje vestavěné opakování
  připojení v `RBNAdapter`; nesouvisí s validací kmitočtu a je mimo rozsah
  tohoto úkolu.

## Doporučená oprava (kód v této iteraci nezměněn)

1. **Tabulka alokací**: rozhodnout, zda Station Agent má VHF/UHF podporovat.
   Pokud ano, doplnit do `BAND_LIMITS_HZ`/`SUPPORTED_BANDS` a
   `MODE_FREQUENCY_RULES` pásma 4 m (70,000–70,500 MHz, IARU R1; národní
   výjimky) a 2 m (144–146 MHz) včetně `source_revision` VHF bandplanu
   IARU R1 a propagačního modelu (`app_state` propagation snapshot zná jen
   160m–6m). Bez toho spoty zůstanou správně vyřazené.
2. **Šum v logu**: spoty, jejichž `band` je `unknown` (tj. `freq_to_band()`
   vrátí `None`), vůbec nemohou projít filtrem `config.bands`
   (`app_state.py:93-96`). V `build_candidates()` je proto vhodné je vyřadit
   tiše nebo na úrovni `DEBUG` (případně logovat jen jednou na spot, ne v
   každém cyklu) a `INFO` ponechat pro skutečné konflikty mód × segment
   (`rule_id` je vyplněný). Alternativně `PolledSource`/adaptéry mohou spoty
   mimo `BAND_LIMITS_HZ` neukládat do DB.
3. **Přepočet kHz→Hz neměnit** – je správný pro RBN i DX Cluster; jednotky
   vstupu (kHz) potvrzeny živými daty.

## Vedlejší pozorování mimo rozsah (neopraveno)

Při ukončení živého běhu přes `POST /api/shutdown` zalogoval server
`ERROR station_agent.web.server: Vyčištění databáze při ukončení selhalo …
Cannot operate on a closed database`. Příčina je souběh: `_perform_shutdown()`
(`web/server.py:146-163`) nejprve zavolá `http_server.shutdown()`, tím se v
`cli.main()` vrátí `serve_forever()` a jeho `finally` (`cli.py:426-431`)
zavře DB; teprve poté se shutdown vlákno dostane k `db.clear_all_data()`
na už zavřeném spojení. `clear_all_data()` sám nic nezměnil (transakce se
nerozběhla), proces skončil s návratovým kódem 0. Netýká se validace
kmitočtu; patří do samostatného požadavku.

## Omezení

- Test suite podle runtime contractu spouští a vyhodnocuje výhradně
  ai-orchestrator.
- Spuštění přes `powershell -Command` bylo v této relaci zamítnuto oprávněním;
  živý běh proto proběhl přímo interpretem `python` (`python -m station_agent`)
  se stejným `config.yaml`, jaký používá `start_station_agent.bat`.
