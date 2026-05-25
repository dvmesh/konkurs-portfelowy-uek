"""Skrypt one-shot: backfill data.json brakującymi tygodniami z lokalnego Excela.

Użycie:
    python backfill_from_excel.py "../Konkurs inwestycyjny (1).xlsx"

Strategia:
- czyta istniejący data.json (29 grup + N tygodni),
- parsuje wszystkie tygodnie z arkuszy "I rok - obstawienia", "II rok - obstawienia"
  oraz "Ceny otwarcia i zamknięcia",
- dodaje canonical_values z "I rok - wyniki" i "II rok wyniki",
- AKTUALIZUJE tylko brakujące tygodnie (nie nadpisuje istniejących pól),
- groups (skład, rok) zostawia bez zmian poza dodaniem grup M, N gdy ich brakuje.

Nie modyfikuje istniejącej zawartości — tylko uzupełnia luki.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl

# Windows console może być cp1250; wymuszamy utf-8 dla emoji.
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
EXPECTED_YEAR = 2026


def _parse_label_to_monday(label: str) -> str:
    """Wyciąga datę poniedziałku ze stringa typu '16.03 - 20.03'.

    Bierze PIERWSZĄ datę: jeśli to poniedziałek - bingo, jeśli niedziela
    (Excel labelował Wielkanoc) - poniedziałek = +1 dzień, w pozostałych
    przypadkach cofa się do najbliższego wcześniejszego poniedziałku.
    """
    parts = re.findall(r"(\d{1,2})\.(\d{1,2})", label)
    if not parts:
        raise ValueError(f"Nie mogę sparsować daty z label={label!r}")
    d, m = parts[0]
    first = date(EXPECTED_YEAR, int(m), int(d))
    wd = first.weekday()  # 0=Mon ... 6=Sun
    if wd == 0:
        monday = first
    elif wd == 6:
        monday = first + timedelta(days=1)
    else:
        monday = first - timedelta(days=wd)
    return monday.strftime("%Y-%m-%d")


def _normalize_label(label: str) -> str:
    """Standaryzuje label do formatu z myślnikiem en-dash."""
    return re.sub(r"\s*-\s*", " – ", label.strip())


def _parse_obstawienia(ws, year: int) -> dict:
    """Zwraca {week_start_iso: (label, {group: {INST: float}})} dla danego roku."""
    by_ws: dict[str, tuple] = {}
    current_label: str | None = None
    current_ws: str | None = None
    header_seen = False
    inst_cols: list[tuple[int, str]] = []  # (col_idx_0based, INST_KEY)

    for row in ws.iter_rows(values_only=True):
        # detect "Tydzień" header
        if row[0] == "Tydzień" and row[1]:
            current_label = _normalize_label(str(row[1]))
            current_ws = _parse_label_to_monday(current_label)
            by_ws.setdefault(current_ws, (current_label, {}))
            header_seen = False
            inst_cols = []
            continue
        # detect column header row: 'Numer Grupy' | 'Osoba 1' | ... | inst names
        if row[0] == "Numer Grupy":
            inst_cols = []
            for ci, cell in enumerate(row):
                if isinstance(cell, str) and cell in INST_MAP:
                    inst_cols.append((ci, INST_MAP[cell]))
            header_seen = True
            continue
        # data rows: 'Grupa X' in col 0
        if not (header_seen and current_ws):
            continue
        gname = row[0]
        if not (isinstance(gname, str) and gname.startswith("Grupa ")):
            continue
        gname = gname.strip()
        pos: dict[str, float] = {i: 0.0 for i in INSTRUMENTS}
        for ci, inst_key in inst_cols:
            v = row[ci]
            if v is None or v == "":
                continue
            try:
                pos[inst_key] = float(v)
            except (TypeError, ValueError):
                pos[inst_key] = 0.0
        by_ws[current_ws][1][gname] = pos
    return by_ws


def _parse_wyniki(ws) -> dict:
    """Zwraca {week_start_iso: {group: final_value}} z arkusza wyniki."""
    by_ws: dict[str, dict] = {}
    current_ws: str | None = None
    header_seen = False
    stan_col: int | None = None

    for row in ws.iter_rows(values_only=True):
        if row[0] == "Tydzień" and row[1]:
            current_ws = _parse_label_to_monday(_normalize_label(str(row[1])))
            by_ws.setdefault(current_ws, {})
            header_seen = False
            stan_col = None
            continue
        if row[0] == "Numer Grupy":
            for ci, cell in enumerate(row):
                if isinstance(cell, str) and "stan portfela" in cell.lower():
                    stan_col = ci
                    break
            header_seen = True
            continue
        if not (header_seen and current_ws and stan_col is not None):
            continue
        gname = row[0]
        if not (isinstance(gname, str) and gname.startswith("Grupa ")):
            continue
        v = row[stan_col]
        if v is None:
            continue
        try:
            by_ws[current_ws][gname.strip()] = float(v)
        except (TypeError, ValueError):
            continue
    return by_ws


def _parse_prices(ws) -> dict:
    """Zwraca {week_start_iso: (label, {'open': {inst: px}, 'close': {inst: px}})}."""
    by_ws: dict[str, tuple] = {}
    current_ws: str | None = None
    current_label: str | None = None
    for row in ws.iter_rows(values_only=True):
        if not row:
            continue
        c0 = row[0]
        if isinstance(c0, str):
            if re.match(r"^\d{1,2}\.\d{1,2}\s*[-–]\s*\d{1,2}\.\d{1,2}", c0.strip()):
                current_label = _normalize_label(c0.strip())
                current_ws = _parse_label_to_monday(current_label)
                by_ws.setdefault(current_ws, (current_label, {"open": {}, "close": {}}))
                continue
            if c0 in INST_MAP and current_ws:
                inst = INST_MAP[c0]
                try:
                    op = float(row[1]) if row[1] is not None else None
                    cl = float(row[2]) if row[2] is not None else None
                    by_ws[current_ws][1]["open"][inst] = op
                    by_ws[current_ws][1]["close"][inst] = cl
                except (TypeError, ValueError):
                    pass
    return by_ws


def _parse_extra_groups_from_ranking(ws) -> dict:
    """Wyciąga grupy M/N (które są tylko w rankingu wspólnym) wraz ze składem."""
    out: dict = {}
    for row in ws.iter_rows(values_only=True):
        if not row or not isinstance(row[0], str):
            continue
        if not row[0].startswith("Grupa "):
            continue
        g = row[0].strip()
        if g in ("Grupa M", "Grupa N"):
            members = [m.strip() for m in row[1:4] if m]
            year = row[4]
            try:
                year = int(year)
            except (TypeError, ValueError):
                year = 2
            out[g] = {"members": members, "year": year}
    return out


def backfill(xlsx_path: Path, data_path: Path) -> dict:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    print(f"📂 Excel: {xlsx_path.name} sheets={wb.sheetnames}")

    pos_y1 = _parse_obstawienia(wb["I rok - obstawienia"], year=1)
    pos_y2 = _parse_obstawienia(wb["II rok - obstawienia"], year=2)
    fin_y1 = _parse_wyniki(wb["I rok - wyniki"])
    fin_y2 = _parse_wyniki(wb["II rok wyniki"])
    prices = _parse_prices(wb["Ceny otwarcia i zamknięcia"])
    extra_groups = _parse_extra_groups_from_ranking(wb["Ranking wspólny"]) \
        if "Ranking wspólny" in wb.sheetnames else {}

    print(f"  Y1 obstawienia: {len(pos_y1)} tygodni")
    print(f"  Y2 obstawienia: {len(pos_y2)} tygodni")
    print(f"  Y1 wyniki:      {len(fin_y1)} tygodni")
    print(f"  Y2 wyniki:      {len(fin_y2)} tygodni")
    print(f"  Ceny:           {len(prices)} tygodni")
    print(f"  Dodatkowe grupy: {list(extra_groups.keys())}")

    # union all week_start keys
    all_ws_set: set = set(prices.keys()) | set(pos_y1.keys()) | set(pos_y2.keys())
    all_ws = sorted(all_ws_set)

    with data_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    existing = {w.get("week_start"): w for w in data.get("weeks", [])}
    added = 0
    enriched = 0

    new_weeks: list = []
    for ws_iso in all_ws:
        # label: preferuj z cen (zwykle dobrze sformatowany), potem z Y1, potem Y2
        if ws_iso in prices:
            lbl = prices[ws_iso][0]
            wk_prices = prices[ws_iso][1]
        elif ws_iso in pos_y1:
            lbl = pos_y1[ws_iso][0]
            wk_prices = None
        elif ws_iso in pos_y2:
            lbl = pos_y2[ws_iso][0]
            wk_prices = None
        else:
            continue

        positions: dict = {}
        if ws_iso in pos_y1:
            positions.update(pos_y1[ws_iso][1])
        if ws_iso in pos_y2:
            positions.update(pos_y2[ws_iso][1])

        canonical: dict = {}
        canonical.update(fin_y1.get(ws_iso, {}))
        canonical.update(fin_y2.get(ws_iso, {}))

        completed = bool(
            wk_prices
            and all(wk_prices.get("close", {}).get(i) is not None for i in INSTRUMENTS)
        )

        if ws_iso in existing:
            w = existing[ws_iso]
            changed = False
            if not w.get("positions") and positions:
                w["positions"] = positions; changed = True
            if not w.get("canonical_values") and canonical:
                w["canonical_values"] = canonical; changed = True
            if not isinstance(w.get("prices"), dict):
                w["prices"] = {"open": {}, "close": {}}
                changed = True
            if wk_prices:
                for side in ("open", "close"):
                    side_dict = w["prices"].setdefault(side, {})
                    for inst in INSTRUMENTS:
                        if not side_dict.get(inst) and wk_prices.get(side, {}).get(inst):
                            side_dict[inst] = wk_prices[side][inst]
                            changed = True
            if "completed" not in w and completed:
                w["completed"] = True; changed = True
            if changed:
                enriched += 1
            new_weeks.append(w)
            continue

        new_weeks.append({
            "label": lbl,
            "week_start": ws_iso,
            "completed": completed,
            "prices": wk_prices or {"open": {}, "close": {}},
            "positions": positions,
            "canonical_values": canonical,
        })
        added += 1

    # zachowaj kolejność wg week_start
    new_weeks.sort(key=lambda w: w.get("week_start") or "")
    data["weeks"] = new_weeks

    # uzupełnij grupy M, N jeśli brakuje
    groups = data.setdefault("groups", {})
    for g, meta in extra_groups.items():
        if g not in groups:
            groups[g] = meta
            print(f"  + dodano grupę {g}")

    # pending_week: ustaw na następny po ostatnim
    if new_weeks:
        last_open = next((w for w in new_weeks if not w.get("completed")), None)
        if last_open:
            data["pending_week"] = {
                "label": last_open["label"],
                "week_start": last_open["week_start"],
                "waiting_for_positions": not last_open.get("positions"),
            }
        else:
            data["pending_week"] = {
                "label": "Następny tydzień",
                "waiting_for_positions": True,
            }

    print(f"📝 Dodano nowych tygodni: {added}, wzbogacono istniejących: {enriched}")
    print(f"📊 Końcowa liczba tygodni: {len(new_weeks)}, grup: {len(groups)}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xlsx", type=Path, help="Ścieżka do Konkurs inwestycyjny.xlsx")
    parser.add_argument(
        "--data", type=Path, default=Path("data.json"),
        help="Ścieżka do data.json (default: ./data.json)",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Zapis do innego pliku (default: nadpisuje --data po backupie)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Tylko podgląd zmian, nie zapisuj",
    )
    args = parser.parse_args()

    if not args.xlsx.exists():
        print(f"❌ Brak pliku: {args.xlsx}", file=sys.stderr)
        return 2
    if not args.data.exists():
        print(f"❌ Brak data.json: {args.data}", file=sys.stderr)
        return 2

    data = backfill(args.xlsx, args.data)

    if args.dry_run:
        print("🔍 dry-run, nie zapisuję")
        return 0

    out = args.out or args.data
    if not args.out:
        backup = args.data.with_suffix(".json.bak." + datetime.now().strftime("%Y%m%d_%H%M%S"))
        shutil.copy2(args.data, backup)
        print(f"💾 Backup: {backup.name}")
    with out.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ Zapisano: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
