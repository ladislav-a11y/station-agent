# Diagnostika aktuálního Windows checkoutu (2026-09-08)

Tento evidenční záznam vznikl živým spuštěním `start_station_agent.bat`.
Produkční kód ani lokální konfigurace nebyly změněny. Citlivé hodnoty nejsou
uvedeny.

## Checkout a konfigurace

- HEAD při diagnostice byl `d3703c9`; jedinou dirty cestou už před ní byl
  `config.example.yaml`. Tato změna obsahovala lokální hodnoty včetně
  přihlašovacího údaje. Po diagnostice byla distribuovaná ukázková sekce
  obnovena na neaktivní prázdné hodnoty, aniž se přepsal ignorovaný
  `config.yaml`. Protože se údaj objevil v pracovním stromu a diagnostickém
  vstupu, zůstává doporučena jeho rotace mimo tento repozitář.
- Batch explicitně předal absolutní cestu `config.yaml`. Runtime objekt
  potvrdil hodnoty z tohoto ignorovaného souboru: live rig, localhost GUI,
  sedm nakonfigurovaných zdrojů a zapnutý read-only Log4OM2 lookup. Příčinou
  hlášených jevů tedy není nenačtený config ani fallback na example soubor.

## DX Cluster, RBN a backoff

- Bezprostředně po startu byly telnetové zdroje v GUI `pending`. To je
  očekávaný startup grace stav `LiveTelnetSpotSource`, nikoli důkaz chyby
  endpointu ani HTTP backoffu.
- Po ustálení byly všechny čtyři DX Cluster zdroje i RBN `ok`. Windows
  současně evidoval pět samostatných navázaných TCP relací procesu na
  konfigurované porty 7373/7300/7000. Primární cluster dodal spoty, RBN
  desítky spotů; tři alternativní clustery byly připojené, ale v pozorovaném
  intervalu neměly nový rozpoznaný spot. To je rozdíl v aktivitě serverů,
  ne společný pád klienta.
- Každý telnet adaptér má vlastní socket, vlákno a exponenciální reconnect
  5, 10, 20 až 300 sekund; úspěšné spojení jej resetuje na 5 sekund.
  Aktuální GUI však nezobrazuje zbývající interní telnet reconnect backoff.
  Pole `backoff_remaining_seconds` a text `backoff (429)` patří
  `PolledSource` (typicky HTTP 429), zatímco telnet reconnect je během grace
  vidět jen jako `pending` a později jako obecný `error`. Navazující karta má
  zpřístupnit strukturovaný telnet stav (connected, poslední chyba, další
  pokus) a v GUI jej odlišit od HTTP 429.

## Tok locatoru

- Živý PSKReporter fetch skončil `ok` a cache obsahovala 1514 spotů.
  `/api/candidates` v pozorovaném okamžiku vrátil 394 kandidátů, z nich 393
  s locatorem. Ukázkové kandidáty měly jako jediný potvrzující zdroj
  `pskreporter` a normalizovaný locator.
- Rozhraní je souvislé: parser nastaví `Spot.locator`, databázový sloupec
  `spots.locator` jej uchová, `group_spots_into_candidates()` vybere nejnovější
  dostupnou hodnotu do `Candidate.locator`, `candidate_to_dict()` ji
  serializuje a `web/static/app.js` ji vykreslí (neznámou hodnotu jako `?`).
  Hlášenou hromadnou ztrátu locatoru se v tomto checkoutu nepodařilo
  reprodukovat. Jeden kandidát bez locatoru je přípustný stav zdrojových dat.

## Read-only Log4OM2 lookup na UNC cestě

- GUI opakovaně hlásilo `configured=true`, `filter_enabled=true`,
  `verified=false`, `status=login_error`. Kandidáti zůstali bezpečně
  zobrazeni; chyba externí historie nebyla zaměněna za ověřenou absenci.
- Anonymizované zopakování stejného Windows `WNetAddConnection2W` vrátilo
  kód **1219**: k témuž SMB serveru už existuje relace pod jinou identitou
  a Windows nepovolí souběžné připojení pod druhou identitou. Potvrzenou
  příčinou je lokální SMB session/authentication conflict. Běh nedošel
  k `exists`/`isfile`/read-access ani k read-only SQLite URI, takže nepotvrdil
  chybu cesty, oprávnění souboru, schématu ani SQLite.
- Navazující oprava má zachovat redakci tajných hodnot, ale bezpečně mapovat
  Windows kód 1219 na konkrétní instrukci k odstranění konfliktu existující
  relace. Aplikace nemá automaticky odpojovat cizí SMB relace. Po vyřešení
  relace je nutný nový read-only pokus, který odděleně ověří cestu, oprávnění,
  SQLite otevření a očekávané schéma.

## Omezení

- Pozorovací okno neobsahovalo skutečný telnet výpadek, takže potvrdilo
  paralelní stabilní relace a implementované časování, nikoli živý celý
  reconnect cyklus konkrétního serveru.
- Nebyla měněna SMB relace ani oprávnění uživatele. To je záměrné: jejich
  změna by překročila read-only diagnostiku a mohla ovlivnit jiné aplikace.
- Test suite je podle runtime contractu výhradně auditní evidence
  ai-orchestratoru a agent ji nespouštěl.
