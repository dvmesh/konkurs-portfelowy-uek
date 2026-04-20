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
    page_title="Konkurs Portfelowy | Rynki Finansowe | UEK | 2026",
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

/* --- MOBILE (≤ 768px) --- */
@media (max-width: 768px) {
    h1 { font-size: 1.35rem !important; line-height: 1.2 !important; }
    h2 { font-size: 1.1rem !important; }
    h3 { font-size: 1rem !important; }
    [data-testid="stMetricValue"] { font-size: 1rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.72rem !important; }
    .stTabs [data-baseweb="tab"] {
        font-size: 0.75rem !important;
        padding: 0.35rem 0.5rem !important;
    }
    .ticker-card  { padding: 0.35rem 0.4rem !important; }
    .ticker-name  { font-size: 0.62rem !important; }
    .ticker-price { font-size: 0.95rem !important; }
    .ticker-green, .ticker-red, .ticker-gray { font-size: 0.7rem !important; }
    .pending-box { padding: 0.6rem 0.8rem !important; font-size: 0.85rem !important; }
    .block-container { padding-top: 1rem !important; padding-bottom: 1rem !important; }
}
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


@st.cache_data(ttl=900, show_spinner=False)
def fetch_weekly_bounds_yf(inst: str, week_start_iso: str):
    """Return (open_price, close_price) dla tygodnia [ws, ws+7).

    Fallbacki:
      - brak daily baru w tym tygodniu (np. poniedziałek premarket, weekend) →
        bierzemy ostatni dostępny close z 14 dni wstecz jako open-proxy
      - brak close (tydzień w trakcie) → ostatni dostępny close lub live_price
    """
    if not HAS_YF or not week_start_iso:
        return None, None
    ticker = YF_TICKERS.get(inst)
    if not ticker:
        return None, None
    try:
        from datetime import datetime as _dt, timedelta as _td
        ws = _dt.strptime(week_start_iso, "%Y-%m-%d").date()
        end = ws + _td(days=7)
        df = yf.download(ticker,
                         start=ws.strftime("%Y-%m-%d"),
                         end=end.strftime("%Y-%m-%d"),
                         interval="1d", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex) if df is not None else False:
            df.columns = [c[0] for c in df.columns]

        open_px  = None
        close_px = None
        if df is not None and not df.empty:
            open_px  = float(df["Open"].iloc[0])
            close_px = float(df["Close"].iloc[-1])

        # fallback: jeśli daily bar nie istnieje w tym tygodniu, sięgnij do wcześniejszych 14 dni
        if open_px is None:
            back = yf.download(ticker,
                               start=(ws - _td(days=14)).strftime("%Y-%m-%d"),
                               end=ws.strftime("%Y-%m-%d"),
                               interval="1d", auto_adjust=True, progress=False)
            if isinstance(back.columns, pd.MultiIndex) if back is not None else False:
                back.columns = [c[0] for c in back.columns]
            if back is not None and not back.empty:
                open_px = float(back["Close"].iloc[-1])  # ostatni znany close jako proxy

        # dla close: jeśli wciąż brak, weź fast_info.last_price
        if close_px is None:
            try:
                close_px = float(yf.Ticker(ticker).fast_info.last_price)
            except Exception:
                pass

        return open_px, close_px
    except Exception:
        return None, None


def effective_prices(week: dict):
    """Merge manual prices from data.json with yfinance fallback.

    Returns (prices_dict, sources) where:
      prices_dict = {"open": {inst: value|None}, "close": {inst: value|None}}
      sources     = {"open": {inst: "manual"|"yfinance"|"missing"}, "close": {...}}
    """
    raw     = week.get("prices") or {}
    raw_op  = raw.get("open")  or {}
    raw_cl  = raw.get("close") or {}
    ws_iso  = week.get("week_start")

    opens, closes = {}, {}
    sources = {"open": {}, "close": {}}

    # decide which instruments need yfinance
    need_yf = {}
    for inst in INSTRUMENTS:
        o_m = raw_op.get(inst)
        c_m = raw_cl.get(inst)
        need_yf[inst] = (not o_m) or (not c_m)

    yf_cache = {}
    for inst in INSTRUMENTS:
        if need_yf[inst]:
            yf_cache[inst] = fetch_weekly_bounds_yf(inst, ws_iso)
        else:
            yf_cache[inst] = (None, None)

    for inst in INSTRUMENTS:
        o_m = raw_op.get(inst)
        c_m = raw_cl.get(inst)
        yo, yc = yf_cache[inst]

        if o_m:
            opens[inst] = o_m
            sources["open"][inst] = "manual"
        elif yo is not None:
            opens[inst] = yo
            sources["open"][inst] = "yfinance"
        else:
            opens[inst] = None
            sources["open"][inst] = "missing"

        if c_m:
            closes[inst] = c_m
            sources["close"][inst] = "manual"
        elif yc is not None:
            closes[inst] = yc
            sources["close"][inst] = "yfinance"
        else:
            closes[inst] = None
            sources["close"][inst] = "missing"

    return {"open": opens, "close": closes}, sources


