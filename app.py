"""Dashboard Streamlit konkursu portfelowego UEK.

Po refaktorze (2026-05) ten plik trzyma tylko warstwę UI - logika siedzi
w modułach: config, styles, data_io, pricing, portfolio, history, charts, knf_report.

Zmiany P0 wbudowane:
- hmac.compare_digest na hasło admina (brak hardcoded fallbacka),
- atomic write data.json (przez data_io.save_data),
- hard-block na |sum|>100 i NaN/inf przy zapisie pozycji,
- deadline-enforcement: pozycje edytowalne tylko gdy tydzień jeszcze nie wystartował,
- html.escape na week["label"] przed unsafe_allow_html,
- guard week["prices"] is None.
"""
from __future__ import annotations

import html
import math
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (
    GROUP_ORDER, INSTRUMENTS, INST_LABELS, INST_SHORT,
    MAX_PORTFOLIO_ALLOCATION, ALLOCATION_TOLERANCE,
)
from styles import inject_css
from data_io import (
    admin_login, admin_logout, admin_session_active,
    load_audit_log, load_data, save_data, verify_admin,
)
from pricing import (
    HAS_YF, effective_prices, fetch_live_prices,
    live_changes, week_is_provisional, price_changes,
)
from portfolio import (
    portfolio_value, sharpe_ratio, validate_positions, volatility_annual,
)
from history import build_history, build_hourly_history, iter_completed_weeks
from charts import (
    build_candlestick_chart, build_equity_chart, build_ranking_df,
)
from knf_report import build_knf_workbook, report_filename


st.set_page_config(
    page_title="Konkurs Portfelowy | Rynki Finansowe | UEK | 2026",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_css()


# ────────────────────────── fragmenty live ──────────────────────────


@st.fragment(run_every=60)
def live_ticker_bar(week_opens: dict) -> None:
    if not week_opens or not HAS_YF:
        return
    prices = fetch_live_prices()
    ts = datetime.now().strftime("%H:%M:%S")
    cols = st.columns(4)
    for i, inst in enumerate(INSTRUMENTS):
        lp = prices.get(inst)
        op = week_opens.get(inst)
        with cols[i]:
            if lp and op:
                chg_pct = (lp / op - 1) * 100
                sign = "+" if chg_pct >= 0 else ""
                cls = "ticker-green" if chg_pct >= 0 else "ticker-red"
                arrow = "▲" if chg_pct >= 0 else "▼"
                st.markdown(
                    f'<div class="ticker-card">'
                    f'<div class="ticker-name">{html.escape(INST_SHORT[inst])}</div>'
                    f'<div class="ticker-price">{lp:.5g}</div>'
                    f'<div class="{cls}">{arrow} {sign}{chg_pct:.3f}%</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="ticker-card">'
                    f'<div class="ticker-name">{html.escape(INST_SHORT[inst])}</div>'
                    f'<div class="ticker-price">—</div>'
                    f'<div class="ticker-gray">brak</div></div>',
                    unsafe_allow_html=True,
                )
    st.caption(f"⏱ {ts}  ·  odśw. co 60s  ·  zmiana vs otwarcie tygodnia")


def _nan_fmt(places: int = 3, sign: bool = False):
    pat = f"{{:+.{places}f}}" if sign else f"{{:.{places}f}}"
    def _f(x):
        try:
            if x is None or (isinstance(x, float) and math.isnan(x)):
                return "—"
            return pat.format(x)
        except Exception:
            return "—"
    return _f


@st.fragment(run_every=60)
def live_ranking_fragment(hist, bench, groups_meta,
                          open_wk_pos, week_opens) -> None:
    live_chg = None
    is_live = False
    if open_wk_pos and week_opens and HAS_YF:
        prices = fetch_live_prices()
        live_chg = live_changes(week_opens, prices)
        is_live = any(v is not None for v in live_chg.values())

    label_html = (
        '<span class="live-badge">LIVE</span>' if is_live
        else '<span style="color:#586069;font-size:0.8rem"> (po ostatnim rozliczeniu)</span>'
    )
    st.markdown(f"### 🏆 Ranking &nbsp;{label_html}", unsafe_allow_html=True)

    df = build_ranking_df(
        hist, bench, groups_meta,
        live_chg if is_live else None,
        open_wk_pos if is_live else None,
    )

    def _clr_delta(v):
        if not isinstance(v, (int, float)):
            return ""
        if v > 0:
            return "color:#3fb950;font-weight:600"
        if v < 0:
            return "color:#f85149"
        return ""

    def _clr_live(v):
        if v is None or not isinstance(v, (int, float)):
            return ""
        return "color:#3fb950;font-weight:700" if v > 100 else "color:#f85149"

    fmt = {
        "Rozliczony (j.p.)": "{:.3f}",
        "Live (j.p.)":       _nan_fmt(3),
        "Tydzień Δ":         "{:+.3f}",
        "Od startu Δ":       "{:+.3f}",
        "vs Benchmark":      "{:+.3f}",
        "Sharpe (roczny)":   _nan_fmt(2),
        "Zmienność (%)":     _nan_fmt(1),
    }
    styled = (
        df.style
        .format(fmt)
        .map(_clr_live,  subset=["Live (j.p.)"])
        .map(_clr_delta, subset=["Tydzień Δ", "Od startu Δ", "vs Benchmark"])
    )
    st.dataframe(
        styled, use_container_width=True, hide_index=True,
        column_config={
            "#":                 st.column_config.TextColumn("#", width=50),
            "Rok":               st.column_config.TextColumn("Rok", width=70),
            "Rozliczony (j.p.)": st.column_config.NumberColumn("Rozliczony", format="%.3f"),
            "Live (j.p.)":       st.column_config.TextColumn("Live", width=100),
            "Tydzień Δ":         st.column_config.NumberColumn("Tyg. Δ", format="%+.3f"),
            "Od startu Δ":       st.column_config.NumberColumn("Od startu", format="%+.3f"),
            "vs Benchmark":      st.column_config.NumberColumn("vs Bench", format="%+.3f"),
            "Sharpe (roczny)":   st.column_config.TextColumn(
                "Sharpe", width=80,
                help="Roczny Sharpe ratio z tygodniowych zwrotów (rf=0)."),
            "Zmienność (%)":     st.column_config.TextColumn(
                "Vol %", width=80,
                help="Roczna zmienność (sd tygodniowych zwrotów × √52)."),
            "Skład":             st.column_config.TextColumn("Skład", width=300),
        },
    )

    st.markdown("---")
    c1, c2 = st.columns(2)
    for widget_col, yr in zip([c1, c2], [1, 2]):
        with widget_col:
            st.markdown(f"**Rok {yr}**")
            yr_df = df[df["Rok"] == f"Rok {yr}"].copy().reset_index(drop=True)
            yr_df.insert(0, "Msc", range(1, len(yr_df) + 1))
            sub = ["Msc", "Grupa", "Rozliczony (j.p.)"]
            if is_live:
                sub.append("Live (j.p.)")
            sub.append("Tydzień Δ")
            st.dataframe(
                yr_df[sub].style.format({
                    "Rozliczony (j.p.)": "{:.3f}",
                    "Tydzień Δ":         "{:+.3f}",
                    "Live (j.p.)":       _nan_fmt(3),
                }),
                use_container_width=True, hide_index=True,
            )

    with st.expander("🎯 Zawodnicy tygodnia (top 3 per tydzień)"):
        weekly_rows = []
        n_weeks = len(next(iter(hist.values()))) if hist else 0
        for wi in range(1, n_weeks):
            deltas = [(g, hist[g][wi] - hist[g][wi - 1]) for g in hist]
            deltas.sort(key=lambda x: x[1], reverse=True)
            top3 = deltas[:3]
            weekly_rows.append({
                "Tydzień": f"#{wi}",
                "🥇 Grupa": top3[0][0] if len(top3) > 0 else "—",
                "🥇 Δ":     f"{top3[0][1]:+.3f}" if len(top3) > 0 else "—",
                "🥈 Grupa": top3[1][0] if len(top3) > 1 else "—",
                "🥈 Δ":     f"{top3[1][1]:+.3f}" if len(top3) > 1 else "—",
                "🥉 Grupa": top3[2][0] if len(top3) > 2 else "—",
                "🥉 Δ":     f"{top3[2][1]:+.3f}" if len(top3) > 2 else "—",
            })
        if weekly_rows:
            st.dataframe(pd.DataFrame(weekly_rows),
                         use_container_width=True, hide_index=True)


@st.fragment(run_every=300)
def candlestick_fragment(week_opens: dict) -> None:
    if not HAS_YF:
        st.info("Zainstaluj `yfinance` aby zobaczyć wykresy live.")
        return
    prices = fetch_live_prices()
    fig = build_candlestick_chart(week_opens, prices)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "⏱ Dane godzinowe z Yahoo Finance (odśw. co 5 min). "
        "Ceny live orientacyjne – rozliczenie wg stooq.pl."
    )


