import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json, base64, requests
from datetime import datetime

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

st.set_page_config(
    page_title="Konkurs Portfelowy | UEK 2025",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #0d1117; }
[data-testid="stHeader"]           { background: transparent; }
section[data-testid="stSidebar"]   { background: #161b22; }

[data-testid="stMetric"] {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 0.6rem 1rem 0.4rem;
}
[data-testid="stMetricValue"] { font-size: 1.4rem; }

.pending-box {
    background: #1c1600;
    border: 1px solid #d29922;
    border-radius: 8px;
    padding: 1rem 1.4rem;
    margin-bottom: 1rem;
}
.live-badge {
    display: inline-block;
    background: #1a2e1a;
    border: 1px solid #3fb950;
    color: #3fb950;
    font-size: 0.72rem;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 20px;
    letter-spacing: 0.08em;
    vertical-align: middle;
    margin-left: 8px;
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0%,100% { opacity:1; }
    50%      { opacity:0.5; }
}
.ticker-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 0.7rem 1rem;
    text-align: center;
}
.ticker-name  { color: #8b949e; font-size: 0.78rem; font-weight:600; letter-spacing:.05em; }
.ticker-price { color: #e6edf3; font-size: 1.3rem; font-weight: 700; margin: 2px 0; }
.ticker-green { color: #3fb950; font-size: 0.88rem; font-weight: 600; }
.ticker-red   { color: #f85149; font-size: 0.88rem; font-weight: 600; }
.ticker-gray  { color: #8b949e; font-size: 0.88rem; }
thead tr th { background: #161b22 !important; }
.stTabs [data-baseweb="tab"] { font-size: 0.95rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

INSTRUMENTS = ["SPX", "XAUUSD", "BOND10Y", "EURUSD"]
INST_LABELS = {
    "SPX":     "S&P 500",
    "XAUUSD":  "Złoto (XAU/USD)",
    "BOND10Y": "Obligacje 10Y USA",
    "EURUSD":  "EUR/USD",
}
INST_SHORT = {"SPX": "SPX", "XAUUSD": "Złoto", "BOND10Y": "Obligacje 10Y", "EURUSD": "EUR/USD"}
MEDALS = ["🥇", "🥈", "🥉"]

YF_TICKERS = {
    "SPX":     "^GSPC",
    "XAUUSD":  "GC=F",
    "BOND10Y": "^TNX",
    "EURUSD":  "EURUSD=X",
}

GROUP_ORDER = [
    "Grupa 1","Grupa 2","Grupa 3","Grupa 4","Grupa 5",
    "Grupa 6","Grupa 7","Grupa 8","Grupa 9","Grupa 10",
    "Grupa 11","Grupa 12","Grupa 13","Grupa 14","Grupa 15",
    "Grupa A","Grupa B","Grupa C","Grupa D","Grupa E",
    "Grupa F","Grupa G","Grupa H","Grupa I","Grupa J",
    "Grupa K","Grupa L","Grupa M","Grupa N",
]

def _gh_headers():
    token = st.secrets.get("github_token", "")
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}


@st.cache_data(ttl=30, show_spinner=False)
def load_data():
    repo = st.secrets.get("github_repo", "")
    if repo:
        url = f"https://api.github.com/repos/{repo}/contents/data.json"
        try:
            r = requests.get(url, headers=_gh_headers(), timeout=10)
            if r.ok:
                j       = r.json()
                content = base64.b64decode(j["content"]).decode("utf-8")
                return json.loads(content), j["sha"]
        except Exception:
            pass
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return {}, None


def save_data(data: dict, sha):
    repo = st.secrets.get("github_repo", "")
    if repo and sha:
        url     = f"https://api.github.com/repos/{repo}/contents/data.json"
        content = base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode()
        ).decode()
        payload = {
            "message":   f"update [{datetime.now().strftime('%Y-%m-%d %H:%M')}]",
            "content":   content,
            "sha":       sha,
            "committer": {"name": "KonkursBot", "email": "bot@konkurs.pl"},
        }
        try:
            r = requests.put(url, headers=_gh_headers(), json=payload, timeout=15)
            if r.ok:
                load_data.clear()
                return True, "Zapisano do GitHub ✓"
            return False, f"GitHub error {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, f"Błąd sieci: {e}"
    try:
        with open("data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        load_data.clear()
        return True, "Zapisano lokalnie ✓"
    except Exception as e:
        return False, f"Błąd zapisu: {e}"

@st.cache_data(ttl=55, show_spinner=False)
def fetch_live_prices() -> dict:
    if not HAS_YF:
        return {}
    result = {}
    for inst, ticker in YF_TICKERS.items():
        try:
            result[inst] = float(yf.Ticker(ticker).fast_info.last_price)
        except Exception:
            result[inst] = None
    return result


@st.cache_data(ttl=300, show_spinner=False)
def fetch_hourly_df(inst: str):
    """Returns hourly OHLCV DataFrame for the given instrument (last 7d)."""
    if not HAS_YF:
        return None
    ticker = YF_TICKERS.get(inst)
    if not ticker:
        return None
    try:
        df = yf.download(ticker, period="7d", interval="1h",
                         auto_adjust=True, progress=False)
        if df.empty:
            return None
        # flatten MultiIndex columns produced by newer yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        return df
    except Exception:
        return None

def price_changes(prices: dict) -> dict:
    op = prices.get("open") or {}
    cl = prices.get("close") or {}
    return {
        inst: (cl[inst] / op[inst] - 1) if (op.get(inst) and cl.get(inst)) else None
        for inst in INSTRUMENTS
    }


def live_changes(week_opens: dict, live_prices: dict) -> dict:
    return {
        inst: (live_prices[inst] / week_opens[inst] - 1)
              if (week_opens.get(inst) and live_prices.get(inst)) else None
        for inst in INSTRUMENTS
    }


def portfolio_value(start: float, positions: dict, changes: dict) -> float:
    pos       = {i: (positions.get(i) or 0) for i in INSTRUMENTS}
    allocated = sum(abs(pos[i]) for i in INSTRUMENTS)
    free      = start - allocated
    total     = free
    for inst in INSTRUMENTS:
        chg    = changes.get(inst)
        p      = pos[inst]
        total += abs(p) + p * (chg if chg is not None else 0)
    return total


def benchmark_value(start: float, changes: dict) -> float:
    avg = sum((changes.get(i) or 0) for i in INSTRUMENTS) / 4
    return start * (1 + avg)


def build_history(data: dict):
    completed = [
        w for w in data.get("weeks", [])
        if w.get("completed") and (w.get("prices") or {}).get("close")
    ]
    groups = list(data.get("groups", {}).keys())
    hist   = {g: [100.0] for g in groups}
    bench  = [100.0]
    labels = ["Start"]

    for week in completed:
        chg = price_changes(week["prices"])
        labels.append(week["label"])
        bench.append(benchmark_value(bench[-1], chg))
        for g in groups:
            pos = (week.get("positions") or {}).get(g) or {}
            hist[g].append(portfolio_value(hist[g][-1], pos, chg))

    return hist, bench, labels

def build_equity_chart(hist, bench, labels, groups_meta):
    fig   = go.Figure()
    final = {g: v[-1] for g, v in hist.items()}
    top3  = [g for g, _ in sorted(final.items(), key=lambda x: x[1], reverse=True)[:3]]
    top_colors = ["#FFD700", "#C0C0C0", "#CD7F32"]

    for g, vals in hist.items():
        if g in top3:
            continue
        yr = groups_meta.get(g, {}).get("year", "")
        fig.add_trace(go.Scatter(
            x=labels, y=vals, name=g, mode="lines",
            line=dict(color="rgba(140,150,170,0.22)", width=1),
            hovertemplate=f"<b>{g}</b> (Rok {yr})<br>%{{x}}: %{{y:.3f}} jp<extra></extra>",
        ))

    for idx, g in enumerate(top3):
        yr = groups_meta.get(g, {}).get("year", "")
        fig.add_trace(go.Scatter(
            x=labels, y=hist[g], name=f"{MEDALS[idx]} {g}",
            mode="lines+markers",
            line=dict(color=top_colors[idx], width=2.5),
            marker=dict(size=7),
            hovertemplate=f"<b>{MEDALS[idx]} {g}</b> (Rok {yr})<br>%{{x}}: %{{y:.3f}} jp<extra></extra>",
        ))

    avg_vals = [sum(hist[g][i] for g in hist) / len(hist) for i in range(len(labels))]
    fig.add_trace(go.Scatter(
        x=labels, y=avg_vals, name="⌀ Średnia konkursu",
        mode="lines+markers",
        line=dict(color="#4A9EFF", width=2.5, dash="dot"),
        marker=dict(size=7, symbol="diamond"),
        hovertemplate="<b>Średnia</b><br>%{x}: %{y:.3f} jp<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=bench, name="📊 Benchmark 4×25%",
        mode="lines+markers",
        line=dict(color="#FF6B35", width=2.5, dash="dash"),
        marker=dict(size=7, symbol="square"),
        hovertemplate="<b>Benchmark</b><br>%{x}: %{y:.3f} jp<extra></extra>",
    ))
    fig.add_hline(y=100, line_dash="dot",
                  line_color="rgba(255,255,255,0.12)", line_width=1)
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(13,17,23,0.6)",
        font=dict(family="Inter, sans-serif", size=12, color="#c9d1d9"),
        legend=dict(x=1.01, y=1, xanchor="left",
                    bgcolor="rgba(22,27,34,0.9)",
                    bordercolor="#30363d", borderwidth=1, font=dict(size=11)),
        xaxis=dict(gridcolor="#21262d", linecolor="#30363d"),
        yaxis=dict(gridcolor="#21262d", linecolor="#30363d",
                   title="Wartość portfela (j.p.)", tickformat=".2f"),
        hovermode="x unified", height=420,
        margin=dict(l=60, r=220, t=20, b=40),
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
        df       = fetch_hourly_df(inst)

        if df is not None and not df.empty:
            ohlc = df[["Open", "High", "Low", "Close"]].copy()
            fig.add_trace(go.Candlestick(
                x=ohlc.index,
                open=ohlc["Open"], high=ohlc["High"],
                low=ohlc["Low"],   close=ohlc["Close"],
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
            sign    = "+" if chg_pct >= 0 else ""
            color   = "#3fb950" if chg_pct >= 0 else "#f85149"
            fig.add_hline(
                y=lp,
                line_dash="solid", line_color=color, line_width=2,
                annotation_text=f"live  {lp:.5g}  ({sign}{chg_pct:.2f}%)",
                annotation_font=dict(color=color, size=10),
                annotation_position="top right",
                row=row, col=col,
            )

    axis_style = dict(gridcolor="#21262d", linecolor="#30363d")
    updates = {}
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
    )
    return fig

def build_ranking_df(hist, bench, groups_meta,
                     live_chg=None, open_week_positions=None):
    bench_current = bench[-1]
    rows = []
    for g, vals in hist.items():
        meta    = groups_meta.get(g, {})
        settled = vals[-1]
        prev    = vals[-2] if len(vals) > 1 else 100.0

        if live_chg and open_week_positions is not None:
            pos    = (open_week_positions.get(g) or {})
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
        ))

    rows.sort(key=lambda r: r["current"], reverse=True)

    result = []
    for i, r in enumerate(rows):
        result.append({
            "#":                   MEDALS[i] if i < 3 else str(i + 1),
            "Grupa":               r["group"],
            "Rok":                 f"Rok {r['year']}",
            "Skład":               r["members"],
            "Rozliczony (j.p.)":  r["settled"],
            "Live (j.p.)":        r["current"] if r["is_live"] else None,
            "Tydzień Δ":          r["week_settled_chg"],
            "Od startu Δ":        r["total_chg"],
            "vs Benchmark":       r["vs_bench"],
        })
    return pd.DataFrame(result)

@st.fragment(run_every=60)
def live_ticker_bar(week_opens: dict):
    if not week_opens or not HAS_YF:
        return
    prices = fetch_live_prices()
    ts     = datetime.now().strftime("%H:%M:%S")
    cols   = st.columns([1, 1, 1, 1, 0.5])
    for i, inst in enumerate(INSTRUMENTS):
        lp = prices.get(inst)
        op = week_opens.get(inst)
        with cols[i]:
            if lp and op:
                chg_pct = (lp / op - 1) * 100
                sign    = "+" if chg_pct >= 0 else ""
                cls     = "ticker-green" if chg_pct >= 0 else "ticker-red"
                arrow   = "▲" if chg_pct >= 0 else "▼"
                st.markdown(f"""
<div class="ticker-card">
  <div class="ticker-name">{INST_SHORT[inst]}</div>
  <div class="ticker-price">{lp:.5g}</div>
  <div class="{cls}">{arrow} {sign}{chg_pct:.3f}% vs otwarcie</div>
</div>""", unsafe_allow_html=True)
            else:
                st.markdown(f"""
<div class="ticker-card">
  <div class="ticker-name">{INST_SHORT[inst]}</div>
  <div class="ticker-price">—</div>
  <div class="ticker-gray">brak danych</div>
</div>""", unsafe_allow_html=True)
    with cols[4]:
        st.markdown(
            f"<div style='color:#586069;font-size:0.75rem;padding-top:0.9rem;"
            f"text-align:right'>⏱ {ts}<br>odśw. co 60s</div>",
            unsafe_allow_html=True,
        )


@st.fragment(run_every=60)
def live_ranking_fragment(hist, bench, groups_meta,
                          open_wk_pos, week_opens):
    live_chg = None
    is_live  = False
    if open_wk_pos and week_opens and HAS_YF:
        prices   = fetch_live_prices()
        live_chg = live_changes(week_opens, prices)
        is_live  = any(v is not None for v in live_chg.values())

    label_html = (
        '<span class="live-badge">🔴 LIVE</span>' if is_live
        else '<span style="color:#586069;font-size:0.8rem"> (po ostatnim rozliczeniu)</span>'
    )
    st.markdown(f"### 🏆 Ranking &nbsp;{label_html}", unsafe_allow_html=True)

    df = build_ranking_df(hist, bench, groups_meta,
                          live_chg if is_live else None,
                          open_wk_pos if is_live else None)

    def _clr_delta(v):
        if not isinstance(v, (int, float)):
            return ""
        return "color:#3fb950;font-weight:600" if v > 0 else (
               "color:#f85149"                 if v < 0 else "")

    def _clr_live(v):
        if v is None or not isinstance(v, (int, float)):
            return ""
        return "color:#3fb950;font-weight:700" if v > 100 else "color:#f85149"

    fmt = {
        "Rozliczony (j.p.)": "{:.3f}",
        "Live (j.p.)":       lambda x: f"{x:.3f}" if x is not None and str(x) != "nan" else "—",
        "Tydzień Δ":         "{:+.3f}",
        "Od startu Δ":       "{:+.3f}",
        "vs Benchmark":      "{:+.3f}",
    }

    styled = (
        df.style
        .format(fmt)
        .map(_clr_live,  subset=["Live (j.p.)"])
        .map(_clr_delta, subset=["Tydzień Δ", "Od startu Δ", "vs Benchmark"])
    )

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config={
            "#":                  st.column_config.TextColumn("#",           width=50),
            "Rok":                st.column_config.TextColumn("Rok",         width=70),
            "Rozliczony (j.p.)":  st.column_config.NumberColumn("Rozliczony",format="%.3f"),
            "Live (j.p.)":        st.column_config.TextColumn("🔴 Live",     width=100),
            "Tydzień Δ":          st.column_config.NumberColumn("Tyg. Δ",    format="%+.3f"),
            "Od startu Δ":        st.column_config.NumberColumn("Od startu", format="%+.3f"),
            "vs Benchmark":       st.column_config.NumberColumn("vs Bench",  format="%+.3f"),
            "Skład":              st.column_config.TextColumn("Skład",       width=300),
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
                    "Live (j.p.)": lambda x: f"{x:.3f}" if x is not None and str(x) != "nan" else "—",
                }),
                use_container_width=True, hide_index=True,
            )


@st.fragment(run_every=300)
def candlestick_fragment(week_opens: dict):
    if not HAS_YF:
        st.info("Zainstaluj `yfinance` aby zobaczyć wykresy live.")
        return
    prices = fetch_live_prices()
    fig    = build_candlestick_chart(week_opens, prices)
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "⏱ Dane godzinowe z Yahoo Finance (odśw. co 5 min). "
        "Ceny live orientacyjne – rozliczenie wg stooq.pl."
    )

def show_positions_tab(data, hist):
    pending  = data.get("pending_week", {})
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]

    if pending.get("waiting_for_positions") and not open_wks:
        st.markdown("""
<div class="pending-box">
⏳ <strong>Administrator oczekuje na nowe pozycje od prowadzącego.</strong><br>
Po otrzymaniu dyspozycji zostaną one wprowadzone do systemu.
</div>""", unsafe_allow_html=True)
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
    start_vals  = {g: hist[g][-1] if g in hist else 100.0 for g in groups_meta}

    rows = []
    for g in GROUP_ORDER:
        if g not in groups_meta:
            continue
        pos   = (week.get("positions") or {}).get(g) or {}
        meta  = groups_meta[g]
        start = start_vals.get(g, 100.0)
        alloc = sum(abs(pos.get(i) or 0) for i in INSTRUMENTS)
        rows.append({
            "Grupa":          g,
            "Rok":            meta.get("year", "?"),
            "S&P 500":        pos.get("SPX") or 0,
            "Złoto":          pos.get("XAUUSD") or 0,
            "Obligacje 10Y":  pos.get("BOND10Y") or 0,
            "EUR/USD":        pos.get("EURUSD") or 0,
            "Wolne środki":   round(start - alloc, 3),
            "Portfel start":  round(start, 3),
        })

    df = pd.DataFrame(rows)

    def _color(val):
        try:
            v = float(val)
            return "color: #3fb950" if v > 0 else ("color: #f85149" if v < 0 else "")
        except (TypeError, ValueError):
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


def admin_panel(data, sha):
    st.header("⚙️  Panel administratora")

    if not st.session_state.get("admin_ok"):
        pwd = st.text_input("Hasło", type="password", key="admin_pwd_input")
        if st.button("Zaloguj"):
            correct = st.secrets.get("admin_password", "konkurs2025")
            if pwd == correct:
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error("Nieprawidłowe hasło")
        return

    st.success("✅ Zalogowano")
    if st.button("Wyloguj"):
        st.session_state.admin_ok = False
        st.rerun()
    st.divider()

    t1, t2, t3 = st.tabs(["📅 Otwórz tydzień", "📝 Pozycje", "🏁 Zamknij tydzień"])
    with t1:
        _admin_open_week(data, sha)
    with t2:
        _admin_positions(data, sha)
    with t3:
        _admin_close_week(data, sha)


def _admin_open_week(data, sha):
    st.subheader("Otwórz nowy tydzień")
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]
    if open_wks:
        st.info(f"Tydzień **{open_wks[-1]['label']}** już otwarty. Zamknij najpierw.")
        return

    with st.form("form_open_week"):
        c1, c2 = st.columns(2)
        with c1:
            label  = st.text_input("Etykieta", placeholder="30.03 – 03.04")
        with c2:
            wstart = st.date_input("Data otwarcia (poniedziałek)")
        st.markdown("**Ceny otwarcia** (stooq.pl – niedzielne 23:00 / poniedziałek)")
        cols  = st.columns(4)
        opens = {}
        for i, inst in enumerate(INSTRUMENTS):
            with cols[i]:
                opens[inst] = st.number_input(INST_SHORT[inst],
                                              min_value=0.0, value=0.0,
                                              format="%.5f", key=f"o_{inst}")
        mark_waiting = st.checkbox("Czekam na pozycje od prowadzącego", value=True)

        if st.form_submit_button("Otwórz tydzień ➜"):
            if not label:
                st.error("Podaj etykietę.")
                return
            data.setdefault("weeks", []).append(dict(
                label=label, week_start=wstart.strftime("%Y-%m-%d"),
                completed=False,
                prices=dict(open=opens, close=None),
                positions={},
            ))
            data["pending_week"] = dict(
                label=label, week_start=wstart.strftime("%Y-%m-%d"),
                waiting_for_positions=mark_waiting,
            )
            ok, msg = save_data(data, sha)
            st.success(msg) if ok else st.error(msg)
            if ok:
                st.rerun()


def _admin_positions(data, sha):
    st.subheader("Pozycje grup")
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]
    if not open_wks:
        st.info("Brak otwartego tygodnia.")
        return

    week        = open_wks[-1]
    groups_meta = data.get("groups", {})
    existing    = dict(week.get("positions") or {})
    st.markdown(f"Tydzień: **{week['label']}**")

    year_filter = st.radio("Pokaż:", ["Wszystkie", "Rok 1", "Rok 2"], horizontal=True)

    with st.form("form_positions"):
        new_pos = dict(existing)
        for g in GROUP_ORDER:
            if g not in groups_meta:
                continue
            meta = groups_meta[g]
            yr   = meta.get("year", 1)
            if year_filter == "Rok 1" and yr != 1:
                continue
            if year_filter == "Rok 2" and yr != 2:
                continue
            members_str = ", ".join(meta.get("members", []))
            with st.expander(f"**{g}** (Rok {yr}) — {members_str}"):
                prev = (existing.get(g) or {})
                cols = st.columns(4)
                gpos = {}
                for i, inst in enumerate(INSTRUMENTS):
                    with cols[i]:
                        gpos[inst] = st.number_input(
                            INST_SHORT[inst],
                            value=float(prev.get(inst) or 0),
                            step=0.01, format="%.2f",
                            key=f"p_{g}_{inst}",
                        )
                new_pos[g] = gpos

        if st.form_submit_button("💾 Zapisz pozycje"):
            week["positions"] = new_pos
            if "pending_week" in data:
                data["pending_week"]["waiting_for_positions"] = False
            ok, msg = save_data(data, sha)
            st.success(msg) if ok else st.error(msg)
            if ok:
                st.rerun()


