# Station Agent - Project Notes

## Prostředí
- OS: Windows 11
- Projekt: D:\orchestrator\station-agent
- Shell: PowerShell
- Python: 3.14.7

## Pravidla práce
- Vždy provádět jeden příkaz najednou.
- Před úpravou souboru vytvořit zálohu.
- Preferovat PowerShell úpravy přes List[string] před složitými one-linery.
- Neprovádět hromadné neověřené změny.
- Po každé změně ověřit výsledek.

## Známé problémy
### PowerShell a YAML
- Nevkládat YAML bloky přímo do PowerShell konzole.
- Nepoužívat složité replace příkazy s vloženými `n a escapovanými uvozovkami.
- Při úpravách YAML kontrolovat odsazení.

### Kódování
- Soubory ukládat jako UTF-8.
- Pozor na špatné zobrazení češtiny v PowerShell výpisu.

## DX Cluster
- Server: dxc.w3lpl.net
- Port: 7373
- Login: callsign
- Stanice: OK1RPL
- Jméno: Ladislav
- QTH: Pilsen
- Locator: JN69QR

## Aktuální stav
- TCP spojení DX Cluster ověřeno.
- Přihlášení OK1RPL funguje.
- DX spoty se načítají ručně.
- Probíhá dokončení integrace DXClusterAdapter.