# ────────────────────────── zakładki UI ──────────────────────────


def show_group_detail_tab(data, hist, bench, labels, groups_meta) -> None:
    st.subheader("Szczegóły grupy")
    groups = list(hist.keys())
    if not groups:
        st.info("Brak danych grup.")
        return

    default_idx = groups.index("Grupa 13") if "Grupa 13" in groups else 0
    sel = st.selectbox("Wybierz grupę", groups, index=default_idx, key="detail_group")
    vals = hist[sel]
    meta = groups_meta.get(sel, {})

    total = vals[-1] - 100
    best_wi = max(range(1, len(vals)), key=lambda i: vals[i] - vals[i - 1]) if len(vals) > 1 else 0
    worst_wi = min(range(1, len(vals)), key=lambda i: vals[i] - vals[i - 1]) if len(vals) > 1 else 0
    beat = sum(1 for i in range(1, len(vals))
               if (vals[i] - vals[i - 1]) > (bench[i] - bench[i - 1]))
    shp = sharpe_ratio(vals)
    vol = volatility_annual(vals)

    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric("Total Δ", f"{total:+.3f} jp")
    with m2: st.metric("Sharpe (roczny)", f"{shp:.2f}" if shp is not None else "—")
    with m3: st.metric("Zmienność (roczna)", f"{(vol*100):.1f}%" if vol is not None else "—")
    with m4: st.metric("Pokonało bench.", f"{beat}/{len(vals)-1} tyg.")

    mbest, mworst = st.columns(2)
    with mbest:
        if len(vals) > 1:
            d = vals[best_wi] - vals[best_wi - 1]
            st.success(f"🏆 Najlepszy tydzień: **{html.escape(str(labels[best_wi]))}** ({d:+.3f} jp)")
    with mworst:
        if len(vals) > 1:
            d = vals[worst_wi] - vals[worst_wi - 1]
            st.error(f"📉 Najsłabszy tydzień: **{html.escape(str(labels[worst_wi]))}** ({d:+.3f} jp)")

    avg_vals = [sum(v[i] for v in hist.values()) / len(hist) for i in range(len(labels))]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=labels, y=bench, name="benchmark",
                             line=dict(color="#FF6B35", width=2, dash="dash")))
    fig.add_trace(go.Scatter(x=labels, y=avg_vals, name="średnia",
                             line=dict(color="#4A9EFF", width=2, dash="dot")))
    fig.add_trace(go.Scatter(x=labels, y=vals, name=sel,
                             line=dict(color="#FFD700", width=3),
                             mode="lines+markers", marker=dict(size=8)))
    fig.add_hline(y=100, line_dash="dot", line_color="rgba(255,255,255,0.12)")
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        height=360, margin=dict(l=40, r=20, t=10, b=30),
        legend=dict(orientation="h", y=-0.2),
        yaxis=dict(title="j.p."),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Pozycje i wkład per tydzień")
    rows = []
    for week, eff, _src, chg in iter_completed_weeks(data):
        pos = (week.get("positions") or {}).get(sel) or {}
        alloc = sum(abs(pos.get(i) or 0) for i in INSTRUMENTS)
        contrib = {i: (pos.get(i) or 0) * (chg.get(i) or 0) for i in INSTRUMENTS}
        rows.append({
            "Tydzień":  week["label"],
            "SPX pos":  pos.get("SPX") or 0,
            "SPX Δ":    contrib["SPX"],
            "XAU pos":  pos.get("XAUUSD") or 0,
            "XAU Δ":    contrib["XAUUSD"],
            "Bond pos": pos.get("BOND10Y") or 0,
            "Bond Δ":   contrib["BOND10Y"],
            "EUR pos":  pos.get("EURUSD") or 0,
            "EUR Δ":    contrib["EURUSD"],
            "|alok.|":  alloc,
            "Suma Δ":   sum(contrib.values()),
        })
    if rows:
        def _clr(v):
            if not isinstance(v, (int, float)):
                return ""
            return "color:#3fb950" if v > 0 else ("color:#f85149" if v < 0 else "")
        df_pos = pd.DataFrame(rows)
        fmt = {c: "{:+.3f}" for c in ["SPX Δ", "XAU Δ", "Bond Δ", "EUR Δ", "Suma Δ"]}
        fmt.update({c: "{:.2f}" for c in ["SPX pos", "XAU pos", "Bond pos", "EUR pos", "|alok.|"]})
        st.dataframe(
            df_pos.style.format(fmt).map(_clr, subset=["SPX Δ", "XAU Δ", "Bond Δ", "EUR Δ", "Suma Δ"]),
            use_container_width=True, hide_index=True,
        )
    st.caption(f"Skład: **{html.escape(', '.join(meta.get('members', [])))}** · "
               f"Rok {meta.get('year', '?')}")