def _admin_close_week(data, sha):
    st.subheader("Zamknij tydzień")
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]
    if not open_wks:
        st.info("Brak otwartego tygodnia.")
        return

    week  = open_wks[-1]
    opens = (week.get("prices") or {}).get("open") or {}
    st.markdown(f"Zamykasz: **{week['label']}**")

    with st.form("form_close_week"):
        st.markdown("**Ceny zamknięcia (piątek wieczór – stooq.pl)**")
        cols   = st.columns(4)
        closes = {}
        for i, inst in enumerate(INSTRUMENTS):
            with cols[i]:
                closes[inst] = st.number_input(
                    f"{INST_SHORT[inst]}\n*(open: {opens.get(inst, '?')})*",
                    min_value=0.0, value=0.0,
                    format="%.5f", key=f"c_{inst}",
                )
        if st.form_submit_button("🏁 Zamknij i oblicz wyniki"):
            week["prices"]["close"] = closes
            week["completed"]       = True
            data["pending_week"]    = dict(
                label="Następny tydzień",
                waiting_for_positions=True,
            )
            ok, msg = save_data(data, sha)
            st.success(msg) if ok else st.error(msg)
            if ok:
                st.rerun()

def main():
    data, sha = load_data()
    if not data:
        st.error("Nie można załadować danych.")
        return

    groups_meta         = data.get("groups", {})
    hist, bench, labels = build_history(data)
    n_done              = len(labels) - 1
    pending             = data.get("pending_week", {})
    open_wks            = [w for w in data.get("weeks", []) if not w.get("completed")]

    active_week  = open_wks[-1] if open_wks else None
    week_opens   = (active_week.get("prices") or {}).get("open") or {} if active_week else {}
    open_wk_pos  = active_week.get("positions") or {} if active_week else {}
    week_is_live = bool(active_week and week_opens and open_wk_pos and HAS_YF)

    hcol, scol = st.columns([3, 1])
    with hcol:
        live_html = '<span class="live-badge">🔴 LIVE</span>' if week_is_live else ""
        st.markdown(
            f"<h1 style='margin-bottom:0'>📈 Konkurs Portfelowy UEK 2025 {live_html}</h1>",
            unsafe_allow_html=True,
        )
        if pending.get("waiting_for_positions") and not open_wks:
            st.markdown("🟡 **Status:** Oczekiwanie na dyspozycje od prowadzącego")
        elif active_week:
            st.markdown(f"🟢 **Tydzień aktywny:** {active_week['label']}")
        elif data.get("weeks"):
            st.markdown(f"⚪ **Ostatni zamknięty:** {data['weeks'][-1]['label']}")
    with scol:
        st.markdown(
            f"<div style='text-align:right;color:#586069;font-size:0.82rem;"
            f"padding-top:1.8rem'>Grup: {len(groups_meta)} · Tygodni: {n_done}"
            f"<br>Kapitał start: 100 jp</div>",
            unsafe_allow_html=True,
        )

    if week_opens and HAS_YF:
        st.markdown("")
        live_ticker_bar(week_opens)
        st.markdown("")

    if n_done >= 1:
        final      = {g: v[-1] for g, v in hist.items()}
        sorted_g   = sorted(final.items(), key=lambda x: x[1], reverse=True)
        leader_g, leader_v = sorted_g[0]
        avg_v      = sum(final.values()) / len(final)
        bench_v    = bench[-1]
        beat_bench = sum(1 for v in final.values() if v > bench_v)
        chg_leader = leader_v - (hist[leader_g][-2] if n_done > 1 else 100)

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("🥇 Lider (po rozliczeniu)", leader_g,
                      f"{leader_v:.3f} jp ({chg_leader:+.3f})")
        with m2:
            st.metric("⌀ Średnia konkursu", f"{avg_v:.3f} jp",
                      f"{avg_v - 100:+.3f} od startu")
        with m3:
            st.metric("📊 Benchmark 4×25%", f"{bench_v:.3f} jp",
                      f"{bench_v - 100:+.3f} od startu")
        with m4:
            st.metric("✅ Pokonało benchmark",
                      f"{beat_bench}/{len(final)} grup",
                      f"{beat_bench/len(final)*100:.0f}%")
        st.markdown("")

    if pending.get("waiting_for_positions") and not open_wks:
        st.markdown(
            '<div class="pending-box">⏳ <strong>Oczekiwanie na nowe pozycje.</strong> '
            "Prowadzący jeszcze nie przekazał dyspozycji. "
            "Wyniki po ostatnim zamkniętym tygodniu.</div>",
            unsafe_allow_html=True,
        )

    tab_chart, tab_rank, tab_pos, tab_admin = st.tabs([
        "📈 Historia & rynek live",
        "🏆 Ranking",
        "📋 Pozycje",
        "⚙️ Admin",
    ])

    with tab_chart:
        if n_done >= 1:
            st.plotly_chart(
                build_equity_chart(hist, bench, labels, groups_meta),
                use_container_width=True,
            )

            st.subheader("Łączna zmiana instrumentów od startu")
            cum = {inst: 1.0 for inst in INSTRUMENTS}
            for week in [w for w in data["weeks"]
                         if w.get("completed") and (w.get("prices") or {}).get("close")]:
                chg = price_changes(week["prices"])
                for inst in INSTRUMENTS:
                    cum[inst] *= (1 + (chg.get(inst) or 0))
            ic = st.columns(4)
            for i, inst in enumerate(INSTRUMENTS):
                with ic[i]:
                    st.metric(INST_SHORT[inst], f"{(cum[inst]-1)*100:+.2f}%")

            # ── Candlestick charts (hourly, live) ─────────────────────
            if HAS_YF and week_opens:
                st.markdown("---")
                st.markdown(
                    "##### 🕯️ Rynek live — świece godzinowe (ostatnie 7 dni)  "
                    "&nbsp;&nbsp;🔵 otwarcie tygodnia &nbsp; 🟢/🔴 kurs live &nbsp; — &nbsp;"
                    "**odśw. co 5 min**"
                )
                candlestick_fragment(week_opens)
            elif HAS_YF:
                st.markdown("---")
                st.info("Wykresy świecowe pojawią się gdy tydzień jest otwarty z cenami otwarcia.")

            with st.expander("📊 Tabela cen tygodniowych"):
                price_rows = []
                for week in [w for w in data["weeks"]
                             if w.get("completed") and (w.get("prices") or {}).get("close")]:
                    chg = price_changes(week["prices"])
                    op  = (week.get("prices") or {}).get("open") or {}
                    cl  = (week.get("prices") or {}).get("close") or {}
                    price_rows.append({
                        "Tydzień":         week["label"],
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
                    st.dataframe(pd.DataFrame(price_rows), use_container_width=True,
                                 hide_index=True)
        else:
            st.info("Wykres pojawi się po rozliczeniu pierwszego tygodnia.")

    with tab_rank:
        if n_done >= 1:
            live_ranking_fragment(
                hist, bench, groups_meta,
                open_wk_pos if week_is_live else None,
                week_opens  if week_is_live else None,
            )
        else:
            st.info("Ranking pojawi się po rozliczeniu pierwszego tygodnia.")

    with tab_pos:
        show_positions_tab(data, hist)

    with tab_admin:
        admin_panel(data, sha)


main()