def week_is_provisional(sources: dict) -> bool:
    """True if any effective price came from yfinance (not manual)."""
    for side in ("open", "close"):
        for s in sources.get(side, {}).values():
            if s == "yfinance":
                return True
    return False


@st.cache_data(ttl=900, show_spinner=False)
def fetch_week_hourly_prices(week_start_iso: str):
    """Return {inst: pd.Series[Close indexed by hourly timestamp]} for the week.
    Empty dict if yfinance unavailable or all fetches failed.
    """
    if not HAS_YF or not week_start_iso:
        return {}
    from datetime import datetime as _dt, timedelta as _td
    ws = _dt.strptime(week_start_iso, "%Y-%m-%d")
    end = ws + _td(days=7)
    out = {}
    for inst, ticker in YF_TICKERS.items():
        try:
            df = yf.download(ticker,
                             start=ws.strftime("%Y-%m-%d"),
                             end=end.strftime("%Y-%m-%d"),
                             interval="1h", auto_adjust=True, progress=False)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            out[inst] = df["Close"].dropna()
        except Exception:
            continue
    return out


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


def weekly_returns(values):
    """Stopy zwrotu między kolejnymi wartościami w serii."""
    out = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev:
            out.append(values[i] / prev - 1)
    return out


def sharpe_ratio(values, rf_per_week: float = 0.0):
    """Roczny Sharpe z tygodniowych zwrotów. rf — tygodniowa stopa bez ryzyka."""
    import math, statistics as _st
    rets = weekly_returns(values)
    if len(rets) < 2:
        return None
    try:
        mean  = sum(rets) / len(rets) - rf_per_week
        stdev = _st.pstdev(rets)
        if stdev == 0:
            return None
        return (mean / stdev) * math.sqrt(52)
    except Exception:
        return None


def volatility_annual(values):
    """Roczna zmienność portfela (% sd rocznie)."""
    import math, statistics as _st
    rets = weekly_returns(values)
    if len(rets) < 2:
        return None
    try:
        return _st.pstdev(rets) * math.sqrt(52)
    except Exception:
        return None


def benchmark_value(start: float, changes: dict) -> float:
    avg = sum((changes.get(i) or 0) for i in INSTRUMENTS) / 4
    return start * (1 + avg)