def show_positions_tab(data, hist) -> None:
    pending = data.get("pending_week", {})
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]

    if pending.get("waiting_for_positions") and not open_wks:
        st.markdown(
            '<div class="pending-box">'
            '⏳ <strong>Administrator oczekuje na nowe pozycje od prowadzącego.</strong><br>'
            'Po otrzymaniu dyspozycji zostaną one wprowadzone do systemu.'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    if not open_wks:
        st.info("Brak otwartego tygodnia.")
        return

    week = open_wks[-1]
    if not week.get("positions"):
        st.warning(f"⏳ Tydzień **{week['label']}** jest otwarty – brak pozycji.")
        return

    st.subheader(f"Pozycje na tydzień  {week['label']}")
    groups_meta = data.get("groups", {})
    start_vals = {g: hist[g][-1] if g in hist else 100.0 for g in groups_meta}

    rows = []
    for g in GROUP_ORDER:
        if g not in groups_meta:
            continue
        pos = (week.get("positions") or {}).get(g) or {}
        meta = groups_meta[g]
        start = start_vals.get(g, 100.0)
        alloc = sum(abs(pos.get(i) or 0) for i in INSTRUMENTS)
        rows.append({
            "Grupa":         g,
            "Rok":           meta.get("year", "?"),
            "S&P 500":       pos.get("SPX") or 0,
            "Złoto":         pos.get("XAUUSD") or 0,
            "Obligacje 10Y": pos.get("BOND10Y") or 0,
            "EUR/USD":       pos.get("EURUSD") or 0,
            "Wolne środki":  round(start - alloc, 3),
            "Portfel start": round(start, 3),
        })

    df = pd.DataFrame(rows)

    def _color(val):
        try:
            v = float(val)
        except (TypeError, ValueError):
            return ""
        if v > 0:
            return "color: #3fb950"
        if v < 0:
            return "color: #f85149"
        return ""

    st.dataframe(
        df.style.map(_color, subset=["S&P 500", "Złoto", "Obligacje 10Y", "EUR/USD"]),
        use_container_width=True, hide_index=True,
    )

    opens = (week.get("prices") or {}).get("open") or {}
    if opens:
        cols = st.columns(4)
        for i, inst in enumerate(INSTRUMENTS):
            with cols[i]:
                st.metric(f"Otwarcie – {INST_SHORT[inst]}", opens.get(inst, "—"))


# ────────────────────────── panel admina ──────────────────────────


def admin_panel(data, sha) -> None:
    st.header("Panel administratora")

    if not admin_session_active():
        st.session_state.admin_ok = False
        if not st.secrets.get("admin_password"):
            st.error(
                "Brak hasła admina w secrets. Ustaw `admin_password` w "
                "`.streamlit/secrets.toml` lub zmienną środowiskową "
                "`KONKURS_ADMIN_PASSWORD`. Bez tego panel jest zablokowany."
            )
            return
        pwd = st.text_input("Hasło", type="password", key="admin_pwd_input")
        if st.button("Zaloguj"):
            if verify_admin(pwd):
                admin_login()
                st.rerun()
            else:
                st.error("Nieprawidłowe hasło")
        return

    st.success("Zalogowano")
    if st.button("Wyloguj"):
        admin_logout()
        st.rerun()
    st.divider()

    t1, t2, t3, t4 = st.tabs([
        "Otwórz tydzień", "Pozycje", "Zamknij tydzień", "Uzupełnij ceny oficjalne",
    ])
    with t1: _admin_open_week(data, sha)
    with t2: _admin_positions(data, sha)
    with t3: _admin_close_week(data, sha)
    with t4: _admin_update_prices(data, sha)


def _admin_open_week(data, sha) -> None:
    st.subheader("Otwórz nowy tydzień")
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]
    if open_wks:
        st.info(f"Tydzień **{open_wks[-1]['label']}** już otwarty. Zamknij najpierw.")
        return

    today = date.today()
    default_monday = today + timedelta(days=(7 - today.weekday()) % 7)

    if today.weekday() != 6:  # nie niedziela
        st.warning(
            "⚠️ Dziś nie jest niedziela. Regulamin przewiduje otwieranie tygodnia "
            "w niedzielę przed startem. Możesz kontynuować, ale działanie zostanie "
            "zalogowane w audit log."
        )
    st.caption(
        "Ceny otwarcia ściągane automatycznie z yfinance. "
        "Oficjalne ze stooq możesz wpisać później w zakładce „Uzupełnij ceny oficjalne”."
    )

    with st.form("form_open_week"):
        c1, c2 = st.columns([1, 2])
        with c1:
            wstart = st.date_input("Poniedziałek", value=default_monday)
        with c2:
            wend_default = wstart + timedelta(days=4)
            auto_label = f"{wstart.strftime('%d.%m')} – {wend_default.strftime('%d.%m')}"
            label = st.text_input("Etykieta", value=auto_label, max_chars=64)

        manual_opens = {i: 0.0 for i in INSTRUMENTS}
        with st.expander("Wpisz ręczne ceny otwarcia (opcjonalnie)"):
            cols = st.columns(4)
            for i, inst in enumerate(INSTRUMENTS):
                with cols[i]:
                    manual_opens[inst] = st.number_input(
                        INST_SHORT[inst], min_value=0.0, value=0.0,
                        format="%.5f", key=f"o_{inst}",
                    )

        if st.form_submit_button("Otwórz tydzień ➜", type="primary"):
            label_clean = (label or "").strip()
            if not label_clean:
                st.error("Podaj etykietę.")
                return
            # P0: sanityzacja - bez znaków HTML
            label_clean = html.escape(label_clean)
            final_opens = {
                inst: (manual_opens[inst] if manual_opens[inst] > 0 else None)
                for inst in INSTRUMENTS
            }
            data.setdefault("weeks", []).append(dict(
                label=label_clean, week_start=wstart.strftime("%Y-%m-%d"),
                completed=False,
                prices=dict(open=final_opens, close={i: None for i in INSTRUMENTS}),
                positions={},
            ))
            data["pending_week"] = dict(
                label=label_clean, week_start=wstart.strftime("%Y-%m-%d"),
                waiting_for_positions=True,
            )
            ok, msg = save_data(data, sha)
            st.success(msg) if ok else st.error(msg)
            if ok:
                st.rerun()


