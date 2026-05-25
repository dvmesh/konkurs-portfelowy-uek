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
from openpyxl.chart import (
    BarChart, BarChart3D, LineChart, PieChart,
    Reference, ScatterChart, Series,
)
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.layout import Layout, ManualLayout
from openpyxl.chart.marker import Marker
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.chart.text import RichText
from openpyxl.chart.trendline import Trendline
from openpyxl.drawing.line import LineProperties
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
        "Kierunek", "Kwota (j.p.)", "|Kwota|", "% kapitału grupy",
        "Kapitał na start tyg.", "|Sum| tygodnia", "Naruszenia",
    ]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    groups = data.get("groups") or {}
    hist, _, _, _ = build_history(data)
    row = 2

    # iter_completed_weeks daje "completed" tygodnie po kolei → indeks pasuje do hist[g][i]
    completed_list = [w for w in data.get("weeks", []) if w.get("completed")]
    for w_idx, week in enumerate(completed_list):
        positions = week.get("positions") or {}
        for g, pos in positions.items():
            if g not in groups:
                continue
            # kapitał = wartość portfela NA POCZĄTKU tygodnia = hist[g][w_idx]
            # (hist[g][0]=start 100, hist[g][1]=koniec w0 = start w1)
            vals = hist.get(g, [PORTFOLIO_START_VALUE])
            capital = vals[w_idx] if w_idx < len(vals) else PORTFOLIO_START_VALUE
            errs = validate_positions(pos, capital=capital)
            abs_sum = sum(abs(pos.get(i) or 0) for i in INSTRUMENTS)
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
                _format_pct(ws.cell(row=row, column=9), abs(float(v)) / capital if capital else 0)
                _format_num(ws.cell(row=row, column=10), capital, 3)
                _format_num(ws.cell(row=row, column=11), abs_sum, 2)
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
           "Kapitał na start", "|Sum| pozycji", "Nadalokacja",
           "Brak pozycji?", "Lista naruszeń"]
    for col, h in enumerate(hdr, start=1):
        ws.cell(row=1, column=col, value=h)
    _set_header(ws[1])

    groups = data.get("groups") or {}
    hist, _, _, _ = build_history(data)
    completed_list = [w for w in data.get("weeks", []) if w.get("completed")]
    row = 2
    found = 0
    for w_idx, week in enumerate(completed_list):
        positions = week.get("positions") or {}
        for g in groups:
            pos = positions.get(g) or {}
            vals = hist.get(g, [PORTFOLIO_START_VALUE])
            capital = vals[w_idx] if w_idx < len(vals) else PORTFOLIO_START_VALUE
            errs = validate_positions(pos, capital=capital)
            abs_sum = sum(abs(pos.get(i) or 0) for i in INSTRUMENTS)
            empty = not pos or all((pos.get(i) or 0) == 0 for i in INSTRUMENTS)
            if not errs and not empty:
                continue
            found += 1
            ws.cell(row=row, column=1, value=week.get("label"))
            ws.cell(row=row, column=2, value=week.get("week_start"))
            ws.cell(row=row, column=3, value=g)
            ws.cell(row=row, column=4, value=groups[g].get("year"))
            _format_num(ws.cell(row=row, column=5), capital, 3)
            _format_num(ws.cell(row=row, column=6), abs_sum, 2)
            over = abs_sum - capital
            _format_num(ws.cell(row=row, column=7), over if over > 0 else 0, 2)
            ws.cell(row=row, column=8, value="TAK" if empty else "nie")
            ws.cell(row=row, column=9, value="; ".join(errs) if errs else
                    ("brak zgłoszonych pozycji" if empty else ""))
            for c in ws[row]:
                c.border = BORDER
                c.alignment = CENTER if c.column != 9 else LEFT
            if errs:
                ws.cell(row=row, column=9).fill = VIOLATION_FILL
                ws.cell(row=row, column=7).fill = VIOLATION_FILL
            elif empty:
                ws.cell(row=row, column=8).fill = WARN_FILL
            row += 1

    if found == 0:
        ws.cell(row=2, column=1, value="Brak naruszeń regulaminu - wszystkie grupy w normie.")
        ws.cell(row=2, column=1).fill = OK_FILL
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=9)
    ws.freeze_panes = "A2"
    _autosize(ws, min_width=10, max_width=50)


