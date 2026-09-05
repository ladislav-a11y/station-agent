# Station Agent — rekonstrukce a diagnostika

Stav zachycený před editací dne 2026-09-05: `git status --porcelain=v1`
byl prázdný a aktuální `HEAD` byl `804146d`. Nebyly tedy nalezeny žádné
rozpracované změny, které by bylo nutné převzít nebo chránit před přepsáním.
Tento dokument je evidence z repozitáře, nikoli náhrada stavu karet v Trellu
ani nezávislý auditní verdikt.

## Rekonstrukce souvisejících dokončených částí

Následující posloupnost je doložitelná historií Git a současnými soubory:

1. Live DX Cluster a RBN používají společný telnet zdroj; PSKReporter má
   oddělený polling, backoff a cache posledních platných dat. Stav adaptérů
   je vystaven v `/api/status`. Současná implementace je v
   `station_agent/adapters/` a integrační vrstva v `aggregator.py`.
2. Diagnóza chybějících prefixů byla zaznamenána v commitu `2d631b4` jako
   `DIAGNOSIS_DXCC_PREFIX_GAP.md`. Následná obecná QRZ fallback integrace
   vznikla v `f92076a`; současný tok je `callsign_to_dxcc()` a teprve při
   neúspěchu volitelný `QRZClient.lookup()`. Offline tabulka proto může
   bezpečně vrátit `None` a bez přihlašovacích údajů se externí výsledek
   nepředstírá.
3. Geolokace a bearing se dopočítávají pouze z doloženého Maidenhead
   lokátoru nebo referenčního bodu DXCC entity. Commit `4fc27bb` rozšířil
   podporu reálně přijímaných locatorů; žádný modul neovládá rotátor.
4. SQLite ukládá spoty, historii, worked-DXCC a GUI filtry. Oprava v
   `3c684af` zapnula incremental auto-vacuum pro souborovou databázi a
   průběžně vrací stránky uvolněné purgem, takže cache nemusí neomezeně
   zvětšovat soubor.
5. `Aggregator` slučuje evidence podle callsignu, pásma, frekvence, času a
   kompatibilního módu, doplňuje DXCC/bearing a předává kandidáty do
   `AppState`. HTTP server nabízí kandidáty, stav zdrojů, notifikace a
   historie; statické GUI tato API čte. Pozdější commity až po `804146d`
   zachovávají tento řetězec a doplňují zejména notifikace, propagation a
   explicitní Log4OM2 prefill.

Podrobné původní důkazy a omezení zůstávají v `LIVE_EVIDENCE.md`,
`DIAGNOSIS_DXCC_PREFIX_GAP.md`, `DATA_CONTRACT.md`, `AUDIT_MOCK_MODE.md` a
chronologických částech `PROJECT_NOTES.md`. Historické počty testů v těchto
dokumentech nejsou výsledkem této iterace.

## Diagnostika aktuálního zdrojového stavu

| Oblast | Skutečný stav v HEAD | Fail-closed hranice |
| --- | --- | --- |
| Prefixy/DXCC | `dxcc.py` obsahuje záměrně omezenou offline tabulku a longest-prefix match; `aggregator.py` podporuje volitelný obecný fallback. | Neznámá entita zůstane `None`; nepřidává se odhadovaná země. |
| Geolokace | `bearing.py` parsuje Maidenhead a pouze počítá směr/vzdálenost. | Bez platného lokátoru nebo DXCC bodu zůstane hodnota neznámá. |
| Cache/databáze | `db.py` purguje staré spoty a u souborové DB používá incremental vacuum; polling a QRZ mají vlastní časově omezené cache. | Cache není vydávána za čerstvá data; status obsahuje stáří/chybu/backoff. |
| Station Agent | `cli.py` sestavuje konfiguraci, DB, uzavřené rig rozhraní, zdroje, agregátor a lokální web. | Example config používá mock rig; live režim je explicitní uživatelská volba. |
| Agregátor/API | `aggregator.py`, `app_state.py` a `web/server.py` tvoří jeden datový tok až do JSON serializace. | Server přijímá pouze loopback host; neznámá data se v API nedopočítávají kosmeticky. |
| GUI | `web/static/app.js` čte kandidáty, status, notifikace a historie z API. | GUI je prezentační vrstva; nefalšuje chybějící zdrojová pole. |

## Závěr a otevřené externí podmínky

V aktuálním repozitáři nebyla nalezena další „připravená, ale nezapojená“
část v uvedeném řetězci. QRZ zůstává opt-in a bez reálných údajů nelze
ověřit produkční službu; rig live režim vyžaduje fyzické zařízení/rigctld;
Log4OM2 zůstává pouze operátorem vyvolaný prefill. Tyto podmínky nejsou
regresí zdrojového kódu a nesmějí být nahrazeny mock daty vydávanými za
živá.

Touto iterací nebyl změněn žádný produkční ani testovací soubor. Povinné
spuštění a vyhodnocení testů náleží ai-orchestratoru.
