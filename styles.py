"""CSS dashboardu konkursu portfelowego UEK."""
import streamlit as st


def inject_css() -> None:
    st.markdown(
        """
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
.ended-badge {
    display: inline-block;
    background: linear-gradient(135deg, #2b1d05 0%, #3a2807 100%);
    border: 1px solid #d29922;
    color: #ffd055;
    font-size: 0.72rem;
    font-weight: 700;
    padding: 2px 9px;
    border-radius: 20px;
    letter-spacing: 0.08em;
    vertical-align: middle;
    margin-left: 8px;
}
.ended-banner {
    background: linear-gradient(135deg, #1c1600 0%, #261c08 100%);
    border: 1px solid #d29922;
    border-radius: 10px;
    padding: 0.9rem 1.2rem;
    margin: 0.4rem 0 1rem;
}
.ended-banner-small {
    background: #1c1600;
    border: 1px solid #d29922;
    color: #e6c87a;
    border-radius: 8px;
    padding: 0.55rem 0.9rem;
    margin: 0.4rem 0 0.9rem;
    font-size: 0.88rem;
}
.final-chip {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 16px;
    padding: 3px 10px;
    font-size: 0.85rem;
    color: #e6edf3;
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

.title-short { display: none; }
.title-full  { display: inline; }

@media (max-width: 768px) {
    .block-container {
        padding: 0.5rem !important;
        max-width: 100% !important;
    }
    .title-short { display: inline; }
    .title-full  { display: none; }
    h1 { font-size: 1.25rem !important; line-height: 1.15 !important; margin-bottom: 0 !important; }
    h2 { font-size: 1rem !important; }
    h3 { font-size: 0.9rem !important; }
    [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap !important;
        gap: 0.35rem !important;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        flex: 0 1 calc(50% - 0.2rem) !important;
        min-width: calc(50% - 0.2rem) !important;
        width: calc(50% - 0.2rem) !important;
    }
    [data-testid="stMetric"] {
        padding: 0.4rem 0.55rem 0.3rem !important;
    }
    [data-testid="stMetricValue"] { font-size: 0.95rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.68rem !important; }
    [data-testid="stMetricDelta"] { font-size: 0.7rem !important; }
    .stTabs [data-baseweb="tab-list"] {
        overflow-x: auto !important;
        flex-wrap: nowrap !important;
        scrollbar-width: thin !important;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 0.72rem !important;
        padding: 0.3rem 0.5rem !important;
        white-space: nowrap !important;
        min-width: auto !important;
    }
    .ticker-card  { padding: 0.3rem 0.35rem !important; }
    .ticker-name  { font-size: 0.58rem !important; }
    .ticker-price { font-size: 0.88rem !important; }
    .ticker-green, .ticker-red, .ticker-gray { font-size: 0.62rem !important; }
    .pending-box {
        padding: 0.5rem 0.7rem !important;
        font-size: 0.8rem !important;
    }
    [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
        overflow-x: auto !important;
    }
    .streamlit-expanderHeader, [data-testid="stExpander"] summary {
        font-size: 0.85rem !important;
    }
    [data-baseweb="radio"] label { font-size: 0.78rem !important; }
    [data-baseweb="tag"] { font-size: 0.72rem !important; }
    .stButton > button, .stDownloadButton > button {
        font-size: 0.82rem !important;
        padding: 0.35rem 0.7rem !important;
    }
    .stNumberInput input, .stTextInput input, .stDateInput input {
        font-size: 0.85rem !important;
        padding: 0.3rem 0.5rem !important;
    }
}

@media (max-width: 420px) {
    [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:only-of-type,
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]:nth-child(2):last-child) > [data-testid="stColumn"] {
        flex: 0 1 100% !important;
        min-width: 100% !important;
        width: 100% !important;
    }
    h1 { font-size: 1.1rem !important; }
    [data-testid="stMetricValue"] { font-size: 0.85rem !important; }
    .ticker-price { font-size: 0.8rem !important; }
}
</style>
""",
        unsafe_allow_html=True,
    )