def build_hourly_history(data: dict):
    """Hourly equity curve dla wszystkich grup.

    Zwraca (timestamps, hist, bench):
      timestamps: list datetime
      hist:       {group: [floats]}
      bench:      [floats]

    Używa 1h Close per instrument z yfinance, forward-fill kiedy któryś rynek
    zamknięty. Skaluje wewnątrztygodniową trajektorię żeby końcówka zgadzała
    się z canonical_values (jeśli istnieją).
    """
    groups   = list(data.get("groups", {}).keys())
    out_ts   = []
    out_hist = {g: [] for g in groups}
    out_bench = []

    state = {g: 100.0 for g in groups}
    bench_state = 100.0

    for week in data.get("weeks", []):
        completed = week.get("completed")
        eff, _ = effective_prices(week)
        opens = {i: eff["open"].get(i) for i in INSTRUMENTS}
        if any(v is None for v in opens.values()):
            continue
        positions = week.get("positions") or {}
        canonical = week.get("canonical_values") or {}
        ws_iso    = week.get("week_start")

        hourly = fetch_week_hourly_prices(ws_iso)
        # union timestamps from all instruments
        all_ts = sorted(set().union(
            *[set(s.index) for s in hourly.values() if s is not None and not s.empty]
        )) if hourly else []

        if not all_ts:
            # brak danych godzinowych — jeden punkt końca tygodnia jeśli completed
            if not completed:
                continue
            closes = {i: eff["close"].get(i) for i in INSTRUMENTS}
            if any(v is None for v in closes.values()):
                continue
            chg = price_changes(eff)
            new_state = {}
            for g in groups:
                pos = positions.get(g) or {}
                computed = portfolio_value(state[g], pos, chg)
                new_state[g] = float(canonical[g]) if g in canonical else computed
            new_bench = benchmark_value(bench_state, chg)
            import datetime as _dt2
            ts_end = _dt2.datetime.strptime(ws_iso, "%Y-%m-%d") + _dt2.timedelta(days=4, hours=22)
            out_ts.append(ts_end)
            for g in groups:
                out_hist[g].append(new_state[g])
            out_bench.append(new_bench)
            state = new_state
            bench_state = new_bench
            continue

        start_state = dict(state)
        start_bench = bench_state

        last_prices = dict(opens)
        week_points = []  # (ts, {g: val}, bench)

        for ts in all_ts:
            for inst in INSTRUMENTS:
                s = hourly.get(inst)
                if s is not None and ts in s.index:
                    v = s.loc[ts]
                    try:
                        if pd.notna(v):
                            last_prices[inst] = float(v)
                    except Exception:
                        pass
            chg = {i: (last_prices[i] / opens[i] - 1) for i in INSTRUMENTS}
            snap = {}
            for g in groups:
                pos = positions.get(g) or {}
                snap[g] = portfolio_value(start_state[g], pos, chg)
            week_points.append((ts, snap, benchmark_value(start_bench, chg)))

        # skalowanie do canonical (gładkie przejście)
        if completed and canonical and week_points:
            last_snap = week_points[-1][1]
            for g in groups:
                if g not in canonical:
                    continue
                target    = float(canonical[g])
                start_val = start_state[g]
                last_val  = last_snap[g]
                if abs(last_val - start_val) > 1e-9:
                    scale = (target - start_val) / (last_val - start_val)
                    for pt in week_points:
                        pt[1][g] = start_val + (pt[1][g] - start_val) * scale

        for (ts, snap, bench_snap) in week_points:
            out_ts.append(ts)
            for g in groups:
                out_hist[g].append(snap[g])
            out_bench.append(bench_snap)

        # stan na koniec tygodnia
        if week_points:
            last = week_points[-1]
            state = dict(last[1])
            bench_state = last[2]

    return out_ts, out_hist, out_bench


def build_history(data: dict):
    """Return (hist, bench, labels, provisional_flags).

    Includes every week marked completed — even if prices are incomplete,
    missing values are filled from yfinance (tryb provisional).
    provisional_flags[i] is True if labels[i]'s prices weren't fully manual.
    """
    completed = [w for w in data.get("weeks", []) if w.get("completed")]
    groups = list(data.get("groups", {}).keys())
    hist   = {g: [100.0] for g in groups}
    bench  = [100.0]
    labels = ["Start"]
    provisional_flags = [False]

    for week in completed:
        eff, sources = effective_prices(week)
        # skip week if we couldn't assemble prices at all
        if any(eff["open"].get(i) is None or eff["close"].get(i) is None for i in INSTRUMENTS):
            continue
        chg = price_changes(eff)
        labels.append(week["label"])
        provisional_flags.append(week_is_provisional(sources))
        bench.append(benchmark_value(bench[-1], chg))
        canonical = week.get("canonical_values") or {}
        for g in groups:
            pos = (week.get("positions") or {}).get(g) or {}
            computed = portfolio_value(hist[g][-1], pos, chg)
            # jeśli mamy "oficjalny" stan portfela z arkusza Excel → użyj go
            override = canonical.get(g)
            hist[g].append(float(override) if override is not None else computed)

    return hist, bench, labels, provisional_flags

