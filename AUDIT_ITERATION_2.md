# Nezávislý audit — iterace 2/10

Audit byl proveden samostatným read-only agentem 2026-08-28 po implementaci
historie QSO, předvoleb a band-opening notifikací. Testy během auditu nebyly
spouštěny.

## Nálezy a vypořádání

1. Stav deduplikace a hodinového limitu byl pouze v RAM. Opraveno obnovou
   trackeru z perzistentní tabulky `band_openings` při startu `AppState`.
2. QSO endpoint důvěřoval klientskému bearingu a nedostatečně validoval
   čísla. Opraveno: vyžaduje konečnou frekvenci, podporovaný mód/pásmo a
   přesnou shodu s aktuálním kandidátem; bearing přebírá ze serverového
   modelu kandidáta.
3. `dx_cluster.py` obsahoval mojibake. České komentáře a docstringy byly
   opraveny na UTF-8; kontrola diffu nehlásí whitespace chyby.
4. Band activity závisela na filtrech GUI. Opraveno: notifikace i
   propagation skóre se odvozují z úplné sady kandidátů a GUI filtr se
   aplikuje až na výsledný seznam.

Tvrdé invarianty AGENTS.md audit neshledal porušené: nebyl přidán obecný
rig příkaz, ovládání rotoru ani automatické potvrzení externího deníku;
example konfigurace zůstává v mock režimu a web zůstává omezen na loopback.

Finální test suite spouští a vyhodnocuje výhradně orchestrátor.