def _admin_positions(data, sha) -> None:
    st.subheader("Pozycje grup")
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]
    if not open_wks:
        st.info("Brak otwartego tygodnia.")
        return

    week = open_wks[-1]
    groups_meta = data.get("groups", {})
    existing = dict(week.get("positions") or {})

    # P0: deadline enforcement - nie można edytować po starcie tygodnia
    today = date.today()
    try:
        wstart = datetime.strptime(week.get("week_start", ""), "%Y-%m-%d").date()
    except ValueError:
        wstart = None

    week_started = bool(wstart and today >= wstart)
    if week_started:
        st.error(
            f"🚫 Tydzień **{week['label']}** już wystartował "
            f"({wstart.strftime('%d.%m.%Y')}). Zgodnie z regulaminem konkursu "
            "pozycje są niezmienne od poniedziałku. Edycja zablokowana — "
            "tylko podgląd."
        )
    elif wstart and (wstart - today).days > 1 and today.weekday() != 6:
        st.warning(
            "ℹ️ Regulamin: pozycje przyjmowane w niedzielę przed startem. "
            f"Tydzień startuje {wstart.strftime('%d.%m.%Y')} — masz jeszcze czas."
        )

    st.markdown(f"Tydzień: **{html.escape(week['label'])}** · "
                "**Sprawdź, edytuj, zapisz.**")

    rows = []
    for g in GROUP_ORDER:
        if g not in groups_meta:
            continue
        meta = groups_meta[g]
        prev = existing.get(g) or {}
        alloc = sum(abs(prev.get(i) or 0) for i in INSTRUMENTS)
        rows.append({
            "Grupa":   g,
            "Rok":     meta.get("year", 1),
            "Skład":   ", ".join(meta.get("members", [])),
            "SPX":     float(prev.get("SPX") or 0),
            "Złoto":   float(prev.get("XAUUSD") or 0),
            "Bond":    float(prev.get("BOND10Y") or 0),
            "EUR/USD": float(prev.get("EURUSD") or 0),
            "|alok.|": alloc,
        })
    df = pd.DataFrame(rows)

    edited = st.data_editor(
        df, use_container_width=True, hide_index=True,
        num_rows="fixed",
        disabled=["Grupa", "Rok", "Skład", "|alok.|"]
                 if not week_started else df.columns.tolist(),
        column_config={
            "Grupa":   st.column_config.TextColumn("Grupa", width=90),
            "Rok":     st.column_config.NumberColumn("Rok", width=60, format="%d"),
            "Skład":   st.column_config.TextColumn("Skład", width=280),
            "SPX":     st.column_config.NumberColumn(
                "SPX", min_value=-MAX_PORTFOLIO_ALLOCATION,
                max_value=MAX_PORTFOLIO_ALLOCATION, format="%.2f"),
            "Złoto":   st.column_config.NumberColumn(
                "Złoto", min_value=-MAX_PORTFOLIO_ALLOCATION,
                max_value=MAX_PORTFOLIO_ALLOCATION, format="%.2f"),
            "Bond":    st.column_config.NumberColumn(
                "Bond", min_value=-MAX_PORTFOLIO_ALLOCATION,
                max_value=MAX_PORTFOLIO_ALLOCATION, format="%.2f"),
            "EUR/USD": st.column_config.NumberColumn(
                "EUR/USD", min_value=-MAX_PORTFOLIO_ALLOCATION,
                max_value=MAX_PORTFOLIO_ALLOCATION, format="%.2f"),
            "|alok.|": st.column_config.NumberColumn(
                "|alok.|", format="%.2f",
                help="Suma wartości bezwzględnych pozycji"),
        },
        key="pos_editor",
    )

    # P0: walidacja przed zapisem - hard block nie warning
    violations: list[str] = []
    new_pos: dict[str, dict] = {}
    for _, r in edited.iterrows():
        try:
            pos_dict = {
                "SPX":     float(r["SPX"]),
                "XAUUSD":  float(r["Złoto"]),
                "BOND10Y": float(r["Bond"]),
                "EURUSD":  float(r["EUR/USD"]),
            }
        except (TypeError, ValueError):
            violations.append(f"{r['Grupa']}: nie-numeryczna wartość")
            continue
        errs = validate_positions(pos_dict, tolerance=ALLOCATION_TOLERANCE)
        if errs:
            violations.append(f"{r['Grupa']}: {'; '.join(errs)}")
        new_pos[r["Grupa"]] = pos_dict

    if violations:
        st.error(
            "🚫 Naruszenia regulaminu (zapis zablokowany):\n\n• "
            + "\n• ".join(violations)
        )

    if st.button("💾 Zapisz pozycje", type="primary",
                 disabled=week_started or bool(violations)):
        merged = dict(existing)
        merged.update(new_pos)
        week["positions"] = merged
        if "pending_week" in data:
            data["pending_week"]["waiting_for_positions"] = False
        ok, msg = save_data(data, sha)
        st.success(msg) if ok else st.error(msg)
        if ok:
            st.rerun()


