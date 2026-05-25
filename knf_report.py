"""Moduł eksportu raportu Excel dla KNF.

build_knf_workbook(data, audit) -> bytes

13 arkuszy:
  1. Strona tytułowa     (meta, hash, podpisy)
  2. Uczestnicy          (lista grup + skład)
  3. Pozycje (long-form) (tydzień×grupa×instrument z flagą zgodności)
  4. Pozycje (pivot)     (macierz heat-mapowana)
  5. Ceny tygodniowe     (open/close, źródło, Δ%)
  6. P&L per tydzień     (dekompozycja zysku per instrument)
  7. Equity curve        (wartość portfela tygodniowo + benchmark)
  8. Ranking końcowy     (miejsce, ROI, vs benchmark, Sharpe, vol, max DD)
  9. Metryki ryzyka      (Sharpe, vol, max DD, win-rate, long/short alok.)
 10. Top/Bottom tygodnia (komentarz dla każdego tygodnia)
 11. Audit log           (timestamp zmian data.json)
 12. Naruszenia regulam. (|sum|>100, brak pozycji, edycje po starcie)
 13. Benchmark           (benchmark vs portfele - tygodniowo)
"""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime
from typing import Iterable, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule, CellIsRule
from openpyxl.styles import NamedStyle

from config import INSTRUMENTS, INST_LABELS, INST_SHORT, PORTFOLIO_START_VALUE
from history import build_history, iter_completed_weeks
from portfolio import (
    benchmark_value,
    max_drawdown,
    portfolio_value,
    position_summary,
    sharpe_ratio,
    validate_positions,
    volatility_annual,
    win_rate,
)
from pricing import effective_prices, price_changes, week_is_provisional

# ────────────────────────── styling helpers ──────────────────────────

THIN = Side(border_style="thin", color="888888")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
SUBHEAD_FILL = PatternFill("solid", fgColor="D9E2F3")
SUBHEAD_FONT = Font(bold=True, color="1F4E78", size=10)
GROUP_FILL = PatternFill("solid", fgColor="F2F2F2")

LONG_FILL = PatternFill("solid", fgColor="DAF7A6")
SHORT_FILL = PatternFill("solid", fgColor="F7C6A6")
VIOLATION_FILL = PatternFill("solid", fgColor="FF6B6B")
WARN_FILL = PatternFill("solid", fgColor="FFE599")
OK_FILL = PatternFill("solid", fgColor="C6EFCE")

CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
RIGHT = Alignment(horizontal="right", vertical="center")


def _set_header(row_cells, fill=HEADER_FILL, font=HEADER_FONT) -> None:
    for c in row_cells:
        c.fill = fill
        c.font = font
        c.alignment = CENTER
        c.border = BORDER


def _autosize(ws, min_width: int = 10, max_width: int = 40) -> None:
    for col in ws.columns:
        max_len = min_width
        letter = col[0].column_letter
        for c in col:
            try:
                v = "" if c.value is None else str(c.value)
                max_len = max(max_len, min(len(v) + 2, max_width))
            except Exception:
                pass
        ws.column_dimensions[letter].width = max_len


def _format_pct(cell, value, places: int = 2) -> None:
    cell.value = value
    cell.number_format = f"0.{'0'*places}%;[Red]-0.{'0'*places}%;0"


def _format_num(cell, value, places: int = 3) -> None:
    cell.value = value
    cell.number_format = f"0.{'0'*places};[Red]-0.{'0'*places};0.{'0'*places}"


# ────────────────────────── arkusze ──────────────────────────