def build_equity_chart(hist, bench, labels, groups_meta,
                       year_filter="Wszystkie", extra_groups=None, top_n=5,
                       hourly=False):
    """Czystszy wykres equity.

    Domyślnie:
      - top_n grup (z medalami dla 3 najlepszych) jako czytelne linie,
      - pasmo percentyli 25–75% + min/max jako rozmyty kontekst,
      - średnia + benchmark jako punkty referencyjne.
    `extra_groups` są dokładane jako wyraźne linie (np. własna grupa).
    """
    extra_groups = extra_groups or []

    # filtruj grupy po roku
    if year_filter == "Rok 1":
        hist = {g: v for g, v in hist.items() if groups_meta.get(g, {}).get("year") == 1}
    elif year_filter == "Rok 2":
        hist = {g: v for g, v in hist.items() if groups_meta.get(g, {}).get("year") == 2}

    if not hist:
        return go.Figure()

    final = {g: v[-1] for g, v in hist.items()}
    top   = [g for g, _ in sorted(final.items(), key=lambda x: x[1], reverse=True)[:top_n]]
    top_set = set(top) | set(extra_groups)

    # percentyle na "tle"
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

    # pasmo min-max (najszersze, bardzo przezroczyste)
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
    # pasmo percentyli 25–75
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
    # mediana
    fig.add_trace(go.Scatter(
        x=labels, y=p50, name="mediana", mode="lines",
        line=dict(color="rgba(200,210,225,0.5)", width=1.5, dash="dot"),
        hovertemplate="<b>mediana</b><br>%{x}: %{y:.3f}<extra></extra>",
    ))

    # benchmark + średnia zawsze widoczne
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

    # top N — 3 pierwsi mają medale + gold/silver/bronze, reszta paleta
    top_colors_medal = ["#FFD700", "#C0C0C0", "#CD7F32"]
    extra_palette    = ["#7ee787", "#ff7b72", "#d2a8ff", "#79c0ff", "#f2cc60", "#ffa657"]

    for idx, g in enumerate(top):
        yr = groups_meta.get(g, {}).get("year", "")
        if idx < 3:
            color = top_colors_medal[idx]
            name  = f"{MEDALS[idx]} {g}"
            width = 3 if not hourly else 2.2
        else:
            color = extra_palette[(idx - 3) % len(extra_palette)]
            name  = f"#{idx+1} {g}"
            width = 2 if not hourly else 1.6
        fig.add_trace(go.Scatter(
            x=labels, y=hist[g], name=name, mode=mode_main,
            line=dict(color=color, width=width),
            marker=dict(size=7) if not hourly else None,
            hovertemplate=f"<b>{name}</b> (Rok {yr})<br>%{{x}}: %{{y:.3f}}<extra></extra>",
        ))

    # dodatkowe grupy (np. własna)
    highlight_palette = ["#58a6ff", "#bc8cff", "#ffa657", "#56d364"]
    for i, g in enumerate(extra_groups):
        if g in top_set and g in top:
            continue  # już jest w top
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
            orientation="h", y=-0.18, x=0, xanchor="left",
            bgcolor="rgba(22,27,34,0.9)",
            bordercolor="#30363d", borderwidth=1, font=dict(size=11),
        ),
        xaxis=dict(gridcolor="#21262d", linecolor="#30363d"),
        yaxis=dict(gridcolor="#21262d", linecolor="#30363d",
                   title="Wartość portfela (j.p.)", tickformat=".2f"),
        hovermode="x unified", height=460,
        margin=dict(l=60, r=30, t=20, b=100),
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
            sharpe=sharpe_ratio(vals),
            vol=volatility_annual(vals),
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
            "Sharpe (roczny)":    r["sharpe"],
            "Zmienność (%)":      (r["vol"] * 100) if r["vol"] is not None else None,
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
        '<span class="live-badge">LIVE</span>' if is_live
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
        "Sharpe (roczny)":   lambda x: f"{x:.2f}" if x is not None and str(x) != "nan" else "—",
        "Zmienność (%)":     lambda x: f"{x:.1f}" if x is not None and str(x) != "nan" else "—",
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
            "Live (j.p.)":        st.column_config.TextColumn("Live",        width=100),
            "Tydzień Δ":          st.column_config.NumberColumn("Tyg. Δ",    format="%+.3f"),
            "Od startu Δ":        st.column_config.NumberColumn("Od startu", format="%+.3f"),
            "vs Benchmark":       st.column_config.NumberColumn("vs Bench",  format="%+.3f"),
            "Sharpe (roczny)":    st.column_config.TextColumn("Sharpe",      width=80,
                                    help="Roczny Sharpe ratio z tygodniowych zwrotów (rf=0)."),
            "Zmienność (%)":      st.column_config.TextColumn("Vol %",       width=80,
                                    help="Roczna zmienność (sd tygodniowych zwrotów × √52)."),
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

    with st.expander("🎯 Zawodnicy tygodnia (top 3 per tydzień)"):
        weekly_rows = []
        all_labels = list(zip(range(len(hist[next(iter(hist))])), ))  # placeholder
        # iteruj po tygodniach (indeks 1..n, bo 0 to Start)
        n_weeks = len(next(iter(hist.values())))
        for wi in range(1, n_weeks):
            deltas = [(g, hist[g][wi] - hist[g][wi - 1]) for g in hist]
            deltas.sort(key=lambda x: x[1], reverse=True)
            top3 = deltas[:3]
            weekly_rows.append({
                "Tydzień":       f"#{wi}",
                "🥇 Grupa":      top3[0][0] if len(top3) > 0 else "—",
                "🥇 Δ":          f"{top3[0][1]:+.3f}" if len(top3) > 0 else "—",
                "🥈 Grupa":      top3[1][0] if len(top3) > 1 else "—",
                "🥈 Δ":          f"{top3[1][1]:+.3f}" if len(top3) > 1 else "—",
                "🥉 Grupa":      top3[2][0] if len(top3) > 2 else "—",
                "🥉 Δ":          f"{top3[2][1]:+.3f}" if len(top3) > 2 else "—",
            })
        if weekly_rows:
            st.dataframe(pd.DataFrame(weekly_rows),
                         use_container_width=True, hide_index=True)


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