def _admin_update_prices(data, sha) -> None:
    st.subheader("Uzupełnij oficjalne ceny ze stooq.pl")
    st.caption("Użyj gdy wcześniej tydzień leciał na yfinance (szacunek) "
               "i dostałeś finalne dane ze stooq.")

    weeks = data.get("weeks", [])
    if not weeks:
        st.info("Brak tygodni.")
        return

    options = [f"{i}: {w['label']}" for i, w in enumerate(weeks)]
    pick = st.selectbox("Tydzień", options, index=len(options) - 1)
    idx = int(pick.split(":")[0])
    week = weeks[idx]

    # P0: guard week["prices"] is None
    if not isinstance(week.get("prices"), dict):
        week["prices"] = {"open": {}, "close": {}}
    raw = week["prices"]
    raw_op = raw.get("open") or {}
    raw_cl = raw.get("close") or {}
    eff, src = effective_prices(week)

    st.markdown(f"**{html.escape(week['label'])}** · start: "
                f"{html.escape(str(week.get('week_start','?')))}")
    if week_is_provisional(src):
        st.warning("Ten tydzień używa szacunków z yfinance. Wpisanie wartości tu je zastąpi.")
    else:
        st.success("Ten tydzień ma już komplet oficjalnych cen.")

    with st.form(f"form_update_prices_{idx}"):
        st.markdown("**Ceny otwarcia**")
        co = st.columns(4)
        new_op = {}
        for i, inst in enumerate(INSTRUMENTS):
            with co[i]:
                manual = raw_op.get(inst) or 0.0
                hint = "" if src["open"][inst] == "manual" else f"  · yf: {eff['open'].get(inst) or '—'}"
                new_op[inst] = st.number_input(
                    f"open {INST_SHORT[inst]}{hint}",
                    min_value=0.0, value=float(manual),
                    format="%.5f", key=f"up_o_{idx}_{inst}",
                )

        st.markdown("**Ceny zamknięcia**")
        cc = st.columns(4)
        new_cl = {}
        for i, inst in enumerate(INSTRUMENTS):
            with cc[i]:
                manual = raw_cl.get(inst) or 0.0
                hint = "" if src["close"][inst] == "manual" else f"  · yf: {eff['close'].get(inst) or '—'}"
                new_cl[inst] = st.number_input(
                    f"close {INST_SHORT[inst]}{hint}",
                    min_value=0.0, value=float(manual),
                    format="%.5f", key=f"up_c_{idx}_{inst}",
                )

        if st.form_submit_button("💾 Zapisz oficjalne ceny"):
            week["prices"] = {
                "open":  {i: (new_op[i] if new_op[i] > 0 else None) for i in INSTRUMENTS},
                "close": {i: (new_cl[i] if new_cl[i] > 0 else None) for i in INSTRUMENTS},
            }
            ok, msg = save_data(data, sha)
            st.success(msg) if ok else st.error(msg)
            if ok:
                st.rerun()


