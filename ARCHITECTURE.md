# Architektura

Cíl: čistá modulární architektura, kde je snadné přidat nový zdroj spotů
(adaptér) nebo nový typ riggu, aniž by se sahalo do zbytku systému, a kde
je bezpečnostně kritický kód (PTT, anténní rotátor, auto-log) fyzicky nemožné omylem
zapnout.

```
station_agent/
├── config.py         # načtení + validace config.yaml -> dataclasses
├── models.py          # Spot, Candidate, ScoreResult, RigState, ...
├── db.py               # SQLite: spoty, worked-log cache, historie ladění
├── dxcc.py              # callsign -> DXCC entita (prefix tabulka, souřadnice)
├── bearing.py            # Maidenhead <-> lat/lon, great-circle bearing/distance
├── scoring.py             # transparentní scoring 0-100 s rozpisem důvodů
├── aggregator.py           # slučuje spoty z adaptérů do kandidátů
├── autotune.py              # rozhodovací logika AUTO TUNE / HOLD
├── log4om.py                 # sestavení a odeslání PREFILL (nikdy auto-save)
├── adapters/
│   ├── base.py                # SpotSource ABC
│   ├── mock.py                  # offline testovací zdroj (plně funkční)
│   ├── telnet_source.py            # sdílený živý telnet klient pro DX Cluster/RBN
│   ├── dx_cluster.py             # parser řádků + živý telnet fetch() (funkční)
│   ├── rbn.py                     # parser řádků + živý telnet fetch() (funkční)
│   ├── pskreporter.py              # parser XML + živý HTTP fetch() (funkční)
│   └── qrz.py                       # QRZ.com XML lookup -- volitelný síťový DXCC/země fallback (ne SpotSource)
├── rig/
│   ├── base.py                     # RigControl ABC (BEZ jakékoli PTT metody)
│   ├── mock_rig.py                   # in-memory mock rig
│   └── rigctld.py                     # reálný rigctld TCP klient (freq/mode only)
├── web/
│   ├── server.py                       # http.server vázaný na 127.0.0.1
│   └── static/                          # index.html, app.js, style.css
└── cli.py                                # entrypoint, drátování všeho dohromady
```

## Datový tok

```
Adaptéry (DX Cluster / RBN / PSKReporter / Mock)
        │  Spot(callsign, freq_hz, mode, band, ts, source, snr?)
        ▼
   Aggregator  ── seskupí spoty stejné stanice/pásma do jednoho Candidate
        │           a sesbírá potvrzující zdroje (confirming_sources)
        ▼
     DXCC lookup (dxcc.py) ── doplní zemi/kontinent/souřadnice entity
        │       (offline PREFIX_TABLE; když selže, volitelný síťový
        │        fallback adapters/qrz.py -- viz README "DXCC/země
        │        fallback přes QRZ.com")
        ▼
     Bearing (bearing.py) ── spočítá směr a vzdálenost z QTH
        ▼
     Scoring (scoring.py) ── 0-100 + rozpis důvodů (ScoreReason[])
        ▼
     SQLite (db.py) ── perzistence spotů a historie pro "needed DXCC"
        ▼
  ┌─────┴─────────────────────────────┐
  ▼                                    ▼
Web GUI (read-only zobrazení          AutoTuneEngine (autotune.py)
kandidátů + filtry + ovládání         -- pokud enabled a ne HOLD a splněny
AUTO TUNE/HOLD parametrů)             min_score/hold_time/score_delta,
                                       zavolá RigControl.set_frequency/
                                       set_mode (NIKDY set_ptt -- neexistuje)
                                            │
                                            ▼
                                    rigctld (mock nebo live) -> IC-7300
```

Log4OM2 bridge (`log4om.py`) je odbočka z Candidate -> `build_prefill()` ->
volitelně `send_prefill()` (UDP), naprosto odděleně od auto-tune smyčky;
nikdy nezapisuje do deníku sama.

## Proč adaptéry mají oddělené "parse" a "fetch" vrstvy

U DX Clusteru, RBN a PSKReporteru je **parsování formátu** čistá funkce
(text/XML dovnitř, `Spot` ven) — tu lze plně otestovat na fixture datech
bez internetu, a je proto plně implementovaná a testovaná. **Získání dat
z živé služby** (telnet spojení, HTTP dotaz) je taky plně implementované
a živé (`fetch()` u všech tří adaptérů skutečně mluví po síti -- viz
`telnet_source.py` pro DX Cluster/RBN a `pskreporter.py` pro HTTP), ale
testuje se výhradně proti skutečnému lokálnímu testovacímu socketu/HTTP
serveru (`tests/test_telnet_source.py`, `tests/test_adapters_live.py`),
nikdy proti reálnému vzdálenému serveru -- viz AGENTS.md "Testy běží bez
internetu". Dokud se DX Cluster/RBN adaptér poprvé skutečně nepřipojí a
nenaparsuje aspoň jeden reálný spot, `fetch()` hlásí `SourceNotReadyError`
(GUI stav "pending") místo toho, aby si "vymýšlel" data, která vypadají
jako reálná odpověď externí služby (viz AGENTS.md pravidlo 6).

## Rozšiřování o nový zdroj spotů

1. Vytvoř `station_agent/adapters/muj_zdroj.py`, implementuj `SpotSource`
   (`fetch() -> list[Spot]`).
2. Pokud je nutné síťové připojení, které nejde ověřit v testovacím
   prostředí, rozděl na `parse_...()` (testovatelné čistě funkcí) a
   `fetch()`/`fetch_live()` (může zůstat `NotImplementedError` do doby, než
   je reálně ověřeno proti živé službě).
3. Zaregistruj adaptér v `cli.py` podle configu (`sources.muj_zdroj.enabled`).
4. Přidej testy parseru do `tests/test_adapters_parsing.py`.

## Bezpečnostní hranice v architektuře

- `rig/base.py` definuje jediné rozhraní pro ovládání riggu a **fyzicky
  neobsahuje** žádnou PTT metodu — nelze ji tedy zavolat ani omylem přes
  rozhraní, protože neexistuje.
- `autotune.py` volá výhradně `set_frequency`/`set_mode`.
- `tests/test_rig_safety.py` prohledává celý zdrojový strom a selže, pokud
  se kdekoli v `station_agent/` objeví byť jen zmínka o PTT.
- Anténní rotátor nemá modul vůbec — `bearing.py` pouze vrací číslo (stupně)
  pro zobrazení v GUI.
