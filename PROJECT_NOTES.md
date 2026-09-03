# Station Agent - Project Notes

## Prostředí

* OS: Windows 11
* Projekt: D:\\orchestrator\\station-agent
* Shell: PowerShell
* Python: 3.14.7

## Známé problémy

### PowerShell a YAML

* Nevkládat YAML bloky přímo do PowerShell konzole.
* Nepoužívat složité replace příkazy s vloženými `n a escapovanými uvozovkami.
* Při úpravách YAML kontrolovat odsazení.

### Kódování

* Soubory ukládat jako UTF-8.
* Pozor na špatné zobrazení češtiny v PowerShell výpisu.

## DX Cluster

* Server: dxc.w3lpl.net
* Port: 7373
* Login: callsign
* Stanice: OK1RPL
* Jméno: Ladislav
* QTH: Pilsen
* Locator: JN69QR

## Aktuální stav

* TCP spojení DX Cluster ověřeno.
* Přihlášení OK1RPL funguje.
* DX spoty se načítají ručně.
* Probíhá dokončení integrace DXClusterAdapter.

\## DX Cluster integrace - dokončeno 25.08.2026



\- Připojení k dxc.w3lpl.net:7373 funkční.

\- Login OK1RPL funkční.

\- Automatické odeslání sh/dx po připojení.

\- Parser podporuje:

&#x20; - původní DXSpider formát "DX de CALL:"

&#x20; - aktuální W3LPL živý formát bez prefixu.

\- Spoty se převádí do interního modelu Spot.

\- Kompletní testy: 192 passed.

## Přepnutí na reálný provoz -- 03.09.2026

* Vyřízen Inbox požadavek "Station agent -- přepnutí na reálný režim".
* Lokální `config.yaml` (gitignored, mimo repozitář) přepnut na připravené
  a živě ověřené části (viz `LIVE_EVIDENCE.md`): `station.callsign: OK1RPL`,
  `station.qth_locator: JN69QR`, `rig.mode: live`, `sources.mock.enabled:
  false`, `sources.dx_cluster/rbn/pskreporter.enabled: true`.
* `log4om.enabled` zůstává `false` -- payload proti reálné instanci Log4OM2
  není ověřený (viz `AUDIT_MOCK_MODE.md` bod 3), tedy není "připravená
  část" ve smyslu Inbox požadavku.
* Alternativní DX Cluster uzly (`dx_cluster_hamserve/ea7jxh/m0mhx`) zůstávají
  vypnuté -- jde o volitelné náhrady primárního uzlu, ne o další povinný
  souběžný zdroj.
* Žádná změna kódu v `station_agent/` -- vše potřebné bylo už dřív hotové a
  živě ověřené, šlo jen o konfigurační přepnutí v uživatelově vlastním
  souboru.

## Live test v PowerShell -- 03.09.2026

* Vyřízen Inbox požadavek "Station agent -- live test v PowerShell" v
  rozsahu, který jde ověřit bez fyzicky připojeného IC-7300 (viz
  `LIVE_EVIDENCE.md` bod 6): `python -m station_agent --config config.yaml`
  s ostrým `config.yaml` (rig.mode live, dx_cluster/rbn/pskreporter
  enabled) skutečně naběhl, GUI i `/api/status`/`/api/candidates`
  odpověděly, chybějící rigctld se odbrzdil korektně (fail-open, ne pád).
* Nalezen a opraven reálný bug objevený jen díky živým datům:
  `bearing.py::maidenhead_to_latlon` odmítal validní 8/10znakové rozšířené
  Maidenhead locatory, které PSKReporter reálně posílá u části stanic --
  bearing se tak ztrácel u ~10 % živých kandidátů. Opraveno + regresní
  testy v `tests/test_bearing.py`.
* Fyzické připojení IC-7300 přes `rigctld` zůstává na uživateli -- v tomto
  prostředí není žádný rig k dispozici, jde o nutně manuální krok mimo
  dosah agenta.