def _admin_close_week(data, sha) -> None:
    st.subheader("Zamknij tydzień")
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]
    if not open_wks:
        st.info("Brak otwartego tygodnia.")
        return

    week = open_wks[-1]
    st.markdown(f"Zamykasz: **{html.escape(week['label'])}**")
    st.caption(
        "Jeden klik → tydzień zamknięty, ceny zamknięcia ściągnięte z yfinance. "
        "Oficjalne ze stooq wpiszesz później w zakładce „Uzupełnij ceny oficjalne”."
    )

    if st.button("🏁 Zamknij tydzień (yfinance)", type="primary"):
        # P0: guard prices=None
        if not isinstance(week.get("prices"), dict):
            week["prices"] = {"open": {}, "close": {}}
        week["prices"]["close"] = {i: None for i in INSTRUMENTS}
        week["completed"] = True
        data["pending_week"] = dict(
            label="Następny tydzień", waiting_for_positions=True,
        )
        ok, msg = save_data(data, sha)
        st.success(msg) if ok else st.error(msg)
        if ok:
            st.rerun()

    with st.expander("Wpisz ręczne ceny zamknięcia (opcjonalnie)"):
        opens = (week.get("prices") or {}).get("open") or {}
        live = fetch_live_prices() if HAS_YF else {}
        with st.form("form_close_week_manual"):
            cols = st.columns(4)
            closes = {}
            for i, inst in enumerate(INSTRUMENTS):
                with cols[i]:
                    st.markdown(f"**{INST_SHORT[inst]}**")
                    st.caption(
                        f"open: {opens.get(inst) or '—'}"
                        + (f"  ·  yf: {live[inst]:.5g}" if live.get(inst) else "")
                    )
                    closes[inst] = st.number_input(
                        "close", min_value=0.0, value=0.0,
                        format="%.5f", key=f"c_{inst}", label_visibility="collapsed",
                    )
            if st.form_submit_button("Zamknij z ręcznymi cenami"):
                if not isinstance(week.get("prices"), dict):
                    week["prices"] = {"open": {}, "close": {}}
                week["prices"]["close"] = {
                    inst: (closes[inst] if closes[inst] > 0 else None)
                    for inst in INSTRUMENTS
                }
                week["completed"] = True
                data["pending_week"] = dict(
                    label="Następny tydzień", waiting_for_positions=True,
                )
                ok, msg = save_data(data, sha)
                st.success(msg) if ok else st.error(msg)
                if ok:
                    st.rerun()


# ────────────────────────── zakładka KNF ──────────────────────────


def show_knf_tab(data) -> None:
    st.header("📑 Raport KNF — dowód kompletny")
    st.markdown(
        "Pełen raport Excel (13 arkuszy) ze wszystkimi obliczeniami, pozycjami "
        "tydzień-po-tygodniu, metrykami ryzyka i audit logiem. Dostępny tylko "
        "dla zalogowanego administratora — zawiera dane osobowe uczestników."
    )

    if not admin_session_active():
        st.warning(
            "🔒 Wymagane zalogowanie w zakładce **Admin**. "
            "Raport zawiera PII (imiona i nazwiska uczestników) i jest "
            "udostępniany tylko po autentykacji."
        )
        return

    weeks_done = [w for w in data.get("weeks", []) if w.get("completed")]
    groups = data.get("groups") or {}

    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric("Grup uczestników", len(groups))
    with m2: st.metric("Zamknięte tygodnie", len(weeks_done))
    with m3:
        prov_count = sum(
            1 for _ in weeks_done
            if week_is_provisional(effective_prices(_)[1])
        )
        st.metric("Tygodnie prowizoryczne", prov_count)
    with m4:
        audit = load_audit_log(limit=10_000)
        st.metric("Wpisy audit log", len(audit))

    st.markdown("### Zawartość raportu")
    st.markdown(
        "1. **Strona tytułowa** — meta, hash SHA-256 data.json, miejsce na podpisy\n"
        "2. **Uczestnicy** — pełna lista grup + skład\n"
        "3. **Pozycje (long-form)** — tydzień×grupa×instrument z flagami zgodności\n"
        "4. **Pozycje (pivot)** — macierz heatmapowana (long zielony, short czerwony)\n"
        "5. **Ceny tygodniowe** — open/close + źródło (stooq/yfinance) + Δ%\n"
        "6. **P&L per tydzień** — dekompozycja wyniku per instrument\n"
        "7. **Equity curve** — wartość portfela tydzień-po-tygodniu (z benchmarkiem)\n"
        "8. **Ranking końcowy** — miejsce, ROI, vs benchmark, Sharpe, vol, max DD\n"
        "9. **Metryki ryzyka** — szczegółowe statystyki per grupa\n"
        "10. **Top/Bottom tygodnia** — najlepsi i najgorsi w każdym tygodniu\n"
        "11. **Audit log** — wszystkie zmiany w data.json z timestampami\n"
        "12. **Naruszenia regulaminu** — `|sum|>100`, brak pozycji, nieprawidłowości\n"
        "13. **Benchmark vs portfele** — agregat tygodniowy (p25/p75, max-min spread)"
    )

    st.divider()
    col_a, col_b = st.columns([2, 1])
    with col_b:
        if st.button("🔨 Wygeneruj raport", type="primary", use_container_width=True):
            with st.spinner("Buduję raport KNF (13 arkuszy)..."):
                try:
                    payload = build_knf_workbook(data, audit)
                    st.session_state["knf_payload"] = payload
                    st.session_state["knf_filename"] = report_filename()
                    st.success(f"✅ Gotowe — {len(payload)/1024:.1f} KB")
                except Exception as exc:
                    st.error(f"Błąd generowania: {exc}")
    with col_a:
        if "knf_payload" in st.session_state:
            st.download_button(
                label=f"⬇️ Pobierz: {st.session_state['knf_filename']}",
                data=st.session_state["knf_payload"],
                file_name=st.session_state["knf_filename"],
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True,
            )
        else:
            st.info("Kliknij **Wygeneruj raport** aby przygotować plik.")

    if audit:
        with st.expander("📋 Podgląd ostatnich 20 wpisów audit log"):
            df_audit = pd.DataFrame(audit[-20:])
            st.dataframe(df_audit, use_container_width=True, hide_index=True)


