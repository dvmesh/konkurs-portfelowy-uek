"""Plotly figury i tabele rankingowe."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import INSTRUMENTS, INST_LABELS, INST_SHORT, MEDALS
from portfolio import portfolio_value, sharpe_ratio, volatility_annual
from pricing import fetch_hourly_df


def build_equity_chart(hist, bench, labels, groups_meta,
                       year_filter: str = "Wszystkie",
                       extra_groups=None, top_n: int = 5,
                       hourly: bool = False):
    extra_groups = extra_groups or []

    if year_filter == "Rok 1":
        hist = {g: v for g, v in hist.items() if groups_meta.get(g, {}).get("year") == 1}
    elif year_filter == "Rok 2":
        hist = {g: v for g, v in hist.items() if groups_meta.get(g, {}).get("year") == 2}

    if not hist:
        return go.Figure()

    final = {g: v[-1] for g, v in hist.items()}
    top = [g for g, _ in sorted(final.items(), key=lambda x: x[1], reverse=True)[:top_n]]
    top_set = set(top) | set(extra_groups)

    n_points = len(labels)
    p25, p50, p75, pmin, pmax = [], [], [], [], []
    for i in range(n_points):
        vals = sorted(v[i] for v in hist.values())
        if not vals:
            p25.append(None); p50.append(None); p75.append(None)
            pmin.append(None); pmax.append(None); continue

        def q(qq):
            idx = max(0, min(len(vals) - 1, int(round(qq * (len(vals) - 1)))))
            return vals[idx]

        p25.append(q(0.25)); p50.append(q(0.50)); p75.append(q(0.75))
        pmin.append(vals[0]); pmax.append(vals[-1])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=pmax, mode="lines", line=dict(width=0),
        name="zakres min–max", showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=pmin, mode="lines", line=dict(width=0),
        fill="tonexty", fillcolor="rgba(140,150,170,0.10)",
        name="zakres min–max",
        hovertemplate="min–max: %{y:.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=p75, mode="lines", line=dict(width=0),
        showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=p25, mode="lines", line=dict(width=0),
        fill="tonexty", fillcolor="rgba(74,158,255,0.15)",
        name="25–75 percentyl",
        hovertemplate="25–75: %{y:.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=p50, name="mediana", mode="lines",
        line=dict(color="rgba(200,210,225,0.5)", width=1.5, dash="dot"),
        hovertemplate="<b>mediana</b><br>%{x}: %{y:.3f}<extra></extra>",
    ))

    mode_main = "lines" if hourly else "lines+markers"
    avg_vals = [sum(v[i] for v in hist.values()) / len(hist) for i in range(n_points)]
    fig.add_trace(go.Scatter(
        x=labels, y=avg_vals, name="⌀ średnia",
        mode=mode_main,
        line=dict(color="#4A9EFF", width=2.5, dash="dot"),
        marker=dict(size=7, symbol="diamond") if not hourly else None,
        hovertemplate="<b>średnia</b><br>%{x}: %{y:.3f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=bench, name="benchmark 4×25%",
        mode=mode_main,
        line=dict(color="#FF6B35", width=2.5, dash="dash"),
        marker=dict(size=7, symbol="square") if not hourly else None,
        hovertemplate="<b>benchmark</b><br>%{x}: %{y:.3f}<extra></extra>",
    ))

    top_colors_medal = ["#FFD700", "#C0C0C0", "#CD7F32"]
    extra_palette = ["#7ee787", "#ff7b72", "#d2a8ff", "#79c0ff", "#f2cc60", "#ffa657"]

    for idx, g in enumerate(top):
        yr = groups_meta.get(g, {}).get("year", "")
        if idx < 3:
            color = top_colors_medal[idx]
            name = f"{MEDALS[idx]} {g}"
            width = 3 if not hourly else 2.2
        else:
            color = extra_palette[(idx - 3) % len(extra_palette)]
            name = f"#{idx+1} {g}"
            width = 2 if not hourly else 1.6
        fig.add_trace(go.Scatter(
            x=labels, y=hist[g], name=name, mode=mode_main,
            line=dict(color=color, width=width),
            marker=dict(size=7) if not hourly else None,
            hovertemplate=f"<b>{name}</b> (Rok {yr})<br>%{{x}}: %{{y:.3f}}<extra></extra>",
        ))

    highlight_palette = ["#58a6ff", "#bc8cff", "#ffa657", "#56d364"]
    for i, g in enumerate(extra_groups):
        if g in top_set and g in top:
            continue
        if g not in hist:
            continue
        yr = groups_meta.get(g, {}).get("year", "")
        fig.add_trace(go.Scatter(
            x=labels, y=hist[g], name=f"★ {g}", mode=mode_main,
            line=dict(color=highlight_palette[i % len(highlight_palette)],
                      width=2.5 if not hourly else 1.8),
            marker=dict(size=7, symbol="star") if not hourly else None,
            hovertemplate=f"<b>★ {g}</b> (Rok {yr})<br>%{{x}}: %{{y:.3f}}<extra></extra>",
        ))

    fig.add_hline(y=100, line_dash="dot",
                  line_color="rgba(255,255,255,0.12)", line_width=1)
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(13,17,23,0.6)",
        font=dict(family="Inter, sans-serif", size=12, color="#c9d1d9"),
        legend=dict(
            orientation="h", y=-0.22, x=0, xanchor="left",
            bgcolor="rgba(22,27,34,0.9)",
            bordercolor="#30363d", borderwidth=1, font=dict(size=10),
        ),
        xaxis=dict(gridcolor="#21262d", linecolor="#30363d",
                   title="Tydzień konkursu"),
        yaxis=dict(gridcolor="#21262d", linecolor="#30363d",
                   title="Wartość portfela (j.p.)", tickformat=".2f"),
        hovermode="x unified", height=420, autosize=True,
        margin=dict(l=45, r=15, t=15, b=90),
        # uirevision: stała wartość → Plotly trzyma user state (zoom, ukryte
        # traces) przy rerunach. Zmiana wartości → reset.
        uirevision=f"equity_{year_filter}_{'hourly' if hourly else 'weekly'}",
    )
    return fig


def build_candlestick_chart(week_opens: dict, live_prices: dict):
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[INST_LABELS[i] for i in INSTRUMENTS],
        vertical_spacing=0.14, horizontal_spacing=0.08,
    )
    positions_map = [(1, 1), (1, 2), (2, 1), (2, 2)]
    for idx, inst in enumerate(INSTRUMENTS):
        row, col = positions_map[idx]
        df = fetch_hourly_df(inst)
        if df is not None and not df.empty:
            ohlc = df[["Open", "High", "Low", "Close"]].copy()
            fig.add_trace(go.Candlestick(
                x=ohlc.index,
                open=ohlc["Open"], high=ohlc["High"],
                low=ohlc["Low"], close=ohlc["Close"],
                name=INST_SHORT[inst],
                increasing=dict(line=dict(color="#3fb950"),
                                fillcolor="rgba(63,185,80,0.55)"),
                decreasing=dict(line=dict(color="#f85149"),
                                fillcolor="rgba(248,81,73,0.55)"),
                showlegend=False, whiskerwidth=0.3,
            ), row=row, col=col)
        if week_opens.get(inst):
            fig.add_hline(
                y=week_opens[inst],
                line_dash="dash", line_color="rgba(74,158,255,0.9)", line_width=1.5,
                annotation_text=f"open tygodnia  {week_opens[inst]:.5g}",
                annotation_font=dict(color="#4A9EFF", size=10),
                annotation_position="bottom right",
                row=row, col=col,
            )
        lp = live_prices.get(inst)
        if lp and week_opens.get(inst):
            chg_pct = (lp / week_opens[inst] - 1) * 100
            sign = "+" if chg_pct >= 0 else ""
            color = "#3fb950" if chg_pct >= 0 else "#f85149"
            fig.add_hline(
                y=lp,
                line_dash="solid", line_color=color, line_width=2,
                annotation_text=f"live  {lp:.5g}  ({sign}{chg_pct:.2f}%)",
                annotation_font=dict(color=color, size=10),
                annotation_position="top right",
                row=row, col=col,
            )
    updates: dict = {}
    for i in range(1, 5):
        xk = f"xaxis{'' if i == 1 else i}"
        yk = f"yaxis{'' if i == 1 else i}"
        updates[f"{xk}_rangeslider_visible"] = False
        updates.update({f"{xk}_gridcolor": "#21262d",
                        f"{xk}_linecolor": "#30363d",
                        f"{yk}_gridcolor": "#21262d",
                        f"{yk}_linecolor": "#30363d"})
    fig.update_layout(
        **updates,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(13,17,23,0.6)",
        font=dict(family="Inter, sans-serif", size=11, color="#c9d1d9"),
        height=660,
        margin=dict(l=60, r=60, t=55, b=40),
        uirevision="candlestick_v1",
    )
    return fig


def build_ranking_df(hist, bench, groups_meta,
                     live_chg=None, open_week_positions=None) -> pd.DataFrame:
    bench_current = bench[-1]
    rows = []
    for g, vals in hist.items():
        meta = groups_meta.get(g, {})
        settled = vals[-1]
        prev = vals[-2] if len(vals) > 1 else 100.0

        if live_chg and open_week_positions is not None:
            pos = (open_week_positions.get(g) or {})
            live_v = portfolio_value(settled, pos, live_chg)
        else:
            live_v = None

        current = live_v if live_v is not None else settled
        rows.append(dict(
            group=g, year=meta.get("year", "?"),
            members=", ".join(meta.get("members", [])),
            settled=settled, current=current,
            week_settled_chg=settled - prev,
            total_chg=current - 100,
            vs_bench=current - bench_current,
            is_live=live_v is not None,
            sharpe=sharpe_ratio(vals),
            vol=volatility_annual(vals),
        ))
    rows.sort(key=lambda r: r["current"], reverse=True)

    result = []
    for i, r in enumerate(rows):
        result.append({
            "#":                  MEDALS[i] if i < 3 else str(i + 1),
            "Grupa":              r["group"],
            "Rok":                f"Rok {r['year']}",
            "Skład":              r["members"],
            "Rozliczony (j.p.)":  r["settled"],
            "Live (j.p.)":        r["current"] if r["is_live"] else None,
            "Tydzień Δ":          r["week_settled_chg"],
            "Od startu Δ":        r["total_chg"],
            "vs Benchmark":       r["vs_bench"],
            "Sharpe (roczny)":    r["sharpe"],
            "Zmienność (%)":      (r["vol"] * 100) if r["vol"] is not None else None,
        })
    return pd.DataFrame(result)
