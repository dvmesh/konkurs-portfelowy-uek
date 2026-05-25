"""Stałe i mapowania konkursu portfelowego UEK."""
from __future__ import annotations

INSTRUMENTS = ["SPX", "XAUUSD", "BOND10Y", "EURUSD"]

INST_LABELS = {
    "SPX":     "S&P 500",
    "XAUUSD":  "Złoto (XAU/USD)",
    "BOND10Y": "Obligacje 10Y USA",
    "EURUSD":  "EUR/USD",
}
INST_SHORT = {
    "SPX":     "SPX",
    "XAUUSD":  "Złoto",
    "BOND10Y": "Obligacje 10Y",
    "EURUSD":  "EUR/USD",
}

YF_TICKERS = {
    "SPX":     "^GSPC",
    "XAUUSD":  "GC=F",
    "BOND10Y": "^TNX",
    "EURUSD":  "EURUSD=X",
}

MEDALS = ["🥇", "🥈", "🥉"]

GROUP_ORDER = [
    "Grupa 1", "Grupa 2", "Grupa 3", "Grupa 4", "Grupa 5",
    "Grupa 6", "Grupa 7", "Grupa 8", "Grupa 9", "Grupa 10",
    "Grupa 11", "Grupa 12", "Grupa 13", "Grupa 14", "Grupa 15",
    "Grupa A", "Grupa B", "Grupa C", "Grupa D", "Grupa E",
    "Grupa F", "Grupa G", "Grupa H", "Grupa I", "Grupa J",
    "Grupa K", "Grupa L", "Grupa M", "Grupa N",
]

INST_PL_TO_KEY = {
    "SPX":     "SPX",
    "Złoto":   "XAUUSD",
    "Bond":    "BOND10Y",
    "EUR/USD": "EURUSD",
}
INST_KEY_TO_PL = {v: k for k, v in INST_PL_TO_KEY.items()}

MAX_PORTFOLIO_ALLOCATION = 100.0
ALLOCATION_TOLERANCE = 0.01
PORTFOLIO_START_VALUE = 100.0
TRADING_DAYS_PER_WEEK = 5
WEEKS_PER_YEAR = 52