# ────────────────────────── main ──────────────────────────


def main() -> None:
    data, sha = load_data()
    if not data:
        st.error("Nie można załadować danych.")
        return

    groups_meta = data.get("groups", {})
    hist, bench, labels, prov_flags = build_history(data)
    n_done = len(labels) - 1
    any_provisional = any(prov_flags)
    pending = data.get("pending_week", {})
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]

    active_week = open_wks[-1] if open_wks else None
    if active_week:
        eff_act, src_act = effective_prices(active_week)
        week_opens = {i: v for i, v in eff_act["open"].items() if v}
        active_opens_src = src_act["open"]
    else:
        week_opens = {}
        active_opens_src = {}
    open_wk_pos = active_week.get("positions") or {} if active_week else {}
    week_is_live = bool(active_week and week_opens and open_wk_pos and HAS_YF)

    _render_header(active_week, pending, open_wks, data, week_is_live, groups_meta, n_done)
    if week_opens and HAS_YF:
        st.markdown("")
        live_ticker_bar(week_opens)
        st.markdown("")
    _render_kpis(hist, bench, n_done)
    _render_status_banners(pending, open_wks, any_provisional, prov_flags, labels)

    tab_chart, tab_rank, tab_live, tab_detail, tab_pos, tab_admin, tab_knf = st.tabs([
        "📈 Wykres", "🏆 Ranking", "🕯️ Rynek live",
        "👤 Grupa", "📋 Pozycje", "⚙️ Admin", "📑 Raport KNF",
    ])

    with tab_rank:
        if n_done >= 1:
            live_ranking_fragment(
                hist, bench, groups_meta,
                open_wk_pos if week_is_live else None,
                week_opens if week_is_live else None,
            )
        else:
            st.info("Ranking pojawi się po rozliczeniu pierwszego tygodnia.")

    with tab_chart:
        _render_chart_tab(data, hist, bench, labels, groups_meta, n_done)

    with tab_live:
        _render_live_tab(active_week, week_opens, active_opens_src)

    with tab_detail:
        if n_done >= 1:
            show_group_detail_tab(data, hist, bench, labels, groups_meta)
        else:
            st.info("Detale grupy pojawią się po rozliczeniu pierwszego tygodnia.")

    with tab_pos:
        show_positions_tab(data, hist)

    with tab_admin:
        admin_panel(data, sha)

    with tab_knf:
        show_knf_tab(data)


def _render_header(active_week, pending, open_wks, data, week_is_live,
                   groups_meta, n_done) -> None:
    hcol, scol = st.columns([3, 1])
    with hcol:
        live_html = '<span class="live-badge">LIVE</span>' if week_is_live else ""
        st.markdown(
            "<h1 style='margin-bottom:0'>"
            "<span class='title-full'>Konkurs Portfelowy | Rynki Finansowe | UEK | 2026</span>"
            "<span class='title-short'>Konkurs UEK · 2026</span> "
            f"{live_html}</h1>",
            unsafe_allow_html=True,
        )
        if pending.get("waiting_for_positions") and not open_wks:
            st.markdown("**Status:** Oczekiwanie na dyspozycje od prowadzącego")
        elif active_week:
            st.markdown(f"**Tydzień aktywny:** {html.escape(active_week['label'])}")
        elif data.get("weeks"):
            st.markdown(f"**Ostatni zamknięty:** {html.escape(data['weeks'][-1]['label'])}")
    with scol:
        st.markdown(
            f"<div style='text-align:right;color:#8b949e;font-size:0.78rem;"
            f"padding-top:0.6rem'>Grup: {len(groups_meta)} · Tygodni: {n_done}"
            f"<br>Start: 100 jp</div>",
            unsafe_allow_html=True,
        )


def _render_kpis(hist, bench, n_done) -> None:
    if n_done < 1:
        return
    final = {g: v[-1] for g, v in hist.items()}
    sorted_g = sorted(final.items(), key=lambda x: x[1], reverse=True)
    leader_g, leader_v = sorted_g[0]
    avg_v = sum(final.values()) / len(final)
    bench_v = bench[-1]
    beat_bench = sum(1 for v in final.values() if v > bench_v)
    chg_leader = leader_v - (hist[leader_g][-2] if n_done > 1 else 100)

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Lider (po rozliczeniu)", leader_g,
                  f"{leader_v:.3f} jp ({chg_leader:+.3f})")
    with m2:
        st.metric("Średnia konkursu", f"{avg_v:.3f} jp",
                  f"{avg_v - 100:+.3f} od startu")
    with m3:
        st.metric("Benchmark 4×25%", f"{bench_v:.3f} jp",
                  f"{bench_v - 100:+.3f} od startu")
    with m4:
        st.metric("Pokonało benchmark",
                  f"{beat_bench}/{len(final)} grup",
                  f"{beat_bench/len(final)*100:.0f}%")
    st.markdown("")


