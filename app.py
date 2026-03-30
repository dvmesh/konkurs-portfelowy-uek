"""
Konkurs Portfelowy UEK 2025
Streamlit web application – public ranking + admin panel
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json, base64, requests
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Konkurs Portfelowy | UEK 2025",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
/* ---- general ---- */
[data-testid="stAppViewContainer"] { background: #0d1117; }
[data-testid="stHeader"] { background: transparent; }
section[data-testid="stSidebar"] { background: #161b22; }

/* ---- metric cards ---- */
[data-testid="stMetric"] {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 0.6rem 1rem 0.4rem;
}
[data-testid="stMetricValue"] { font-size: 1.4rem; }

/* ---- tab bar ---- */
button[data-baseweb="tab"] { font-size: 0.95rem; font-weight: 600; }

/* ---- dataframe header ---- */
thead tr th { background: #161b22 !important; }

/* ---- pending banner ---- */
.pending-box {
    background: #1c1600;
    border: 1px solid #d29922;
    border-radius: 8px;
    padding: 1rem 1.4rem;
    margin-bottom: 1rem;
}
.rank-number { font-weight: 700; font-size: 1rem; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

INSTRUMENTS = ["SPX", "XAUUSD", "BOND10Y", "EURUSD"]
INST_LABELS = {
    "SPX":     "S&P 500 (^SPX)",
    "XAUUSD":  "Złoto (XAU/USD)",
    "BOND10Y": "Obligacje 10Y USA",
    "EURUSD":  "EUR/USD",
}
INST_SHORT = {"SPX": "SPX", "XAUUSD": "Złoto", "BOND10Y": "Obligacje", "EURUSD": "EUR/USD"}
MEDALS = ["🥇", "🥈", "🥉"]

GROUP_ORDER = [
    "Grupa 1","Grupa 2","Grupa 3","Grupa 4","Grupa 5",
    "Grupa 6","Grupa 7","Grupa 8","Grupa 9","Grupa 10",
    "Grupa 11","Grupa 12","Grupa 13","Grupa 14","Grupa 15",
    "Grupa A","Grupa B","Grupa C","Grupa D","Grupa E",
    "Grupa F","Grupa G","Grupa H","Grupa I","Grupa J",
    "Grupa K","Grupa L","Grupa M","Grupa N",
]

# ═══════════════════════════════════════════════════════════════════════
# DATA LAYER  (GitHub API with local fallback)
# ═══════════════════════════════════════════════════════════════════════

def _gh_headers():
    token = st.secrets.get("github_token", "")
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}


@st.cache_data(ttl=30, show_spinner="Ładowanie danych…")
def load_data():
    repo = st.secrets.get("github_repo", "")
    if repo:
        url = f"https://api.github.com/repos/{repo}/contents/data.json"
        try:
            r = requests.get(url, headers=_gh_headers(), timeout=10)
            if r.ok:
                j = r.json()
                content = base64.b64decode(j["content"]).decode("utf-8")
                return json.loads(content), j["sha"]
        except Exception:
            pass
    # local fallback (development)
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return {}, None


def save_data(data: dict, sha):
    """Write data back to GitHub (or local file for dev)."""
    repo = st.secrets.get("github_repo", "")
    if repo and sha:
        url = f"https://api.github.com/repos/{repo}/contents/data.json"
        content = base64.b64encode(
            json.dumps(data, ensure_ascii=False, indent=2).encode()
        ).decode()
        payload = {
            "message": f"update data [{datetime.now().strftime('%Y-%m-%d %H:%M')}]",
            "content": content,
            "sha": sha,
            "committer": {"name": "KonkursBot", "email": "bot@konkurs.pl"},
        }
        try:
            r = requests.put(url, headers=_gh_headers(), json=payload, timeout=15)
            if r.ok:
                load_data.clear()
                return True, "Zapisano do GitHub ✓"
            return False, f"GitHub API error {r.status_code}: {r.text[:200]}"
        except Exception as e:
            return False, f"Błąd sieci: {e}"
    # local fallback
    try:
        with open("data.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        load_data.clear()
        return True, "Zapisano lokalnie ✓"
    except Exception as e:
        return False, f"Błąd zapisu: {e}"

# ═══════════════════════════════════════════════════════════════════════
# COMPUTATION
# ═══════════════════════════════════════════════════════════════════════

def price_changes(prices: dict) -> dict:
    """Return % change per instrument (None if data missing)."""
    op = prices.get("open") or {}
    cl = prices.get("close") or {}
    return {
        inst: (cl[inst] / op[inst] - 1) if (op.get(inst) and cl.get(inst)) else None
        for inst in INSTRUMENTS
    }


def portfolio_value(start: float, positions: dict, changes: dict) -> float:
    """
    Excel formula (reproduced exactly):
        contribution_i = ABS(pos_i) + pos_i * change_i
        free_cash      = start - SUM(ABS(pos_i))
        result         = free_cash + SUM(contribution_i)
    """
    pos = {i: (positions.get(i) or 0) for i in INSTRUMENTS}
    allocated = sum(abs(pos[i]) for i in INSTRUMENTS)
    free = start - allocated
    total = free
    for inst in INSTRUMENTS:
        chg = changes.get(inst)
        p = pos[inst]
        total += abs(p) + p * (chg if chg is not None else 0)
    return total


def benchmark_value(start: float, changes: dict) -> float:
    """4 × 25 % equal-weight long portfolio."""
    # 25 % long in each → total = 25*(1+c1) + 25*(1+c2) + 25*(1+c3) + 25*(1+c4)
    # missing instrument treated as 0 change
    avg = sum((changes.get(i) or 0) for i in INSTRUMENTS) / 4
    return start * (1 + avg)


def build_history(data: dict):
    """
    Returns
    -------
    hist   : {group: [100, v1, v2, …]}  one value per completed week + start
    bench  : [100, b1, b2, …]
    labels : ["Start", "16.03–20.03", …]
    """
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

# ═══════════════════════════════════════════════════════════════════════
# CHART
# ═══════════════════════════════════════════════════════════════════════

def build_chart(hist, bench, labels, groups_meta):
    fig = go.Figure()

    final = {g: v[-1] for g, v in hist.items()}
    ranked = sorted(final.items(), key=lambda x: x[1], reverse=True)
    top3   = [g for g, _ in ranked[:3]]
    top_colors = ["#FFD700", "#C0C0C0", "#CD7F32"]

    # ── all non-top groups (thin gray) ─────────────────────────────────
    for g, vals in hist.items():
        if g in top3:
            continue
        yr = groups_meta.get(g, {}).get("year", "")
        fig.add_trace(go.Scatter(
            x=labels, y=vals,
            name=g,
            mode="lines",
            line=dict(color="rgba(140,150,170,0.25)", width=1),
            hovertemplate=f"<b>{g}</b> (Rok {yr})<br>%{{x}}: %{{y:.3f}} jp<extra></extra>",
        ))

    # ── top 3 highlighted ──────────────────────────────────────────────
    for idx, g in enumerate(top3):
        yr = groups_meta.get(g, {}).get("year", "")
        fig.add_trace(go.Scatter(
            x=labels, y=hist[g],
            name=f"{MEDALS[idx]} {g}",
            mode="lines+markers",
            line=dict(color=top_colors[idx], width=2.5),
            marker=dict(size=7),
            hovertemplate=f"<b>{MEDALS[idx]} {g}</b> (Rok {yr})<br>%{{x}}: %{{y:.3f}} jp<extra></extra>",
        ))

    # ── contest average ────────────────────────────────────────────────
    avg_vals = [
        sum(hist[g][i] for g in hist) / len(hist)
        for i in range(len(labels))
    ]
    fig.add_trace(go.Scatter(
        x=labels, y=avg_vals,
        name="⌀ Średnia konkursu",
        mode="lines+markers",
        line=dict(color="#4A9EFF", width=2.5, dash="dot"),
        marker=dict(size=7, symbol="diamond"),
        hovertemplate="<b>Średnia konkursu</b><br>%{x}: %{y:.3f} jp<extra></extra>",
    ))

    # ── benchmark ──────────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=labels, y=bench,
        name="📊 Benchmark 4×25%",
        mode="lines+markers",
        line=dict(color="#FF6B35", width=2.5, dash="dash"),
        marker=dict(size=7, symbol="square"),
        hovertemplate="<b>Benchmark 4×25%</b><br>%{x}: %{y:.3f} jp<extra></extra>",
    ))

    # ── 100-line ───────────────────────────────────────────────────────
    fig.add_hline(y=100, line_dash="dot",
                  line_color="rgba(255,255,255,0.15)", line_width=1)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(13,17,23,0.6)",
        font=dict(family="Inter, sans-serif", size=12, color="#c9d1d9"),
        legend=dict(
            x=1.01, y=1, xanchor="left",
            bgcolor="rgba(22,27,34,0.9)",
            bordercolor="#30363d", borderwidth=1,
            font=dict(size=11),
        ),
        xaxis=dict(gridcolor="#21262d", linecolor="#30363d", title=""),
        yaxis=dict(gridcolor="#21262d", linecolor="#30363d",
                   title="Wartość portfela (j.p.)", tickformat=".2f"),
        hovermode="x unified",
        height=460,
        margin=dict(l=60, r=220, t=20, b=40),
    )
    return fig

# ═══════════════════════════════════════════════════════════════════════
# RANKING TABLE
# ═══════════════════════════════════════════════════════════════════════

def build_ranking_df(hist, bench, groups_meta):
    bench_current = bench[-1]
    rows = []
    for g, vals in hist.items():
        meta    = groups_meta.get(g, {})
        current = vals[-1]
        prev    = vals[-2] if len(vals) > 1 else current
        rows.append(dict(
            group=g,
            year=meta.get("year", "?"),
            members=", ".join(meta.get("members", [])),
            val=current,
            week_chg=current - prev,
            total_chg=current - 100,
            vs_bench=current - bench_current,
        ))

    rows.sort(key=lambda r: r["val"], reverse=True)

    result = []
    for i, r in enumerate(rows):
        result.append({
            "#":                  MEDALS[i] if i < 3 else str(i + 1),
            "Grupa":              r["group"],
            "Rok":                f"Rok {r['year']}",
            "Skład":              r["members"],
            "Portfel (j.p.)":    r["val"],
            "Tydzień Δ":         r["week_chg"],
            "Od startu Δ":       r["total_chg"],
            "vs Benchmark":      r["vs_bench"],
        })
    return pd.DataFrame(result)

# ═══════════════════════════════════════════════════════════════════════
# POSITIONS VIEW
# ═══════════════════════════════════════════════════════════════════════

def show_positions_tab(data, hist):
    pending   = data.get("pending_week", {})
    open_wks  = [w for w in data.get("weeks", []) if not w.get("completed")]

    # ── Waiting state ──────────────────────────────────────────────────
    if pending.get("waiting_for_positions") and not open_wks:
        st.markdown("""