def show_group_detail_tab(data, hist, bench, labels, groups_meta):
    st.subheader("Szczegóły grupy")
    groups = list(hist.keys())
    if not groups:
        st.info("Brak danych grup.")
        return

    default_idx = groups.index("Grupa 13") if "Grupa 13" in groups else 0
    sel = st.selectbox("Wybierz grupę", groups, index=default_idx, key="detail_group")
    vals = hist[sel]
    meta = groups_meta.get(sel, {})

    total   = vals[-1] - 100
    best_wi = max(range(1, len(vals)), key=lambda i: vals[i] - vals[i - 1]) if len(vals) > 1 else 0
    worst_wi= min(range(1, len(vals)), key=lambda i: vals[i] - vals[i - 1]) if len(vals) > 1 else 0
    beat    = sum(1 for i in range(1, len(vals))
                  if (vals[i] - vals[i-1]) > (bench[i] - bench[i-1]))
    shp     = sharpe_ratio(vals)
    vol     = volatility_annual(vals)

    m1, m2, m3, m4 = st.columns(4)
    with m1: st.metric("Total Δ", f"{total:+.3f} jp")
    with m2: st.metric("Sharpe (roczny)", f"{shp:.2f}" if shp is not None else "—")
    with m3: st.metric("Zmienność (roczna)", f"{(vol*100):.1f}%" if vol is not None else "—")
    with m4: st.metric("Pokonało bench.", f"{beat}/{len(vals)-1} tyg.")

    mbest, mworst = st.columns(2)
    with mbest:
        if len(vals) > 1:
            d = vals[best_wi] - vals[best_wi - 1]
            st.success(f"🏆 Najlepszy tydzień: **{labels[best_wi]}** ({d:+.3f} jp)")
    with mworst:
        if len(vals) > 1:
            d = vals[worst_wi] - vals[worst_wi - 1]
            st.error(f"📉 Najsłabszy tydzień: **{labels[worst_wi]}** ({d:+.3f} jp)")

    # wykres: tylko ta grupa + benchmark + średnia
    import plotly.graph_objects as _go
    avg_vals = [sum(v[i] for v in hist.values()) / len(hist) for i in range(len(labels))]
    fig = _go.Figure()
    fig.add_trace(_go.Scatter(x=labels, y=bench, name="benchmark",
                              line=dict(color="#FF6B35", width=2, dash="dash")))
    fig.add_trace(_go.Scatter(x=labels, y=avg_vals, name="średnia",
                              line=dict(color="#4A9EFF", width=2, dash="dot")))
    fig.add_trace(_go.Scatter(x=labels, y=vals, name=sel,
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

    # tabela pozycji per tydzień + contribution
    st.markdown("#### Pozycje i wkład per tydzień")
    rows = []
    for wi, week in enumerate([w for w in data.get("weeks", []) if w.get("completed")]):
        eff, _ = effective_prices(week)
        if any(eff["open"].get(i) is None or eff["close"].get(i) is None for i in INSTRUMENTS):
            continue
        chg = price_changes(eff)
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

    st.caption(f"Skład: **{', '.join(meta.get('members', []))}** · "
               f"Rok {meta.get('year', '?')}")


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
    st.header("Panel administratora")

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

    st.success("Zalogowano")
    if st.button("Wyloguj"):
        st.session_state.admin_ok = False
        st.rerun()
    st.divider()

    t1, t2, t3, t4 = st.tabs([
        "Otwórz tydzień", "Pozycje", "Zamknij tydzień", "Uzupełnij ceny oficjalne",
    ])
    with t1:
        _admin_open_week(data, sha)
    with t2:
        _admin_positions(data, sha)
    with t3:
        _admin_close_week(data, sha)
    with t4:
        _admin_update_prices(data, sha)


def _admin_open_week(data, sha):
    from datetime import timedelta, date
    st.subheader("Otwórz nowy tydzień")
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]
    if open_wks:
        st.info(f"Tydzień **{open_wks[-1]['label']}** już otwarty. Zamknij najpierw.")
        return

    today = date.today()
    default_monday = today + timedelta(days=(7 - today.weekday()) % 7)

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
            label = st.text_input("Etykieta", value=auto_label)

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
            if not label:
                st.error("Podaj etykietę.")
                return
            final_opens = {
                inst: (manual_opens[inst] if manual_opens[inst] > 0 else None)
                for inst in INSTRUMENTS
            }
            data.setdefault("weeks", []).append(dict(
                label=label, week_start=wstart.strftime("%Y-%m-%d"),
                completed=False,
                prices=dict(open=final_opens, close=None),
                positions={},
            ))
            data["pending_week"] = dict(
                label=label, week_start=wstart.strftime("%Y-%m-%d"),
                waiting_for_positions=True,
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
    st.markdown(f"Tydzień: **{week['label']}** &nbsp; · &nbsp; "
                "**Sprawdź, edytuj dowolną komórkę, zapisz.**",
                unsafe_allow_html=True)

    # zbuduj tabelę
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
        df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=["Grupa", "Rok", "Skład", "|alok.|"],
        column_config={
            "Grupa":   st.column_config.TextColumn("Grupa",   width=90),
            "Rok":     st.column_config.NumberColumn("Rok",   width=60, format="%d"),
            "Skład":   st.column_config.TextColumn("Skład",   width=280),
            "SPX":     st.column_config.NumberColumn("SPX",   format="%.2f"),
            "Złoto":   st.column_config.NumberColumn("Złoto", format="%.2f"),
            "Bond":    st.column_config.NumberColumn("Bond",  format="%.2f"),
            "EUR/USD": st.column_config.NumberColumn("EUR/USD", format="%.2f"),
            "|alok.|": st.column_config.NumberColumn("|alok.|", format="%.2f",
                                                    help="Suma wartości bezwzględnych "
                                                         "pozycji (widać przy zapisie)."),
        },
        key="pos_editor",
    )

    over = edited[edited.apply(
        lambda r: abs(r["SPX"]) + abs(r["Złoto"]) + abs(r["Bond"]) + abs(r["EUR/USD"]) > 100.01,
        axis=1,
    )]
    if not over.empty:
        st.warning("⚠️ Grupy z alokacją > 100: " + ", ".join(over["Grupa"].tolist()))

    if st.button("💾 Zapisz pozycje", type="primary"):
        new_pos = dict(existing)
        for _, r in edited.iterrows():
            new_pos[r["Grupa"]] = {
                "SPX":     float(r["SPX"]),
                "XAUUSD":  float(r["Złoto"]),
                "BOND10Y": float(r["Bond"]),
                "EURUSD":  float(r["EUR/USD"]),
            }
        week["positions"] = new_pos
        if "pending_week" in data:
            data["pending_week"]["waiting_for_positions"] = False
        ok, msg = save_data(data, sha)
        st.success(msg) if ok else st.error(msg)
        if ok:
            st.rerun()


def _admin_update_prices(data, sha):
    """Uzupełnij oficjalne ceny (stooq) dla tygodnia, który wcześniej był szacunkowy."""
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

    raw     = week.get("prices") or {}
    raw_op  = raw.get("open")  or {}
    raw_cl  = raw.get("close") or {}
    eff, src = effective_prices(week)

    st.markdown(f"**{week['label']}** &nbsp; start: {week.get('week_start','?')}", unsafe_allow_html=True)
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
                hint   = "" if src["open"][inst] == "manual" else f"  · yf: {eff['open'].get(inst) or '—'}"
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
                hint   = "" if src["close"][inst] == "manual" else f"  · yf: {eff['close'].get(inst) or '—'}"
                new_cl[inst] = st.number_input(
                    f"close {INST_SHORT[inst]}{hint}",
                    min_value=0.0, value=float(manual),
                    format="%.5f", key=f"up_c_{idx}_{inst}",
                )

        if st.form_submit_button("💾 Zapisz oficjalne ceny"):
            # 0 → None (nadal fallback do yfinance)
            week["prices"] = {
                "open":  {i: (new_op[i] if new_op[i] > 0 else None) for i in INSTRUMENTS},
                "close": {i: (new_cl[i] if new_cl[i] > 0 else None) for i in INSTRUMENTS},
            }
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
    st.markdown(f"Zamykasz: **{week['label']}**")
    st.caption(
        "Jeden klik → tydzień zamknięty, ceny zamknięcia ściągnięte z yfinance. "
        "Oficjalne ze stooq wpiszesz później w zakładce „Uzupełnij ceny oficjalne”."
    )

    if st.button("🏁 Zamknij tydzień (yfinance)", type="primary"):
        week["prices"]["close"] = {i: None for i in INSTRUMENTS}
        week["completed"]       = True
        data["pending_week"]    = dict(
            label="Następny tydzień", waiting_for_positions=True,
        )
        ok, msg = save_data(data, sha)
        st.success(msg) if ok else st.error(msg)
        if ok:
            st.rerun()

    with st.expander("Wpisz ręczne ceny zamknięcia (opcjonalnie)"):
        opens = (week.get("prices") or {}).get("open") or {}
        live  = fetch_live_prices() if HAS_YF else {}
        with st.form("form_close_week_manual"):
            cols   = st.columns(4)
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
                final_closes = {
                    inst: (closes[inst] if closes[inst] > 0 else None)
                    for inst in INSTRUMENTS
                }
                week["prices"]["close"] = final_closes
                week["completed"]       = True
                data["pending_week"]    = dict(
                    label="Następny tydzień", waiting_for_positions=True,
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

    groups_meta                      = data.get("groups", {})
    hist, bench, labels, prov_flags  = build_history(data)
    n_done                           = len(labels) - 1
    any_provisional                  = any(prov_flags)
    pending             = data.get("pending_week", {})
    open_wks            = [w for w in data.get("weeks", []) if not w.get("completed")]

    active_week  = open_wks[-1] if open_wks else None
    if active_week:
        eff_act, src_act = effective_prices(active_week)
        week_opens       = {i: v for i, v in eff_act["open"].items() if v}
        active_opens_src = src_act["open"]
    else:
        week_opens       = {}
        active_opens_src = {}
    open_wk_pos  = active_week.get("positions") or {} if active_week else {}
    week_is_live = bool(active_week and week_opens and open_wk_pos and HAS_YF)

    hcol, scol = st.columns([3, 1])
    with hcol:
        live_html = '<span class="live-badge">LIVE</span>' if week_is_live else ""
        st.markdown(
            f"<h1 style='margin-bottom:0'>Konkurs Portfelowy | Rynki Finansowe | UEK | 2026 {live_html}</h1>",
            unsafe_allow_html=True,
        )
        if pending.get("waiting_for_positions") and not open_wks:
            st.markdown("**Status:** Oczekiwanie na dyspozycje od prowadzącego")
        elif active_week:
            st.markdown(f"**Tydzień aktywny:** {active_week['label']}")
        elif data.get("weeks"):
            st.markdown(f"**Ostatni zamknięty:** {data['weeks'][-1]['label']}")
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

    if pending.get("waiting_for_positions") and not open_wks:
        st.markdown(
            '<div class="pending-box">⏳ <strong>Oczekiwanie na nowe pozycje.</strong> '
            "Prowadzący jeszcze nie przekazał dyspozycji. "
            "Wyniki po ostatnim zamkniętym tygodniu.</div>",
            unsafe_allow_html=True,
        )

    if any_provisional:
        prov_labels = [labels[i] for i in range(1, len(labels)) if prov_flags[i]]
        st.markdown(
            f'<div class="pending-box" style="background:#2a1f05;border-color:#d29922">'
            f'📊 <strong>Szacunek finalny.</strong> Niektóre tygodnie używają cen z '
            f'yfinance (brak oficjalnych cen ze stooq): '
            f'<em>{", ".join(prov_labels)}</em>. '
            f'Wyniki zaktualizują się gdy prowadzący wpisze oficjalne ceny.'
            f'</div>',
            unsafe_allow_html=True,
        )

    tab_chart, tab_rank, tab_live, tab_detail, tab_pos, tab_admin = st.tabs([
        "📈 Wykres",
        "🏆 Ranking",
        "🕯️ Rynek live",
        "👤 Grupa",
        "📋 Pozycje",
        "⚙️ Admin",
    ])

    with tab_rank:
        if n_done >= 1:
            live_ranking_fragment(
                hist, bench, groups_meta,
                open_wk_pos if week_is_live else None,
                week_opens  if week_is_live else None,
            )
        else:
            st.info("Ranking pojawi się po rozliczeniu pierwszego tygodnia.")

    with tab_chart:
        if n_done >= 1:
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
            for week in [w for w in data["weeks"] if w.get("completed")]:
                eff, _ = effective_prices(week)
                if any(eff["open"].get(i) is None or eff["close"].get(i) is None for i in INSTRUMENTS):
                    continue
                chg = price_changes(eff)
                for inst in INSTRUMENTS:
                    cum[inst] *= (1 + (chg.get(inst) or 0))
            ic = st.columns(4)
            for i, inst in enumerate(INSTRUMENTS):
                with ic[i]:
                    st.metric(INST_SHORT[inst], f"{(cum[inst]-1)*100:+.2f}%")

            with st.expander("Tabela cen tygodniowych"):
                price_rows = []
                for week in [w for w in data["weeks"] if w.get("completed")]:
                    eff, src = effective_prices(week)
                    if any(eff["open"].get(i) is None or eff["close"].get(i) is None for i in INSTRUMENTS):
                        continue
                    chg = price_changes(eff)
                    op  = eff["open"]
                    cl  = eff["close"]
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
                    st.dataframe(pd.DataFrame(price_rows), use_container_width=True,
                                 hide_index=True)
        else:
            st.info("Wykres pojawi się po rozliczeniu pierwszego tygodnia.")

    with tab_live:
        if not HAS_YF:
            st.warning("Zainstaluj `yfinance` aby zobaczyć rynek live.")
        else:
            if active_week:
                live_opens = week_opens
                opens_src  = active_opens_src
                banner     = None
            else:
                # brak aktywnego tygodnia od prowadzącego — podstaw bieżący pn–pt z yfinance
                from datetime import date, timedelta
                today  = date.today()
                monday = today - timedelta(days=today.weekday())
                fake_week = {
                    "week_start": monday.strftime("%Y-%m-%d"),
                    "prices":     {"open": {}, "close": {}},
                }
                eff_f, src_f = effective_prices(fake_week)
                live_opens   = {i: v for i, v in eff_f["open"].items() if v}
                opens_src    = src_f["open"]
                banner       = (
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

    with tab_detail:
        if n_done >= 1:
            show_group_detail_tab(data, hist, bench, labels, groups_meta)
        else:
            st.info("Detale grupy pojawią się po rozliczeniu pierwszego tygodnia.")

    with tab_pos:
        show_positions_tab(data, hist)

    with tab_admin:
        admin_panel(data, sha)


main()