def _render_status_banners(pending, open_wks, any_provisional, prov_flags, labels) -> None:
    if pending.get("waiting_for_positions") and not open_wks:
        st.markdown(
            '<div class="pending-box">⏳ <strong>Oczekiwanie na nowe pozycje.</strong> '
            "Prowadzący jeszcze nie przekazał dyspozycji. "
            "Wyniki po ostatnim zamkniętym tygodniu.</div>",
            unsafe_allow_html=True,
        )
    if any_provisional:
        prov_labels = [html.escape(str(labels[i])) for i in range(1, len(labels)) if prov_flags[i]]
        st.markdown(
            f'<div class="pending-box" style="background:#2a1f05;border-color:#d29922">'
            f'📊 <strong>Szacunek finalny.</strong> Niektóre tygodnie używają cen z '
            f'yfinance (brak oficjalnych cen ze stooq): '
            f'<em>{", ".join(prov_labels)}</em>. '
            f'Wyniki zaktualizują się gdy prowadzący wpisze oficjalne ceny.'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_chart_tab(data, hist, bench, labels, groups_meta, n_done) -> None:
    if n_done < 1:
        st.info("Wykres pojawi się po rozliczeniu pierwszego tygodnia.")
        return
    fc1, fc2, fc3 = st.columns([1, 1, 2])
    with fc1:
        granularity = st.radio(
            "Ziarnistość", ["Tygodniowo", "Godzinowo"],
            horizontal=True, key="chart_gran",
            help="Godzinowo = wykres pulsuje intraweek z cen yfinance",
        )
    with fc2:
        year_filter = st.radio(
            "Rok", ["Wszystkie", "Rok 1", "Rok 2"],
            horizontal=True, key="chart_year",
        )
    with fc3:
        all_groups = sorted(
            groups_meta.keys(),
            key=lambda g: (groups_meta[g].get("year", 0),
                           int("".join(c for c in g if c.isdigit()) or 0)),
        )
        extra = st.multiselect(
            "Dodaj grupy do wykresu (np. swoją)",
            options=all_groups, default=[], key="chart_extra",
        )

    if granularity == "Godzinowo":
        with st.spinner("Pobieram dane godzinowe z yfinance..."):
            ts_h, hist_h, bench_h = build_hourly_history(data)
        if ts_h:
            st.plotly_chart(
                build_equity_chart(hist_h, bench_h, ts_h, groups_meta,
                                   year_filter=year_filter,
                                   extra_groups=extra, hourly=True),
                use_container_width=True,
            )
        else:
            st.info("Brak danych godzinowych z yfinance — pokazuję tygodniowo.")
            st.plotly_chart(
                build_equity_chart(hist, bench, labels, groups_meta,
                                   year_filter=year_filter, extra_groups=extra),
                use_container_width=True,
            )
    else:
        st.plotly_chart(
            build_equity_chart(hist, bench, labels, groups_meta,
                               year_filter=year_filter, extra_groups=extra),
            use_container_width=True,
        )

    st.subheader("Łączna zmiana instrumentów od startu")
    cum = {inst: 1.0 for inst in INSTRUMENTS}
    for _week, _eff, _src, chg in iter_completed_weeks(data):
        for inst in INSTRUMENTS:
            cum[inst] *= 1 + (chg.get(inst) or 0)
    ic = st.columns(4)
    for i, inst in enumerate(INSTRUMENTS):
        with ic[i]:
            st.metric(INST_SHORT[inst], f"{(cum[inst]-1)*100:+.2f}%")

    with st.expander("Tabela cen tygodniowych"):
        price_rows = []
        for week, eff, src, chg in iter_completed_weeks(data):
            op = eff["open"]; cl = eff["close"]
            is_prov = week_is_provisional(src)
            price_rows.append({
                "Tydzień":         week["label"] + (" ⚠️" if is_prov else ""),
                "Źródło":          "yfinance (szac.)" if is_prov else "stooq (ofic.)",
                "SPX open":        op.get("SPX"),
                "SPX close":       cl.get("SPX"),
                "SPX Δ%":          f"{(chg.get('SPX') or 0)*100:+.3f}%",
                "Złoto open":      op.get("XAUUSD"),
                "Złoto close":     cl.get("XAUUSD"),
                "Złoto Δ%":        f"{(chg.get('XAUUSD') or 0)*100:+.3f}%",
                "Bond open":       op.get("BOND10Y"),
                "Bond close":      cl.get("BOND10Y"),
                "Bond Δ%":         f"{(chg.get('BOND10Y') or 0)*100:+.3f}%",
                "EUR/USD open":    op.get("EURUSD"),
                "EUR/USD close":   cl.get("EURUSD"),
                "EUR/USD Δ%":      f"{(chg.get('EURUSD') or 0)*100:+.3f}%",
            })
        if price_rows:
            st.dataframe(pd.DataFrame(price_rows),
                         use_container_width=True, hide_index=True)


def _render_live_tab(active_week, week_opens, active_opens_src) -> None:
    if not HAS_YF:
        st.warning("Zainstaluj `yfinance` aby zobaczyć rynek live.")
        return
    if active_week:
        live_opens = week_opens
        opens_src = active_opens_src
        banner = None
    else:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        fake_week = {
            "week_start": monday.strftime("%Y-%m-%d"),
            "prices": {"open": {}, "close": {}},
        }
        eff_f, src_f = effective_prices(fake_week)
        live_opens = {i: v for i, v in eff_f["open"].items() if v}
        opens_src = src_f["open"]
        banner = (
            f"Brak otwartego tygodnia od prowadzącego — pokazuję bieżący "
            f"({monday.strftime('%d.%m')}–{(monday + timedelta(days=4)).strftime('%d.%m')}) "
            f"z yfinance."
        )

    if banner:
        st.info(banner)

    yf_used = [INST_SHORT[i] for i, s in opens_src.items() if s == "yfinance"]
    if yf_used and not banner:
        st.caption(
            f"Otwarcia pobrane z yfinance: **{', '.join(yf_used)}**. "
            "Prowadzący może później wpisać oficjalne ze stooq."
        )
    elif not yf_used:
        st.caption("Wszystkie otwarcia oficjalne (stooq.pl).")

    st.caption(
        "Świece godzinowe, ostatnie 7 dni. Niebieska linia — otwarcie tygodnia. "
        "Zielona/czerwona — kurs live. Odśwież co 5 min."
    )
    candlestick_fragment(live_opens)


main()