<div class="pending-box">
⏳  <strong>Administrator oczekuje na nowe pozycje od prowadzącego.</strong><br>
Po otrzymaniu dyspozycji na nowy tydzień zostaną one wprowadzone do systemu.<br>
Ranking poniżej pokazuje wyniki po ostatnim rozliczonym tygodniu.
</div>""", unsafe_allow_html=True)
        return

    if not open_wks:
        st.info("Brak otwartego tygodnia – wyniki ostatniego są finalne.")
        return

    week = open_wks[-1]
    if not week.get("positions"):
        st.warning(f"⏳ Tydzień **{week['label']}** jest otwarty – oczekiwanie na pozycje.")
        return

    st.subheader(f"Pozycje na tydzień  {week['label']}")
    groups_meta = data.get("groups", {})

    # last computed portfolio values (= start values for this week)
    start_vals = {g: hist[g][-1] if g in hist else 100.0 for g in groups_meta}

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
            "Wartość portfela": round(start, 3),
        })

    df = pd.DataFrame(rows)

    def _color(val):
        try:
            v = float(val)
            if v > 0: return "color: #3fb950"
            if v < 0: return "color: #f85149"
        except (TypeError, ValueError):
            pass
        return ""

    num_cols = ["S&P 500", "Złoto", "Obligacje 10Y", "EUR/USD"]
    st.dataframe(
        df.style.map(_color, subset=num_cols),
        use_container_width=True, hide_index=True,
    )

    opens = (week.get("prices") or {}).get("open") or {}
    if opens:
        cols = st.columns(4)
        for i, inst in enumerate(INSTRUMENTS):
            with cols[i]:
                st.metric(f"Otwarcie – {INST_SHORT[inst]}", opens.get(inst, "—"))

# ═══════════════════════════════════════════════════════════════════════
# ADMIN PANEL
# ═══════════════════════════════════════════════════════════════════════

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

    st.success("✅ Zalogowano jako administrator")
    if st.button("Wyloguj"):
        st.session_state.admin_ok = False
        st.rerun()
    st.divider()

    t1, t2, t3 = st.tabs(["📅 Nowy tydzień / open prices", "📝 Wprowadź pozycje", "🏁 Zamknij tydzień"])
    with t1:
        _admin_open_week(data, sha)
    with t2:
        _admin_positions(data, sha)
    with t3:
        _admin_close_week(data, sha)


# ── sub-panels ─────────────────────────────────────────────────────────

def _admin_open_week(data, sha):
    st.subheader("Otwórz nowy tydzień")
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]
    if open_wks:
        st.info(f"Tydzień **{open_wks[-1]['label']}** jest już otwarty. "
                "Zamknij go najpierw, żeby otworzyć nowy.")
        return

    with st.form("form_open_week"):
        c1, c2 = st.columns(2)
        with c1:
            label = st.text_input("Etykieta tygodnia", placeholder="30.03 – 03.04")
        with c2:
            wstart = st.date_input("Data otwarcia (poniedziałek)")

        st.markdown("**Ceny otwarcia** (niedzielne 23:00 / poniedziałek rano)")
        cols = st.columns(4)
        opens = {}
        for i, inst in enumerate(INSTRUMENTS):
            with cols[i]:
                opens[inst] = st.number_input(
                    INST_LABELS[inst], min_value=0.0, value=0.0,
                    format="%.4f", key=f"o_{inst}"
                )
        mark_waiting = st.checkbox(
            "Zaznacz jako 'oczekiwanie na pozycje' (profesor jeszcze nie podał dyspozycji)",
            value=True
        )
        if st.form_submit_button("Otwórz tydzień ➜"):
            if not label:
                st.error("Podaj etykietę tygodnia.")
                return
            new_week = {
                "label":      label,
                "week_start": wstart.strftime("%Y-%m-%d"),
                "completed":  False,
                "prices":     {"open": opens, "close": None},
                "positions":  {},
            }
            data.setdefault("weeks", []).append(new_week)
            data["pending_week"] = {
                "label":                label,
                "week_start":           wstart.strftime("%Y-%m-%d"),
                "waiting_for_positions": mark_waiting,
            }
            ok, msg = save_data(data, sha)
            st.success(msg) if ok else st.error(msg)
            if ok:
                st.rerun()


def _admin_positions(data, sha):
    st.subheader("Pozycje grup na bieżący tydzień")
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]
    if not open_wks:
        st.info("Brak otwartego tygodnia. Najpierw otwórz nowy tydzień.")
        return

    week = open_wks[-1]
    st.markdown(f"Tydzień: **{week['label']}**")
    groups_meta     = data.get("groups", {})
    existing        = dict(week.get("positions") or {})

    year_filter = st.radio("Pokaż grupy:", ["Wszystkie", "Rok 1", "Rok 2"], horizontal=True)

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
            with st.expander(f"**{g}** (Rok {yr})  —  {members_str}"):
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

        if st.form_submit_button("💾 Zapisz wszystkie pozycje"):
            week["positions"] = new_pos
            # clear the "waiting" flag since we now have positions
            if "pending_week" in data:
                data["pending_week"]["waiting_for_positions"] = False
            ok, msg = save_data(data, sha)
            st.success(msg) if ok else st.error(msg)
            if ok:
                st.rerun()


def _admin_close_week(data, sha):
    st.subheader("Zamknij tydzień — wprowadź ceny zamknięcia")
    open_wks = [w for w in data.get("weeks", []) if not w.get("completed")]
    if not open_wks:
        st.info("Brak otwartego tygodnia do zamknięcia.")
        return

    week  = open_wks[-1]
    opens = (week.get("prices") or {}).get("open") or {}
    st.markdown(f"Zamykasz tydzień: **{week['label']}**")

    with st.form("form_close_week"):
        st.markdown("**Ceny zamknięcia (piątek wieczór)**")
        cols   = st.columns(4)
        closes = {}
        for i, inst in enumerate(INSTRUMENTS):
            with cols[i]:
                closes[inst] = st.number_input(
                    f"{INST_SHORT[inst]}\n*(otwarcie: {opens.get(inst, '—')})*",
                    min_value=0.0, value=0.0,
                    format="%.4f", key=f"c_{inst}",
                )

        if st.form_submit_button("🏁 Zamknij tydzień i oblicz wyniki"):
            week["prices"]["close"] = closes
            week["completed"] = True
            data["pending_week"] = {
                "label":                "Następny tydzień",
                "waiting_for_positions": True,
            }
            ok, msg = save_data(data, sha)
            st.success(msg) if ok else st.error(msg)
            if ok:
                st.rerun()

# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    data, sha = load_data()

    if not data:
        st.error("Nie można załadować danych. Sprawdź konfigurację połączenia.")
        return

    groups_meta          = data.get("groups", {})
    hist, bench, labels  = build_history(data)
    n_done               = len(labels) - 1   # completed weeks
    pending              = data.get("pending_week", {})
    open_wks             = [w for w in data.get("weeks", []) if not w.get("completed")]

    # ── HEADER ────────────────────────────────────────────────────────
    hcol, scol = st.columns([3, 1])
    with hcol:
        st.title("📈  Konkurs Portfelowy UEK 2025")

        if pending.get("waiting_for_positions") and not open_wks:
            st.markdown(
                "🟡 **Status:** Oczekiwanie na dyspozycje od prowadzącego  ·  "
                f"Tydzień: **{pending.get('label', '—')}**"
            )
        elif open_wks:
            st.markdown(f"🟢 **Tydzień aktywny:** {open_wks[-1]['label']}")
        elif data.get("weeks"):
            st.markdown(
                f"⚪ **Ostatni zamknięty tydzień:** {data['weeks'][-1]['label']}"
            )

    with scol:
        st.markdown(
            f"<div style='text-align:right;color:#586069;font-size:0.82rem;"
            f"padding-top:1.6rem'>"
            f"Grupy: {len(groups_meta)}  ·  Tygodnie: {n_done}<br>"
            f"Kapitał startowy: 100 j.p.</div>",
            unsafe_allow_html=True,
        )

    # ── KPI METRICS ───────────────────────────────────────────────────
    if n_done >= 1:
        final      = {g: v[-1] for g, v in hist.items()}
        sorted_g   = sorted(final.items(), key=lambda x: x[1], reverse=True)
        leader_g, leader_v = sorted_g[0]
        avg_v      = sum(final.values()) / len(final)
        bench_v    = bench[-1]
        beat_bench = sum(1 for v in final.values() if v > bench_v)

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            chg = hist[leader_g][-1] - (hist[leader_g][-2] if n_done > 1 else 100)
            st.metric("🥇 Lider", leader_g, f"{leader_v:.3f} jp ({chg:+.3f})")
        with m2:
            st.metric("⌀ Średnia konkursu", f"{avg_v:.3f} jp",
                      f"{avg_v - 100:+.3f} od startu")
        with m3:
            st.metric("📊 Benchmark 4×25%", f"{bench_v:.3f} jp",
                      f"{bench_v - 100:+.3f} od startu")
        with m4:
            st.metric("✅ Pokonało benchmark",
                      f"{beat_bench} / {len(final)} grup",
                      f"{beat_bench/len(final)*100:.0f}%")
        st.markdown("")

    # ── PENDING BANNER ────────────────────────────────────────────────
    if pending.get("waiting_for_positions") and not open_wks:
        st.markdown(
            '<div class="pending-box">⏳ <strong>Oczekiwanie na nowe pozycje.</strong> '
            "Prowadzący jeszcze nie przekazał dyspozycji. "
            "Ranking i wykresy pokazują wyniki po ostatnim zamkniętym tygodniu.</div>",
            unsafe_allow_html=True,
        )

    # ── TABS ──────────────────────────────────────────────────────────
    tab_chart, tab_rank, tab_pos, tab_admin = st.tabs([
        "📈 Historia portfeli",
        "🏆 Ranking",
        "📋 Pozycje bieżące",
        "⚙️ Admin",
    ])

    # ── TAB: CHART ────────────────────────────────────────────────────
    with tab_chart:
        if n_done >= 1:
            st.plotly_chart(
                build_chart(hist, bench, labels, groups_meta),
                use_container_width=True,
            )

            # instrument cumulative returns
            st.subheader("Łączna zmiana instrumentów od startu konkursu")
            cum = {inst: 1.0 for inst in INSTRUMENTS}
            for week in [w for w in data["weeks"] if w.get("completed") and (w.get("prices") or {}).get("close")]:
                chg = price_changes(week["prices"])
                for inst in INSTRUMENTS:
                    cum[inst] *= (1 + (chg.get(inst) or 0))
            ic = st.columns(4)
            for i, inst in enumerate(INSTRUMENTS):
                with ic[i]:
                    ret_pct = (cum[inst] - 1) * 100
                    st.metric(INST_SHORT[inst], f"{ret_pct:+.2f}%")

            # per-week price table
            with st.expander("📊 Tabela cen tygodniowych"):
                price_rows = []
                for week in [w for w in data["weeks"] if w.get("completed") and (w.get("prices") or {}).get("close")]:
                    chg = price_changes(week["prices"])
                    op  = (week.get("prices") or {}).get("open") or {}
                    cl  = (week.get("prices") or {}).get("close") or {}
                    price_rows.append({
                        "Tydzień":        week["label"],
                        "SPX (open)":     op.get("SPX"),
                        "SPX (close)":    cl.get("SPX"),
                        "SPX Δ%":         f"{(chg.get('SPX') or 0)*100:+.3f}%",
                        "Złoto (open)":   op.get("XAUUSD"),
                        "Złoto (close)":  cl.get("XAUUSD"),
                        "Złoto Δ%":       f"{(chg.get('XAUUSD') or 0)*100:+.3f}%",
                        "Bond (open)":    op.get("BOND10Y"),
                        "Bond (close)":   cl.get("BOND10Y"),
                        "Bond Δ%":        f"{(chg.get('BOND10Y') or 0)*100:+.3f}%",
                        "EUR/USD (open)": op.get("EURUSD"),
                        "EUR/USD (close)":cl.get("EURUSD"),
                        "EUR/USD Δ%":     f"{(chg.get('EURUSD') or 0)*100:+.3f}%",
                    })
                if price_rows:
                    st.dataframe(pd.DataFrame(price_rows), use_container_width=True,
                                 hide_index=True)
        else:
            st.info("Wykres pojawi się po rozliczeniu pierwszego tygodnia.")

    # ── TAB: RANKING ──────────────────────────────────────────────────
    with tab_rank:
        st.subheader("🏆 Ranking wspólny – wszystkie grupy")
        if n_done >= 1:
            df = build_ranking_df(hist, bench, groups_meta)

            def _style_val(v):
                if not isinstance(v, (int, float)):
                    return ""
                return "color:#3fb950;font-weight:700" if v > 100 else (
                       "color:#f85149" if v < 100 else "")

            def _style_delta(v):
                if not isinstance(v, (int, float)):
                    return ""
                return "color:#3fb950" if v > 0 else ("color:#f85149" if v < 0 else "")

            fmt = {
                "Portfel (j.p.)": "{:.3f}",
                "Tydzień Δ":      "{:+.3f}",
                "Od startu Δ":    "{:+.3f}",
                "vs Benchmark":   "{:+.3f}",
            }
            styled = (
                df.style
                .format(fmt)
                .map(_style_val,   subset=["Portfel (j.p.)"])
                .map(_style_delta, subset=["Tydzień Δ", "Od startu Δ", "vs Benchmark"])
            )
            st.dataframe(
                styled,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "#":             st.column_config.TextColumn("#",          width=50),
                    "Rok":           st.column_config.TextColumn("Rok",        width=70),
                    "Portfel (j.p.)":st.column_config.NumberColumn("Portfel",  format="%.3f"),
                    "Tydzień Δ":     st.column_config.NumberColumn("Tydzień Δ",format="%+.3f"),
                    "Od startu Δ":   st.column_config.NumberColumn("Od startu",format="%+.3f"),
                    "vs Benchmark":  st.column_config.NumberColumn("vs Bench", format="%+.3f"),
                    "Skład":         st.column_config.TextColumn("Skład grupy",width=300),
                },
            )

            # separate-year sub-rankings
            st.markdown("---")
            r1col, r2col = st.columns(2)
            for col, yr in zip([r1col, r2col], [1, 2]):
                with col:
                    st.subheader(f"Rok {yr}")
                    yr_df = df[df["Rok"] == f"Rok {yr}"].copy().reset_index(drop=True)
                    yr_df.insert(0, "Miejsce", range(1, len(yr_df) + 1))
                    st.dataframe(
                        yr_df[["Miejsce", "Grupa", "Portfel (j.p.)","Tydzień Δ"]]
                            .style.format({
                                "Portfel (j.p.)": "{:.3f}",
                                "Tydzień Δ":      "{:+.3f}",
                            }),
                        use_container_width=True,
                        hide_index=True,
                    )
        else:
            st.info("Ranking pojawi się po rozliczeniu pierwszego tygodnia.")

    # ── TAB: POSITIONS ────────────────────────────────────────────────
    with tab_pos:
        show_positions_tab(data, hist)

    # ── TAB: ADMIN ────────────────────────────────────────────────────
    with tab_admin:
        admin_panel(data, sha)


main()
