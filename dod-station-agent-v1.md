# Definition of Done — Station Agent v1 (první plně funkční verze)

## GUI
- [ ] Lokální webové GUI dostupné na `http://127.0.0.1:<port>` (výchozí `8765`)
- [ ] Server se váže výhradně na `127.0.0.1`/loopback — nelze nakonfigurovat na `0.0.0.0` ani jinou externí adresu

## Filtry módů
- [ ] Filtr módu SSB
- [ ] Filtr módu FT8
- [ ] Filtr módu FT4
- [ ] Filtr módu CW
- [ ] Filtr módu RTTY
- [ ] Filtr módu PSK31
- [ ] Filtr módu PSK63
- [ ] Filtr módu Other Digital

## Filtry pásem
- [ ] Filtr pásma 80 m
- [ ] Filtr pásma 40 m
- [ ] Filtr pásma 30 m
- [ ] Filtr pásma 20 m
- [ ] Filtr pásma 17 m
- [ ] Filtr pásma 15 m
- [ ] Filtr pásma 12 m
- [ ] Filtr pásma 10 m

## Zdroje spotů
- [ ] Alespoň jeden DX zdroj má skutečně funkční živé připojení (ne jen mock/fixture parser) — `fetch()` reálně stahuje a parsuje živá data
- [ ] Adaptér RBN je připravený (parser otestovaný na fixture datech) a explicitně označený jako pending, pokud živé připojení není ověřené
- [ ] Adaptér PSKReporter je připravený (parser otestovaný na fixture datech) a explicitně označený jako pending, pokud živé připojení není ověřené
- [ ] Agregace spotů z více zdrojů funguje (deduplikace/sloučení stejné stanice napříč zdroji)
- [ ] Žádný adaptér nevrací vymyšlená/nafingovaná data tvářící se jako reálná odpověď — pending zdroje vyhazují jasnou chybu (např. `NotImplementedError`), nikoli tichý mock výstup

## Skóre a zobrazované údaje
- [ ] Transparentní skóre 0–100 pro každého kandidáta
- [ ] Rozpis důvodů skóre (jednotlivé váhy/faktory viditelné v GUI, ne jen výsledné číslo)
- [ ] Zobrazen callsign
- [ ] Zobrazen DXCC / země
- [ ] Zobrazena frekvence
- [ ] Zobrazen mód
- [ ] Zobrazena čerstvost spotu (stáří/timestamp)
- [ ] Zobrazeny potvrzující zdroje (které adaptéry stanici viděly)
- [ ] Zobrazeno skóre
- [ ] Zobrazen bearing
- [ ] Bearing je počítán z konfigurovaného QTH uživatele (locator nebo lat/lon)

## AUTO TUNE
- [ ] AUTO TUNE respektuje konfigurovatelné minimální skóre (`min_score`)
- [ ] Funkce HOLD — když je aktivní, AUTO TUNE nikdy nepřeladí
- [ ] Minimální doba držení (`min_hold_seconds`) — rig zůstává na stanici alespoň tuto dobu, než se zvažuje přeladění
- [ ] Score delta (`min_score_delta`) — přeladění nastane jen pokud je nový kandidát o nakonfigurovaný rozdíl lepší než aktuální stanice

## Ovládání rigu (IC-7300)
- [ ] Rig je připojen výhradně jako klient k Hamlib/`rigctld` přes `localhost`/loopback a konfigurovatelný port
- [ ] Nikde v kódu není přímé otevírání COM/sériového portu k rádiu
- [ ] Změna frekvence probíhá výhradně přes Hamlib/`rigctld`
- [ ] Změna módu probíhá výhradně přes Hamlib/`rigctld`
- [ ] V celém zdrojovém stromu neexistuje žádná PTT ani TX funkce (ověřeno testem)
- [ ] Anténní rotátor není nikde programově ovládán — pouze se počítá a zobrazuje bearing

## Log4OM2
- [ ] Log4OM2 integrace pouze předvyplní záznam QSO (UDP prefill packet)
- [ ] Nikde neexistuje funkce, která by QSO automaticky uložila do deníku

## Provozní režimy
- [ ] Mock režim funguje bez rádia a bez internetu (mock zdroj spotů + mock rig)
- [ ] Live režim (`rig.mode: live`, živé zdroje) je ve výchozí konfiguraci vypnutý a vyžaduje explicitní volbu uživatele

## Perzistence
- [ ] Spoty/stav se ukládají do SQLite

## Konfigurace
- [ ] Konfigurovatelné QTH (locator nebo lat/lon)
- [ ] Konfigurovatelný `rigctld` host a port
- [ ] Konfigurovatelný seznam povolených módů
- [ ] Konfigurovatelný seznam povolených pásem
- [ ] Konfigurovatelné minimální skóre pro AUTO TUNE
- [ ] Konfigurovatelné zapnutí/vypnutí AUTO TUNE
- [ ] Konfigurovatelný HOLD
- [ ] Konfigurovatelná minimální doba držení (hold time)
- [ ] Konfigurovatelná score delta
- [ ] Konfigurovatelný Log4OM endpoint (host/port)

## Testy
- [ ] Existují bezpečnostní testy ověřující absenci PTT/TX funkcí v celém zdrojovém stromu
- [ ] Všechny testy (`pytest` / `python -m unittest discover -s tests`) projdou bez chyby
- [ ] Testy běží bez internetu a bez připojeného rádia (mock adaptéry)

## Spuštění a dokumentace
- [ ] Projekt se dá spustit jedním příkazem (např. `python -m station_agent --config config.yaml`)
- [ ] README obsahuje přesný krok-za-krokem návod pro Windows 11
- [ ] README obsahuje přesný návod na propojení s Log4OM2 (UDP prefill, port)
- [ ] README obsahuje přesný návod na zapojení IC-7300 přes Hamlib/`rigctld` (instalace Hamlib, spuštění `rigctld` pro IC-7300, host/port, ověření spojení)
