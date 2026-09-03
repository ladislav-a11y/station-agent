# Nezávislý audit — iterace 3/10

Read-only audit aktuálního pracovního stromu provedl samostatný agent
2026-08-28. V souladu se zadáním nespouštěl testy a nic neupravoval.

## Výsledek

Nebyl nalezen žádný blokující problém pro historii QSO, bearing,
předvolby, band-opening notifikace ani opravu telnet odpojení.

- QSO endpoint validuje konečnou kladnou frekvenci, podporovaný mód a
  pásmo a přesnou shodu s aktuálním serverovým kandidátem. Bearing se
  nepřebírá od klienta, ale z modelu kandidáta. Uložení je pouze explicitní
  lokální akce operátora.
- Předvolby jsou propojené od konfigurace přes status API až do GUI.
- Notifikace používají přechodovou deduplikaci, cooldown, globální klouzavý
  hodinový limit a obnovu relevantního stavu z SQLite po restartu. Aktivita
  se počítá před aplikací GUI filtrů.
- Telnet klient parsuje úplné řádky ihned a zbytek bufferu při čistém EOF.
  Lokální socket fixture nyní ukončuje zapisovací polovinu spojení před
  close, takže na Windows nemůže RST předběhnout již odeslaný poslední spot;
  EOF/error/reconnect produkční větev zůstává skutečně otestovaná.
- Tvrdé bezpečnostní invarianty z AGENTS.md zůstávají zachované a
  `git diff --check` nehlásil chybu.

## Nález a vypořádání

Audit označil jako nízké riziko pevné načtení pouze 1000 předchozích
notifikací: uživatelská konfigurace `max_per_hour` vyšší než 1000 by po
restartu nemusela obnovit celý hodinový limit. Opraveno načtením alespoň
`max_per_hour` nejnovějších záznamů (současně zůstává rezerva 1000 pro
cooldown jednotlivých pásem).

Finální test suite spouští a vyhodnocuje výhradně orchestrátor.