def _sheet_charts(wb: Workbook, data: dict) -> None:
    """Arkusz 14: wykresy natywne Excel (openpyxl Chart).

    Wykresy wymagają arkusza z liczbami jako źródła, dlatego trzymamy je tu
    obok wykresów (część danych w ukrytych kolumnach H+ jako data backing).
    """
    ws = wb.create_sheet("14. Wykresy")
    ws.cell(row=1, column=1, value="WYKRESY ANALITYCZNE").font = Font(bold=True, size=16, color="1F4E78")
    ws.merge_cells("A1:E1")
    ws.cell(row=2, column=1, value=(
        "Wszystkie wykresy generowane natywnie w Excel — dane źródłowe w "
        "ukrytych kolumnach po prawej. Można edytować, kopiować, eksportować."
    )).font = Font(italic=True, color="555555", size=10)
    ws.merge_cells("A2:E2")

    hist, bench, labels, _ = build_history(data)
    groups = data.get("groups") or {}
    sorted_groups = sorted(groups.keys(), key=lambda x: (groups[x].get("year", 0), x))

    # ---------- block A: equity data (T rows × N+2 cols) ----------
    # kolumna A: label, B: bench, C..: grupy
    data_start_row = 5
    ws.cell(row=data_start_row - 1, column=1, value="Tydzień")
    ws.cell(row=data_start_row - 1, column=2, value="Benchmark")
    for i, g in enumerate(sorted_groups):
        ws.cell(row=data_start_row - 1, column=3 + i, value=g)
    for i, lbl in enumerate(labels):
        r = data_start_row + i
        ws.cell(row=r, column=1, value=lbl)
        ws.cell(row=r, column=2, value=bench[i])
        for j, g in enumerate(sorted_groups):
            vals = hist.get(g) or []
            v = vals[i] if i < len(vals) else None
            ws.cell(row=r, column=3 + j, value=v)
    equity_last_row = data_start_row + len(labels) - 1

    # ── Chart 1: Equity curve (line) - top 6 grup + benchmark ──
    chart1 = LineChart()
    chart1.title = "Equity curve - Top 6 grup + benchmark 4×25%"
    chart1.style = 12
    chart1.y_axis.title = "Wartość portfela (j.p.)"
    chart1.x_axis.title = "Tydzień"
    chart1.height = 12
    chart1.width = 22
    # benchmark
    bench_ref = Reference(ws, min_col=2, min_row=data_start_row - 1,
                          max_col=2, max_row=equity_last_row)
    chart1.add_data(bench_ref, titles_from_data=True)
    # wybierz top 6 grup po wartości końcowej
    final_vals = [(g, (hist.get(g) or [0])[-1]) for g in sorted_groups]
    final_vals.sort(key=lambda x: x[1], reverse=True)
    top6 = [g for g, _ in final_vals[:6]]
    for g in top6:
        idx = sorted_groups.index(g)
        ref = Reference(ws, min_col=3 + idx, min_row=data_start_row - 1,
                        max_col=3 + idx, max_row=equity_last_row)
        chart1.add_data(ref, titles_from_data=True)
    cats = Reference(ws, min_col=1, min_row=data_start_row, max_row=equity_last_row)
    chart1.set_categories(cats)
    chart1.legend.position = "b"
    ws.add_chart(chart1, "A4")

    # ── Chart 2: Equity curve - WSZYSTKIE grupy (dla pełnego kontekstu) ──
    chart2 = LineChart()
    chart2.title = "Equity curve - wszystkie grupy (kontekst)"
    chart2.style = 13
    chart2.y_axis.title = "j.p."
    chart2.x_axis.title = "Tydzień"
    chart2.height = 12
    chart2.width = 22
    for i in range(len(sorted_groups)):
        ref = Reference(ws, min_col=3 + i, min_row=data_start_row - 1,
                        max_col=3 + i, max_row=equity_last_row)
        chart2.add_data(ref, titles_from_data=True)
    chart2.add_data(bench_ref, titles_from_data=True)
    chart2.set_categories(cats)
    chart2.legend.position = "r"
    # mniejsza czcionka dla legendy 30 elementów
    chart2.legend.txPr = None
    ws.add_chart(chart2, "M4")

    # ---------- block B: ranking final (na dole) ----------
    rank_start = equity_last_row + 3
    ws.cell(row=rank_start, column=1, value="Grupa")
    ws.cell(row=rank_start, column=2, value="Wartość końcowa")
    ws.cell(row=rank_start, column=3, value="ROI %")
    ws.cell(row=rank_start, column=4, value="Sharpe")
    ws.cell(row=rank_start, column=5, value="Volatility roczna")
    for i, (g, fv) in enumerate(final_vals, start=1):
        vals = hist.get(g) or []
        ws.cell(row=rank_start + i, column=1, value=g)
        ws.cell(row=rank_start + i, column=2, value=fv)
        ws.cell(row=rank_start + i, column=3, value=(fv / PORTFOLIO_START_VALUE - 1) * 100)
        sh = sharpe_ratio(vals)
        ws.cell(row=rank_start + i, column=4, value=sh if sh is not None else 0)
        vo = volatility_annual(vals)
        ws.cell(row=rank_start + i, column=5, value=(vo * 100) if vo is not None else 0)
    rank_last = rank_start + len(final_vals)

    # ── Chart 3: Bar chart - ranking final ──
    chart3 = BarChart()
    chart3.type = "bar"
    chart3.title = "Ranking końcowy - wartość portfela [j.p.]"
    chart3.style = 11
    chart3.y_axis.title = "Grupa"
    chart3.x_axis.title = "j.p."
    chart3.height = max(15, len(final_vals) * 0.45)
    chart3.width = 18
    data_ref = Reference(ws, min_col=2, min_row=rank_start,
                         max_col=2, max_row=rank_last)
    cats_ref = Reference(ws, min_col=1, min_row=rank_start + 1, max_row=rank_last)
    chart3.add_data(data_ref, titles_from_data=True)
    chart3.set_categories(cats_ref)
    chart3.legend = None
    ws.add_chart(chart3, f"A{rank_last + 3}")

    # ── Chart 4: Scatter Sharpe vs Volatility (risk-return) ──
    chart4 = ScatterChart()
    chart4.title = "Risk / Return: Sharpe vs Volatility roczna"
    chart4.style = 13
    chart4.x_axis.title = "Volatility roczna (%)"
    chart4.y_axis.title = "Sharpe ratio (roczny)"
    chart4.height = 14
    chart4.width = 18
    x_ref = Reference(ws, min_col=5, min_row=rank_start + 1, max_row=rank_last)
    y_ref = Reference(ws, min_col=4, min_row=rank_start + 1, max_row=rank_last)
    series = Series(y_ref, x_ref, title="Grupy")
    # marker styling
    series.marker = Marker(symbol="circle", size=8)
    series.graphicalProperties = GraphicalProperties(solidFill="4A9EFF")
    series.graphicalProperties.line.noFill = True  # tylko punkty
    chart4.series.append(series)
    chart4.legend = None
    ws.add_chart(chart4, f"M{rank_last + 3}")

    # ---------- block C: benchmark percentile spread (równolegle do block A) ----------
    spread_start = rank_last + 30  # dużo miejsca pod wykres 3
    ws.cell(row=spread_start, column=1, value="Tydzień")
    ws.cell(row=spread_start, column=2, value="Benchmark")
    ws.cell(row=spread_start, column=3, value="Średnia portfeli")
    ws.cell(row=spread_start, column=4, value="Mediana")
    ws.cell(row=spread_start, column=5, value="P25")
    ws.cell(row=spread_start, column=6, value="P75")
    ws.cell(row=spread_start, column=7, value="Min")
    ws.cell(row=spread_start, column=8, value="Max")
    for i, lbl in enumerate(labels):
        r = spread_start + 1 + i
        vals = sorted(v[i] for v in hist.values()) if hist else []
        if not vals:
            continue
        ws.cell(row=r, column=1, value=lbl)
        ws.cell(row=r, column=2, value=bench[i])
        ws.cell(row=r, column=3, value=sum(vals) / len(vals))
        ws.cell(row=r, column=4, value=vals[len(vals) // 2])
        ws.cell(row=r, column=5, value=vals[int(0.25 * (len(vals) - 1))])
        ws.cell(row=r, column=6, value=vals[int(0.75 * (len(vals) - 1))])
        ws.cell(row=r, column=7, value=vals[0])
        ws.cell(row=r, column=8, value=vals[-1])
    spread_last = spread_start + len(labels)

    # ── Chart 5: Benchmark vs portfolio distribution ──
    chart5 = LineChart()
    chart5.title = "Benchmark vs rozkład portfeli (min/p25/mediana/p75/max + średnia)"
    chart5.style = 12
    chart5.y_axis.title = "j.p."
    chart5.x_axis.title = "Tydzień"
    chart5.height = 12
    chart5.width = 22
    for col_off in range(2, 9):  # benchmark + 6 statystyk
        ref = Reference(ws, min_col=col_off, min_row=spread_start,
                        max_col=col_off, max_row=spread_last)
        chart5.add_data(ref, titles_from_data=True)
    cats5 = Reference(ws, min_col=1, min_row=spread_start + 1, max_row=spread_last)
    chart5.set_categories(cats5)
    chart5.legend.position = "b"
    ws.add_chart(chart5, f"A{spread_last + 3}")

    # ---------- block D: per-instrument cumulative returns ----------
    cum_start = spread_last + 30
    cum = {inst: [1.0] for inst in INSTRUMENTS}
    cum_labels = ["Start"]
    for week, _eff, _src, chg in iter_completed_weeks(data):
        cum_labels.append(week.get("label"))
        for inst in INSTRUMENTS:
            cum[inst].append(cum[inst][-1] * (1 + (chg.get(inst) or 0)))
    ws.cell(row=cum_start, column=1, value="Tydzień")
    for j, inst in enumerate(INSTRUMENTS):
        ws.cell(row=cum_start, column=2 + j, value=INST_LABELS[inst])
    for i, lbl in enumerate(cum_labels):
        r = cum_start + 1 + i
        ws.cell(row=r, column=1, value=lbl)
        for j, inst in enumerate(INSTRUMENTS):
            ws.cell(row=r, column=2 + j, value=cum[inst][i])
    cum_last = cum_start + len(cum_labels)

    # ── Chart 6: Per-instrument cumulative return ──
    chart6 = LineChart()
    chart6.title = "Skumulowany zwrot per instrument (start = 1.0)"
    chart6.style = 11
    chart6.y_axis.title = "Indeks"
    chart6.x_axis.title = "Tydzień"
    chart6.height = 12
    chart6.width = 22
    for j in range(len(INSTRUMENTS)):
        ref = Reference(ws, min_col=2 + j, min_row=cum_start,
                        max_col=2 + j, max_row=cum_last)
        chart6.add_data(ref, titles_from_data=True)
    cats6 = Reference(ws, min_col=1, min_row=cum_start + 1, max_row=cum_last)
    chart6.set_categories(cats6)
    chart6.legend.position = "b"
    ws.add_chart(chart6, f"M{spread_last + 3}")

    # ukryj kolumny z danymi (od H w prawo dane są tylko backing)
    for col_letter in ["A", "B", "C", "D", "E", "F", "G", "H"]:
        ws.column_dimensions[col_letter].width = 12

    # navigation helper
    ws.cell(row=3, column=1, value="📊 Wykresy: equity (top6 / wszystkie), ranking, risk/return, benchmark vs rozkład, instrumenty.").font = Font(italic=True, size=9, color="666666")
    ws.merge_cells("A3:Y3")


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
    _sheet_charts(wb, data)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def report_filename() -> str:
    return f"RaportKNF_KonkursUEK_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
