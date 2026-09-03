# Nezávislý audit — iterace 4/10

Read-only audit aktuálního pracovního stromu provedl samostatný agent
2026-08-28. V souladu se zadáním nespouštěl testy a nic neupravoval.

## Výsledek

Pro body 2 (historie QSO, bearing a předvolby) a 3 (band-opening
notifikace s deduplikací a limity) nebyl nalezen žádný blokující problém.

- QSO lze uložit pouze explicitním POST požadavkem odpovídajícím aktuálnímu
  serverovému kandidátovi. Klientský bearing se ignoruje a ukládá se
  bearing vypočtený serverem. Historie je propojena přes SQLite, API a GUI.
- Předvolby jsou propojené od konfigurace přes status API do GUI.
- Notifikace počítají odlišné volací značky před aplikací GUI filtrů,
  deduplikují přechod do otevřeného stavu, respektují cooldown pro pásmo a
  globální klouzavý hodinový limit a obnovují relevantní stav z SQLite.
- Bezpečnostní invarianty z `AGENTS.md` zůstávají zachované. Example
  konfigurace používá mock rig, web vynucuje loopback a QSO historie nemění
  omezené chování Log4OM2.
- Live evidence pokrývá reálné adaptéry i výpočet bearingu v celém pipeline.
- `git diff --check` byl čistý a v evidovaném diffu nebyly nalezeny žádné
  dočasné ani záložní soubory.

## Nález a vypořádání

Audit našel nízkorizikový tautologický assert v testu výchozích předvoleb.
Byl zpřesněn tak, aby ověřoval pásma i módy proti podporovaným hodnotám.

Ignorované runtime artefakty (`station_agent.sqlite3`, cache Pythonu a
pytestu) nejsou součástí změn určených k odevzdání. Databáze obsahuje
lokální provozní data a nebyla mazána.

Finální test suite spouští a vyhodnocuje výhradně orchestrátor.
