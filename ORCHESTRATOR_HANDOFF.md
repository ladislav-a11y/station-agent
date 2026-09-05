# Předání k ověření a nezávislému auditu

Tento dokument předává dokončené změny Station Agenta řídicímu
`ai-orchestratoru`. Je to implementační evidence, nikoli audit ani verdikt.
Spuštění a vyhodnocení testů, živé ověření v PowerShellu a GUI a rozhodnutí
`accepted`/`rejected` náleží výhradně `ai-orchestratoru` a výsledek musí být
uložen do Trella.

## Předávaný stav

- Výchozí bod posledního evidovaného předání: `926a615`.
- Aktuální implementační HEAD při vytvoření předání:
  `4cc07eb140d7b48f1695bcf50a1f82ca9c385c78`.
- Pracovní strom byl před vytvořením tohoto dokumentu čistý.
- Rozsah `926a615..4cc07eb` zahrnuje evidenční dokumentaci, obnovu a rozšíření
  geodatové cesty (offline prefix/volitelný QRZ fallback, bearing a vzdálenost),
  zobrazení lokátoru v GUI, odolnější čtení stavu riggu a cílené regresní testy.
- Controller finalization už pro jednotlivé implementační změny vytvořil a
  odeslal commity. Ověření existujícího HEAD, statusu, diffu a remote stavu je
  auditní evidence; samo nevyžaduje nový implementační commit.

## Evidence připravená pro orchestrátor

1. Datový řetězec je pokryt od zdroje přes agregaci a serializaci až po GUI:
   `tests/test_station_geodata_regression.py` obsahuje sedm scénářů pro známé
   i neznámé geodata, nejdelší prefix, cache, API payload a vykreslení GUI.
2. `station_agent/web/static/index.html` obsahuje sloupec `Lokátor` a
   `station_agent/web/static/app.js` vykresluje `candidate.locator` nebo `?`;
   oba `colspan` odpovídají devíti sloupcům.
3. Bezpečnostní hranice Station Agenta se rozsahem nemění: výchozí example
   konfigurace zůstává v mock režimu, web zůstává loopback-only, rig API je
   uzavřené, bearing se pouze počítá a Log4OM2 zůstává pouze explicitní
   operátorský prefill.
4. Agent testovací příkaz nespustil a nevydává auditní závěr. Výsledek z minulé
   iterace nebyl dodán.

## Kroky vyhrazené ai-orchestratoru

Orchestrátor má po své kontrole identity projektu a repository allowlistu:

1. ověřit aktuálnost finalization proof proti HEAD a vzdálenému commitu;
2. provést strojově vyžadované kontroly v pořadí syntaxe, cílené testy,
   `git --no-pager diff`, `git --no-pager diff --check`, kompletní testy
   (`python -m pytest -q`);
3. spustit Station Agenta v PowerShellu s bezpečnou lokální konfigurací a
   ověřit, že proces i API naběhnou bez neošetřené chyby;
4. v GUI na loopback adrese ověřit známý lokátor, zemi, bearing a vzdálenost
   i explicitní značky neznámých hodnot a zachované ovládací prvky;
5. provést nezávislý audit, uložit konkrétní evidence do Trella a jako jediná
   oprávněná komponenta vydat `accepted` nebo `rejected`.

Při neúspěchu se má do Trella uložit nejnovější konkrétní příčina včetně
selhávajícího kroku. Dokument nesmí být interpretován jako náhrada testovacího
výstupu, živého ověření ani nezávislého auditu.
