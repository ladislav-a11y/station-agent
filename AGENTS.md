# AGENTS.md — pravidla pro vývoj/rozšiřování Station Agent

Tento soubor je určen jak lidem, tak AI agentům, kteří budou na projektu
dále pracovat. Cílem je, aby bezpečnostní invarianty přežily i budoucí
refaktoring.

Obecný manuální postup práce platný pro všechny projekty je v
`D:\orchestrator\AI_PROJECT_PROTOCOL.md`; tento soubor obsahuje pouze pravidla
specifická pro Station Agent.

## Tvrdá pravidla (nikdy neporušuj)

1. **Žádné PTT.** Nikdy nepřidávej žádnou funkci, metodu ani API endpoint,
   který by dokázal zapnout vysílání (PTT) na IC-7300 nebo jakémkoli jiném
   rigu. Platí i transitivně — např. "univerzální" příkazová metoda typu
   `send_raw_command(cmd: str)` na `RigControl` je zakázaná, protože by
   šla zneužít k obejití tohoto pravidla. `rig/base.py` smí nabízet pouze
   uzavřenou sadu metod pro čtení/nastavení frekvence a módu.
   Test `tests/test_rig_safety.py` prohledává `station_agent/` a selže,
   pokud se v kódu objeví byť jen řetězec "ptt" (case-insensitive). Pokud
   opravdu potřebuješ o PTT mluvit v dokumentaci mimo `station_agent/`,
   piš to tam, ne v balíčku samotném.
2. **Žádné ovládání anténního rotátoru.** Bearing se pouze počítá a zobrazuje
   (`bearing.py`). Nepřidávej modul, který by anténu fyzicky natáčel.
3. **Log4OM2 = jen prefill.** `log4om.py` smí sestavit a odeslat data pro
   předvyplnění řádku v deníku. Nikdy nepřidávej funkci, která by QSO
   automaticky uložila/potvrdila v deníku bez zásahu operátora.
4. **Hamlib mock je default.** `config.example.yaml` musí mít
   `rig.mode: mock`. Přepnutí na `live` je vždy explicitní volba
   uživatele v jeho vlastním `config.yaml`, nikdy ne v example souboru
   ani jako fallback v kódu.
5. **Web GUI jen na localhost.** `web.host` se nesmí dát nastavit na nic
   jiného než loopback adresu — `web/server.py` to musí vynucovat v kódu,
   ne se spoléhat jen na konfiguraci.
6. **Nefalšuj externí služby.** Adaptér pro živou službu (DX Cluster, RBN,
   PSKReporter, budoucí zdroje), který nebyl ověřen proti reálnému
   serveru, musí mít `fetch()`/`fetch_live()` implementované jako jasně
   označený `NotImplementedError` "pending" stub — ne mock data vydávaná
   za reálná. Parsovací funkce (text/XML -> `Spot`) naopak testuj naplno
   na fixture datech, protože to ověřitelné je.

## Styl a konvence

- Čistě standardní knihovna Pythonu (>=3.10) v `station_agent/`. Pokud
  přidáváš skutečně nutnou třetí stranu, přidej ji jako **volitelnou**
  (`pyproject.toml` `[project.optional-dependencies]`) a zajisti fallback,
  aby testy a základní běh fungovaly i bez ní.
- Testy pomocí `unittest` (kompatibilní i s `pytest` runnerem).
- Každý nový zdroj skóre v `scoring.py` musí vracet i lidsky čitelný důvod
  (`ScoreReason`), scoring musí zůstat transparentní — žádné "black box"
  váhy schované mimo config.
- Dataclasses pro datové modely (`models.py`), žádné holé dicty
  procházející napříč moduly.

## Než něco označíš za "hotové"

- Spusť `python -m unittest discover -s tests -v`.
- Pokud přidáváš nový adaptér nebo rig backend, přidej k němu test a
  aktualizuj tabulku stavu adaptérů v `README.md`.
- Pokud měníš cokoliv v `rig/`, `autotune.py` nebo `log4om.py`, znovu si
  přečti sekci "Tvrdá pravidla" výše a ověř, že `test_rig_safety.py`
  a `test_log4om.py` pořád procházejí.
