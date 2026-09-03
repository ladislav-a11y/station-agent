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
