"""One-shot: doczytaj ostateczne wyniki z ostateczne wyniki.xlsx i zamknij konkurs.

Co robi:
- dodaje brakujący 11. tydzień 25.05-29.05 (ceny + pozycje I rok + canonical_values 29 grup),
- uzupełnia canonical_values w istniejącym tygodniu 19.05-22.05 (II rok),
- usuwa pending_week,
- ustawia ``competition_ended = True`` + dane finalnego rankingu.

Pozycje II roku dla 19.05 i 25.05 nie są w arkuszach obstawień (Excel ma je tylko
w "wynikach" po rozliczeniu - bez znaku long/short) - zostają puste, bo ranking
i wykresy używają ``canonical_values`` jako autorytatywnej wartości portfela.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

INST_MAP = {
    "^SPX": "SPX",
    "XAUUSD": "XAUUSD",
    "10YUSY.B": "BOND10Y",
    "EURUSD": "EURUSD",
}
INSTRUMENTS = ["SPX", "XAUUSD", "BOND10Y", "EURUSD"]

# Brakujący tydzień: 25.05-29.05 (poniedziałek = 2026-05-25)
NEW_WEEK_START = "2026-05-25"
NEW_WEEK_LABEL = "25.05 – 29.05"
PREV_WEEK_START = "2026-05-19"


def _norm_week_label(label: str) -> str:
    return re.sub(r"\s*-\s*", " – ", label.strip())


def _is_new_week(label: str) -> bool:
    s = label.replace(" ", "")
    return s.startswith("25.05")


def _is_prev_week(label: str) -> bool:
    s = label.replace(" ", "")
    return s.startswith("19.05") or s.startswith("19.05-22.05")


def parse_prices_for_week(ws, target: str) -> dict | None:
    """Wyciągnij open/close dla tygodnia z arkusza cen."""
    rows = list(ws.iter_rows(values_only=True))
    for i, row in enumerate(rows):
        if isinstance(row[0], str) and target.replace(" ", "") in row[0].replace(" ", ""):
            out = {"open": {}, "close": {}}
            for j in range(1, 8):
                if i + j >= len(rows):
                    break
                r = rows[i + j]
                if isinstance(r[0], str) and r[0] in INST_MAP:
                    inst = INST_MAP[r[0]]
                    try:
                        out["open"][inst] = float(r[1]) if r[1] is not None else None
                        out["close"][inst] = float(r[2]) if r[2] is not None else None
                    except (TypeError, ValueError):
                        pass
            return out
    return None


def parse_positions_year1_for_new_week(ws) -> dict:
    """Pozycje I roku na 25.05-29.05.

    UWAGA: w arkuszu te pozycje są błędnie zaetykietowane jako '19.05 - 22.05'
    (drugie wystąpienie pod koniec arkusza). Bierzemy DRUGIE wystąpienie tej etykiety.
    """
    rows = list(ws.iter_rows(values_only=True))
    week_starts = []
    for i, row in enumerate(rows):
        if row[0] == "Tydzień" and isinstance(row[1], str) and "19.05" in row[1].replace(" ", ""):
            week_starts.append(i)
    if len(week_starts) < 2:
        return {}

    start = week_starts[-1]
    out: dict = {}
    header_seen = False
    inst_cols: list = []
    for j in range(start + 1, len(rows)):
        r = rows[j]
        if r[0] == "Tydzień":
            break
        if r[0] == "Numer Grupy":
            for ci, cell in enumerate(r):
                if isinstance(cell, str) and cell in INST_MAP:
                    inst_cols.append((ci, INST_MAP[cell]))
            header_seen = True
            continue
        if not header_seen:
            continue
        gname = r[0]
        if not (isinstance(gname, str) and gname.startswith("Grupa ")):
            continue
        gname = gname.strip()
        pos = {i: 0.0 for i in INSTRUMENTS}
        for ci, inst_key in inst_cols:
            v = r[ci]
            if v is None or v == "":
                continue
            if isinstance(v, str):
                v = v.replace(",", ".").replace("+", "").strip()
            try:
                pos[inst_key] = float(v)
            except (TypeError, ValueError):
                pos[inst_key] = 0.0
        out[gname] = pos
    return out


def parse_canonical_from_wyniki(ws, week_label_substr: str) -> dict:
    """Wyciąga {grupa: stan_portfela} dla pierwszego wystąpienia tygodnia."""
    rows = list(ws.iter_rows(values_only=True))
    target = week_label_substr.replace(" ", "")
    in_week = False
    stan_col = None
    out: dict = {}
    for r in rows:
        if r[0] == "Tydzień":
            in_week = isinstance(r[1], str) and target in r[1].replace(" ", "")
            stan_col = None
            continue
        if not in_week:
            continue
        if r[0] == "Numer Grupy":
            for ci, cell in enumerate(r):
                if isinstance(cell, str) and "stan portfela" in cell.lower():
                    stan_col = ci
                    break
            continue
        if stan_col is None:
            continue
        gname = r[0]
        if not (isinstance(gname, str) and gname.startswith("Grupa ")):
            continue
        try:
            out[gname.strip()] = float(r[stan_col])
        except (TypeError, ValueError):
            continue
    return out


def parse_final_ranking(ws) -> list[dict]:
    """Wyciąga ranking wspólny: [{group, members, year, value, place}]."""
    out: list = []
    for row in ws.iter_rows(values_only=True):
        if not isinstance(row[0], str) or not row[0].startswith("Grupa "):
            continue
        members = [m.strip() for m in row[1:4] if m]
        try:
            year = int(row[4]) if row[4] else None
            value = float(row[5])
            place = int(row[6])
        except (TypeError, ValueError):
            continue
        out.append({
            "group": row[0].strip(),
            "members": members,
            "year": year,
            "value": value,
            "place": place,
        })
    out.sort(key=lambda x: x["place"])
    return out


def main() -> int:
    repo_dir = Path(__file__).parent
    xlsx_path = repo_dir.parent / "ostateczne wyniki.xlsx"
    data_path = repo_dir / "data.json"

    if not xlsx_path.exists():
        print(f"❌ Brak pliku Excel: {xlsx_path}")
        return 2
    if not data_path.exists():
        print(f"❌ Brak data.json: {data_path}")
        return 2

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    print(f"📂 Otwarto: {xlsx_path.name}")

    prices_new = parse_prices_for_week(wb["Ceny otwarcia i zamknięcia"], "25.05-29.05")
    if not prices_new or not prices_new["open"] or not prices_new["close"]:
        print("❌ Brak cen dla 25.05-29.05 w arkuszu cen.")
        return 3
    print(f"  ✓ ceny 25.05-29.05: open={prices_new['open']}, close={prices_new['close']}")

    pos_y1_new = parse_positions_year1_for_new_week(wb["I rok - obstawienia"])
    print(f"  ✓ pozycje I rok na 25.05: {len(pos_y1_new)} grup")

    canon_y1_new = parse_canonical_from_wyniki(wb["I rok - wyniki"], "25.05-29.05")
    canon_y2_new = parse_canonical_from_wyniki(wb["II rok wyniki"], "25.05-29.05")
    print(f"  ✓ canonical 25.05-29.05: y1={len(canon_y1_new)}, y2={len(canon_y2_new)}")

    canon_y2_prev = parse_canonical_from_wyniki(wb["II rok wyniki"], "19.05-22.05")
    print(f"  ✓ canonical 19.05-22.05 (y2): {len(canon_y2_prev)} grup")

    final_rank = parse_final_ranking(wb["Ranking wspólny"])
    print(f"  ✓ ranking finalny: {len(final_rank)} grup")
    print(f"     🥇 {final_rank[0]['group']} ({final_rank[0]['value']:.3f})")
    print(f"     🥈 {final_rank[1]['group']} ({final_rank[1]['value']:.3f})")
    print(f"     🥉 {final_rank[2]['group']} ({final_rank[2]['value']:.3f})")

    # backup
    backup = data_path.with_suffix(
        ".json.bak." + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    shutil.copy2(data_path, backup)
    print(f"💾 Backup: {backup.name}")

    with data_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # 1) uzupełnij 19.05-22.05 - canonical_values II roku
    found_prev = False
    for w in data["weeks"]:
        if w.get("week_start") == PREV_WEEK_START:
            found_prev = True
            cv = w.setdefault("canonical_values", {})
            added = 0
            for g, v in canon_y2_prev.items():
                if g not in cv:
                    cv[g] = v
                    added += 1
            print(f"  → 19.05-22.05: dodano {added} canonical (y2)")
            break
    if not found_prev:
        print("⚠️  Nie znaleziono 19.05-22.05 w data.json")

    # 2) dodaj nowy tydzień 25.05-29.05
    exists = any(w.get("week_start") == NEW_WEEK_START for w in data["weeks"])
    if exists:
        print("ℹ️  25.05-29.05 już istnieje - nadpisuję pola.")
        new_w = next(w for w in data["weeks"] if w.get("week_start") == NEW_WEEK_START)
    else:
        new_w = {
            "label": NEW_WEEK_LABEL,
            "week_start": NEW_WEEK_START,
            "completed": True,
            "prices": {"open": {}, "close": {}},
            "positions": {},
            "canonical_values": {},
        }
        data["weeks"].append(new_w)

    new_w["label"] = NEW_WEEK_LABEL
    new_w["completed"] = True
    new_w["prices"] = prices_new
    new_w["positions"] = pos_y1_new  # tylko I rok; II rok bez kierunku w arkuszu
    merged_canon = {}
    merged_canon.update(canon_y1_new)
    merged_canon.update(canon_y2_new)
    new_w["canonical_values"] = merged_canon
    print(f"  → 25.05-29.05: positions={len(pos_y1_new)}, canonical={len(merged_canon)}")

    # 3) zamknij konkurs - usuwamy pending_week
    if "pending_week" in data:
        del data["pending_week"]
        print("  → usunięto pending_week")

    data["competition_ended"] = True
    data["final_ranking"] = final_rank
    data["competition_end_date"] = "2026-05-29"
    print("  → competition_ended = True")

    # zapisz
    with data_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ Zapisano: {data_path}")
    print(f"📊 Tygodni: {len(data['weeks'])}, grup: {len(data['groups'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