def _sheet_cover(wb: Workbook, data: dict, audit: list) -> None:
    ws = wb.active
    ws.title = "1. Strona tytułowa"

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 60

    ws["A1"] = "RAPORT KONKURSU PORTFELOWEGO"
    ws["A1"].font = Font(bold=True, size=18, color="1F4E78")
    ws.merge_cells("A1:B1")
    ws.row_dimensions[1].height = 32

    ws["A2"] = "Dowód dla Komisji Nadzoru Finansowego (KNF)"
    ws["A2"].font = Font(italic=True, size=11, color="555555")
    ws.merge_cells("A2:B2")

    weeks_done = [w for w in data.get("weeks", []) if w.get("completed")]
    groups = data.get("groups") or {}
    start_iso = weeks_done[0].get("week_start") if weeks_done else "—"
    end_iso = weeks_done[-1].get("week_start") if weeks_done else "—"
    data_blob = json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
    data_sha = hashlib.sha256(data_blob).hexdigest()

    facts = [
        ("Tytuł konkursu",        "Konkurs Portfelowy | Rynki Finansowe | UEK | 2026"),
        ("Organizator",           "Uniwersytet Ekonomiczny w Krakowie"),
        ("Data wygenerowania",    datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("Okres raportu (od)",    start_iso),
        ("Okres raportu (do)",    end_iso),
        ("Liczba grup",           len(groups)),
        ("Liczba zamkn. tygodni", len(weeks_done)),
        ("Instrumenty",           ", ".join(INST_LABELS[i] for i in INSTRUMENTS)),
        ("Wartość startowa",      f"{PORTFOLIO_START_VALUE:.2f} j.p."),
        ("Reguła short/long",     "tak (kwoty +/-)"),
        ("Reguła rebalansu",      "BRAK rebalansu w tygodniu (Pn→Pt)"),
        ("Deadline pozycji",      "niedziela 23:59 przed startem tygodnia"),
        ("SHA-256 data.json",     data_sha),
        ("Liczba wpisów audit",   len(audit)),
        ("Format zgodny z",       "openpyxl 3.x; Excel 2016+"),
    ]
    for i, (k, v) in enumerate(facts, start=4):
        ws.cell(row=i, column=1, value=k).font = Font(bold=True)
        ws.cell(row=i, column=1).fill = SUBHEAD_FILL
        ws.cell(row=i, column=1).border = BORDER
        ws.cell(row=i, column=2, value=v).border = BORDER
        ws.cell(row=i, column=2).alignment = LEFT

    sign_row = 4 + len(facts) + 3
    ws.cell(row=sign_row, column=1, value="Podpisy:").font = Font(bold=True, size=12)
    ws.cell(row=sign_row + 2, column=1, value="Administrator konkursu").border = BORDER
    ws.cell(row=sign_row + 2, column=2, value="").border = BORDER
    ws.cell(row=sign_row + 3, column=1, value="Data / podpis").border = BORDER
    ws.cell(row=sign_row + 3, column=2, value="").border = BORDER
    ws.cell(row=sign_row + 5, column=1, value="Komisarz KNF").border = BORDER
    ws.cell(row=sign_row + 5, column=2, value="").border = BORDER
    ws.cell(row=sign_row + 6, column=1, value="Data / podpis").border = BORDER
    ws.cell(row=sign_row + 6, column=2, value="").border = BORDER


def _sheet_groups(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("2. Uczestnicy")
    hdr = ["Grupa", "Rok", "Osoba 1", "Osoba 2", "Osoba 3", "Liczba osób"]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    row = 2
    groups = data.get("groups") or {}
    for g in sorted(groups.keys(), key=lambda x: (groups[x].get("year", 0), x)):
        meta = groups[g]
        members = meta.get("members") or []
        ws.cell(row=row, column=1, value=g).border = BORDER
        ws.cell(row=row, column=2, value=meta.get("year")).border = BORDER
        for i in range(3):
            ws.cell(row=row, column=3 + i, value=members[i] if i < len(members) else "").border = BORDER
        ws.cell(row=row, column=6, value=len(members)).border = BORDER
        row += 1
    _autosize(ws, min_width=10, max_width=28)


def _sheet_positions_long(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("3. Pozycje (long-form)")
    hdr = [
        "Tydzień", "Data startu", "Grupa", "Rok", "Instrument",
        "Kierunek", "Kwota (j.p.)", "|Kwota|", "% portfela start",
        "|Sum| tygodnia", "Deadline", "Naruszenia",
    ]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    groups = data.get("groups") or {}
    hist, _, _, _ = build_history(data)
    row = 2
    weeks_iter = list(data.get("weeks", []))
    for w_idx, week in enumerate(weeks_iter):
        if not week.get("completed") and not week.get("positions"):
            continue
        positions = week.get("positions") or {}
        for g, pos in positions.items():
            if g not in groups:
                continue
            errs = validate_positions(pos)
            abs_sum = sum(abs(pos.get(i) or 0) for i in INSTRUMENTS)
            start_val = hist.get(g, [PORTFOLIO_START_VALUE])[w_idx] if w_idx < len(hist.get(g, [])) else PORTFOLIO_START_VALUE
            for inst in INSTRUMENTS:
                v = pos.get(inst) or 0
                direction = "—" if v == 0 else ("LONG" if v > 0 else "SHORT")
                ws.cell(row=row, column=1, value=week.get("label"))
                ws.cell(row=row, column=2, value=week.get("week_start"))
                ws.cell(row=row, column=3, value=g)
                ws.cell(row=row, column=4, value=groups[g].get("year"))
                ws.cell(row=row, column=5, value=INST_LABELS[inst])
                ws.cell(row=row, column=6, value=direction)
                _format_num(ws.cell(row=row, column=7), float(v), 2)
                _format_num(ws.cell(row=row, column=8), abs(float(v)), 2)
                _format_pct(ws.cell(row=row, column=9), abs(float(v)) / start_val if start_val else 0)
                _format_num(ws.cell(row=row, column=10), abs_sum, 2)
                ws.cell(row=row, column=11, value="niedziela przed startem")
                ws.cell(row=row, column=12, value="; ".join(errs) if errs else "OK")
                for c in ws[row]:
                    c.border = BORDER
                    c.alignment = CENTER if c.column != 12 else LEFT
                if direction == "LONG":
                    ws.cell(row=row, column=6).fill = LONG_FILL
                elif direction == "SHORT":
                    ws.cell(row=row, column=6).fill = SHORT_FILL
                if errs:
                    ws.cell(row=row, column=12).fill = VIOLATION_FILL
                else:
                    ws.cell(row=row, column=12).fill = OK_FILL
                row += 1
    ws.freeze_panes = "A2"
    _autosize(ws, min_width=10, max_width=40)


def _sheet_positions_pivot(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("4. Pozycje (pivot)")
    groups = data.get("groups") or {}
    groups_sorted = sorted(groups.keys(), key=lambda x: (groups[x].get("year", 0), x))

    weeks_iter = [w for w in data.get("weeks", []) if w.get("positions")]
    if not weeks_iter or not groups_sorted:
        ws.cell(row=1, column=1, value="Brak pozycji.")
        return

    ws.cell(row=1, column=1, value="Grupa / Tydzień → Instrument")
    ws.cell(row=2, column=1, value="Grupa")
    col = 2
    week_starts: list[tuple[int, int]] = []
    for week in weeks_iter:
        week_starts.append((col, col + len(INSTRUMENTS) - 1))
        ws.cell(row=1, column=col, value=week.get("label"))
        ws.merge_cells(start_row=1, start_column=col,
                       end_row=1, end_column=col + len(INSTRUMENTS) - 1)
        for i, inst in enumerate(INSTRUMENTS):
            ws.cell(row=2, column=col + i, value=INST_SHORT[inst])
        col += len(INSTRUMENTS)
    _set_header(ws[1])
    _set_header(ws[2], fill=SUBHEAD_FILL, font=SUBHEAD_FONT)

    row = 3
    for g in groups_sorted:
        ws.cell(row=row, column=1, value=g).font = Font(bold=True)
        ws.cell(row=row, column=1).fill = GROUP_FILL
        ws.cell(row=row, column=1).border = BORDER
        col = 2
        for week in weeks_iter:
            pos = (week.get("positions") or {}).get(g) or {}
            for inst in INSTRUMENTS:
                v = pos.get(inst) or 0
                cell = ws.cell(row=row, column=col, value=float(v) if v else 0)
                cell.number_format = "0.00;[Red]-0.00;0"
                cell.border = BORDER
                cell.alignment = CENTER
                if v > 0:
                    cell.fill = LONG_FILL
                elif v < 0:
                    cell.fill = SHORT_FILL
                col += 1
        row += 1
    ws.freeze_panes = "B3"
    for col_idx in range(2, col):
        ws.column_dimensions[get_column_letter(col_idx)].width = 9
    ws.column_dimensions["A"].width = 12


def _sheet_prices(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("5. Ceny tygodniowe")
    hdr = ["Tydzień", "Data startu", "Instrument", "Open", "Close",
           "Δ%", "Źródło open", "Źródło close", "Tydzień prowizoryczny?"]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    row = 2
    for week, eff, sources, chg in iter_completed_weeks(data):
        prov = week_is_provisional(sources)
        for inst in INSTRUMENTS:
            ws.cell(row=row, column=1, value=week.get("label"))
            ws.cell(row=row, column=2, value=week.get("week_start"))
            ws.cell(row=row, column=3, value=INST_LABELS[inst])
            _format_num(ws.cell(row=row, column=4), eff["open"].get(inst), 5)
            _format_num(ws.cell(row=row, column=5), eff["close"].get(inst), 5)
            _format_pct(ws.cell(row=row, column=6), chg.get(inst) or 0, 3)
            ws.cell(row=row, column=7, value=sources["open"].get(inst))
            ws.cell(row=row, column=8, value=sources["close"].get(inst))
            ws.cell(row=row, column=9, value="TAK" if prov else "nie")
            for c in ws[row]:
                c.border = BORDER
                c.alignment = CENTER
            if prov:
                ws.cell(row=row, column=9).fill = WARN_FILL
            row += 1
    ws.freeze_panes = "A2"
    _autosize(ws, min_width=12, max_width=20)


def _sheet_pnl(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("6. P&L per tydzień")
    hdr = ["Tydzień", "Grupa", "Rok", "Start (j.p.)"] + \
          [f"{INST_SHORT[i]} P&L" for i in INSTRUMENTS] + \
          ["Free", "P&L netto", "Koniec (j.p.)", "ROI tyg."]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    groups = data.get("groups") or {}
    state = {g: PORTFOLIO_START_VALUE for g in groups}
    row = 2
    for week, eff, _src, chg in iter_completed_weeks(data):
        canonical = week.get("canonical_values") or {}
        positions = week.get("positions") or {}
        for g in sorted(groups.keys(), key=lambda x: (groups[x].get("year", 0), x)):
            start_val = state[g]
            pos = positions.get(g) or {}
            contribs = {i: (pos.get(i) or 0) * (chg.get(i) or 0) for i in INSTRUMENTS}
            allocated = sum(abs(pos.get(i) or 0) for i in INSTRUMENTS)
            free = start_val - allocated
            pnl_net = sum(contribs.values())
            end_val = float(canonical[g]) if g in canonical else portfolio_value(start_val, pos, chg)
            roi = (end_val / start_val - 1) if start_val else 0

            ws.cell(row=row, column=1, value=week.get("label"))
            ws.cell(row=row, column=2, value=g)
            ws.cell(row=row, column=3, value=groups[g].get("year"))
            _format_num(ws.cell(row=row, column=4), start_val, 3)
            for i, inst in enumerate(INSTRUMENTS):
                _format_num(ws.cell(row=row, column=5 + i), contribs[inst], 3)
            _format_num(ws.cell(row=row, column=9), free, 3)
            _format_num(ws.cell(row=row, column=10), pnl_net, 3)
            _format_num(ws.cell(row=row, column=11), end_val, 3)
            _format_pct(ws.cell(row=row, column=12), roi, 3)
            for c in ws[row]:
                c.border = BORDER
                c.alignment = CENTER
            state[g] = end_val
            row += 1
    ws.freeze_panes = "A2"
    _autosize(ws, min_width=10, max_width=22)


def _sheet_equity(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("7. Equity curve")
    hist, bench, labels, prov_flags = build_history(data)
    groups = data.get("groups") or {}

    ws.cell(row=1, column=1, value="Tydzień")
    ws.cell(row=1, column=2, value="Prowizoryczny?")
    ws.cell(row=1, column=3, value="Benchmark 4×25%")
    col = 4
    sorted_groups = sorted(groups.keys(), key=lambda x: (groups[x].get("year", 0), x))
    for g in sorted_groups:
        ws.cell(row=1, column=col, value=g)
        col += 1
    _set_header(ws[1])

    for i, lbl in enumerate(labels):
        r = i + 2
        ws.cell(row=r, column=1, value=lbl)
        ws.cell(row=r, column=2, value="TAK" if prov_flags[i] else "nie")
        if prov_flags[i]:
            ws.cell(row=r, column=2).fill = WARN_FILL
        _format_num(ws.cell(row=r, column=3), bench[i], 3)
        col = 4
        for g in sorted_groups:
            vals = hist.get(g) or []
            v = vals[i] if i < len(vals) else None
            _format_num(ws.cell(row=r, column=col), v, 3)
            col += 1
        for c in ws[r]:
            c.border = BORDER
            c.alignment = CENTER

    last_col = 3 + len(sorted_groups)
    rule = ColorScaleRule(
        start_type="min", start_color="F8696B",
        mid_type="num", mid_value=100, mid_color="FFEB84",
        end_type="max", end_color="63BE7B",
    )
    if len(labels) > 1:
        ws.conditional_formatting.add(
            f"D2:{get_column_letter(last_col)}{1 + len(labels)}",
            rule,
        )
    ws.freeze_panes = "D2"
    _autosize(ws, min_width=10, max_width=14)


def _sheet_ranking(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("8. Ranking końcowy")
    hist, bench, labels, _ = build_history(data)
    groups = data.get("groups") or {}

    rows = []
    for g, vals in hist.items():
        meta = groups.get(g, {})
        final_v = vals[-1]
        roi = (final_v / PORTFOLIO_START_VALUE - 1) if vals else 0
        vs_b = final_v - bench[-1] if bench else 0
        rows.append({
            "group": g,
            "year": meta.get("year"),
            "members": ", ".join(meta.get("members") or []),
            "final": final_v,
            "roi": roi,
            "vs_bench": vs_b,
            "sharpe": sharpe_ratio(vals),
            "vol": volatility_annual(vals),
            "mdd": max_drawdown(vals),
            "win": win_rate(vals),
        })
    rows.sort(key=lambda r: r["final"], reverse=True)

    hdr = ["Miejsce", "Grupa", "Rok", "Skład",
           "Wartość końcowa", "ROI total", "vs Benchmark",
           "Sharpe (roczny)", "Volatility (roczna)", "Max Drawdown", "Win rate"]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    for i, r in enumerate(rows, start=2):
        ws.cell(row=i, column=1, value=i - 1)
        ws.cell(row=i, column=2, value=r["group"])
        ws.cell(row=i, column=3, value=r["year"])
        ws.cell(row=i, column=4, value=r["members"])
        _format_num(ws.cell(row=i, column=5), r["final"], 3)
        _format_pct(ws.cell(row=i, column=6), r["roi"], 2)
        _format_num(ws.cell(row=i, column=7), r["vs_bench"], 3)
        if r["sharpe"] is not None:
            _format_num(ws.cell(row=i, column=8), r["sharpe"], 2)
        if r["vol"] is not None:
            _format_pct(ws.cell(row=i, column=9), r["vol"], 2)
        if r["mdd"] is not None:
            _format_pct(ws.cell(row=i, column=10), r["mdd"], 2)
        if r["win"] is not None:
            _format_pct(ws.cell(row=i, column=11), r["win"], 1)
        for c in ws[i]:
            c.border = BORDER
            c.alignment = CENTER
        if i - 1 == 1:
            ws.cell(row=i, column=1).fill = PatternFill("solid", fgColor="FFD700")
        elif i - 1 == 2:
            ws.cell(row=i, column=1).fill = PatternFill("solid", fgColor="C0C0C0")
        elif i - 1 == 3:
            ws.cell(row=i, column=1).fill = PatternFill("solid", fgColor="CD7F32")
    ws.freeze_panes = "A2"
    _autosize(ws, min_width=10, max_width=35)


def _sheet_risk(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("9. Metryki ryzyka")
    hist, _, _, _ = build_history(data)
    groups = data.get("groups") or {}

    hdr = ["Grupa", "Rok", "Sharpe", "Volatility", "Max DD", "Win rate",
           "Σ pozycji long", "Σ pozycji short", "Σ |pozycji|",
           "n_long", "n_short", "n_zero", "% kapitału w long", "% kapitału w short"]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    row = 2
    weeks_done = list(iter_completed_weeks(data))
    for g in sorted(groups.keys(), key=lambda x: (groups[x].get("year", 0), x)):
        vals = hist.get(g, [])
        # alokacje uśrednione przez tygodnie completed
        long_t = short_t = abs_t = 0.0
        n_long = n_short = n_zero = 0
        for week, _eff, _src, _chg in weeks_done:
            pos = (week.get("positions") or {}).get(g) or {}
            s = position_summary(pos)
            long_t += s["long_total"]; short_t += s["short_total"]; abs_t += s["abs_total"]
            n_long += s["n_long"]; n_short += s["n_short"]; n_zero += s["n_zero"]
        nw = max(1, len(weeks_done))
        ws.cell(row=row, column=1, value=g)
        ws.cell(row=row, column=2, value=groups[g].get("year"))
        sh = sharpe_ratio(vals)
        if sh is not None: _format_num(ws.cell(row=row, column=3), sh, 2)
        vo = volatility_annual(vals)
        if vo is not None: _format_pct(ws.cell(row=row, column=4), vo, 2)
        mdd = max_drawdown(vals)
        if mdd is not None: _format_pct(ws.cell(row=row, column=5), mdd, 2)
        wr = win_rate(vals)
        if wr is not None: _format_pct(ws.cell(row=row, column=6), wr, 1)
        _format_num(ws.cell(row=row, column=7), long_t / nw, 2)
        _format_num(ws.cell(row=row, column=8), short_t / nw, 2)
        _format_num(ws.cell(row=row, column=9), abs_t / nw, 2)
        ws.cell(row=row, column=10, value=n_long)
        ws.cell(row=row, column=11, value=n_short)
        ws.cell(row=row, column=12, value=n_zero)
        _format_pct(ws.cell(row=row, column=13), (long_t / nw) / 100 if nw else 0, 1)
        _format_pct(ws.cell(row=row, column=14), (short_t / nw) / 100 if nw else 0, 1)
        for c in ws[row]:
            c.border = BORDER
            c.alignment = CENTER
        row += 1
    ws.freeze_panes = "A2"
    _autosize(ws, min_width=10, max_width=18)


def _sheet_topbottom(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("10. Top-Bottom tygodnia")
    hist, _bench, labels, _ = build_history(data)

    hdr = ["Tydzień", "🥇 Grupa", "🥇 Δ", "🥈 Grupa", "🥈 Δ", "🥉 Grupa", "🥉 Δ",
           "↓ Grupa", "↓ Δ", "Komentarz rynkowy"]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    completed = list(iter_completed_weeks(data))
    for wi in range(1, len(labels)):
        week, _eff, _src, chg = completed[wi - 1] if wi - 1 < len(completed) else (None, {}, {}, {})
        deltas = sorted(
            [(g, hist[g][wi] - hist[g][wi - 1]) for g in hist],
            key=lambda x: x[1], reverse=True,
        )
        top3 = deltas[:3]
        bottom = deltas[-1] if deltas else None
        comment = []
        for inst in INSTRUMENTS:
            c = chg.get(inst)
            if c is not None:
                comment.append(f"{INST_SHORT[inst]} {c:+.2%}")
        row = wi + 1
        ws.cell(row=row, column=1, value=labels[wi])
        for j, (g, d) in enumerate(top3):
            ws.cell(row=row, column=2 + j * 2, value=g)
            _format_num(ws.cell(row=row, column=3 + j * 2), d, 3)
        if bottom:
            ws.cell(row=row, column=8, value=bottom[0])
            _format_num(ws.cell(row=row, column=9), bottom[1], 3)
        ws.cell(row=row, column=10, value=" · ".join(comment))
        for c in ws[row]:
            c.border = BORDER
            c.alignment = CENTER if c.column != 10 else LEFT
    ws.freeze_panes = "A2"
    _autosize(ws, min_width=10, max_width=40)


def _sheet_audit(wb: Workbook, audit: list) -> None:
    ws = wb.create_sheet("11. Audit log")
    hdr = ["Timestamp UTC", "Akcja", "Szczegóły"]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    if not audit:
        ws.cell(row=2, column=1, value="Brak wpisów audit_log.jsonl.")
        ws.cell(row=2, column=1).fill = WARN_FILL
        return

    for i, entry in enumerate(audit, start=2):
        ws.cell(row=i, column=1, value=entry.get("ts"))
        ws.cell(row=i, column=2, value=entry.get("action"))
        ws.cell(row=i, column=3, value=json.dumps(entry.get("info") or {}, ensure_ascii=False))
        for c in ws[i]:
            c.border = BORDER
            c.alignment = LEFT
    ws.freeze_panes = "A2"
    _autosize(ws, min_width=15, max_width=80)


def _sheet_violations(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("12. Naruszenia regulaminu")
    hdr = ["Tydzień", "Data startu", "Grupa", "Rok",
           "|Sum| pozycji", "Brak pozycji?", "Lista naruszeń"]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    groups = data.get("groups") or {}
    row = 2
    found = 0
    for week in data.get("weeks", []):
        positions = week.get("positions") or {}
        for g in groups:
            pos = positions.get(g) or {}
            errs = validate_positions(pos)
            abs_sum = sum(abs(pos.get(i) or 0) for i in INSTRUMENTS)
            empty = not pos or all((pos.get(i) or 0) == 0 for i in INSTRUMENTS)
            if not errs and not empty:
                continue
            found += 1
            ws.cell(row=row, column=1, value=week.get("label"))
            ws.cell(row=row, column=2, value=week.get("week_start"))
            ws.cell(row=row, column=3, value=g)
            ws.cell(row=row, column=4, value=groups[g].get("year"))
            _format_num(ws.cell(row=row, column=5), abs_sum, 2)
            ws.cell(row=row, column=6, value="TAK" if empty else "nie")
            ws.cell(row=row, column=7, value="; ".join(errs) if errs else
                    ("brak zgłoszonych pozycji" if empty else ""))
            for c in ws[row]:
                c.border = BORDER
                c.alignment = CENTER if c.column != 7 else LEFT
            if errs:
                ws.cell(row=row, column=7).fill = VIOLATION_FILL
            elif empty:
                ws.cell(row=row, column=6).fill = WARN_FILL
            row += 1

    if found == 0:
        ws.cell(row=2, column=1, value="Brak naruszeń regulaminu - wszystkie grupy w normie.")
        ws.cell(row=2, column=1).fill = OK_FILL
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=7)
    ws.freeze_panes = "A2"
    _autosize(ws, min_width=10, max_width=50)


def _sheet_benchmark(wb: Workbook, data: dict) -> None:
    ws = wb.create_sheet("13. Benchmark vs portfele")
    hist, bench, labels, _ = build_history(data)

    hdr = ["Tydzień", "Benchmark 4×25%", "Średnia portfeli", "Mediana",
           "P25", "P75", "Najlepszy", "Najgorszy", "Spread (max-min)"]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    for i, lbl in enumerate(labels):
        vals = sorted(v[i] for v in hist.values()) if hist else []
        if not vals:
            continue
        row = i + 2
        ws.cell(row=row, column=1, value=lbl)
        _format_num(ws.cell(row=row, column=2), bench[i], 3)
        _format_num(ws.cell(row=row, column=3), sum(vals) / len(vals), 3)
        _format_num(ws.cell(row=row, column=4), vals[len(vals) // 2], 3)
        _format_num(ws.cell(row=row, column=5), vals[int(0.25 * (len(vals) - 1))], 3)
        _format_num(ws.cell(row=row, column=6), vals[int(0.75 * (len(vals) - 1))], 3)
        _format_num(ws.cell(row=row, column=7), vals[-1], 3)
        _format_num(ws.cell(row=row, column=8), vals[0], 3)
        _format_num(ws.cell(row=row, column=9), vals[-1] - vals[0], 3)
        for c in ws[row]:
            c.border = BORDER
            c.alignment = CENTER
    ws.freeze_panes = "A2"
    _autosize(ws, min_width=12, max_width=20)


# ────────────────────────── public API ──────────────────────────


def build_knf_workbook(data: dict, audit: Optional[Iterable[dict]] = None) -> bytes:
    """Składa kompletny raport KNF (xlsx) i zwraca bytes do pobrania."""
    wb = Workbook()
    audit_list = list(audit or [])

    _sheet_cover(wb, data, audit_list)
    _sheet_groups(wb, data)
    _sheet_positions_long(wb, data)
    _sheet_positions_pivot(wb, data)
    _sheet_prices(wb, data)
    _sheet_pnl(wb, data)
    _sheet_equity(wb, data)
    _sheet_ranking(wb, data)
    _sheet_risk(wb, data)
    _sheet_topbottom(wb, data)
    _sheet_audit(wb, audit_list)
    _sheet_violations(wb, data)
    _sheet_benchmark(wb, data)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def report_filename() -> str:
    return f"RaportKNF_KonkursUEK_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
