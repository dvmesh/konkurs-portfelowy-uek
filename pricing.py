"""Ceny instrumentów: yfinance batch download, cache, merge z manualnymi ze stooq."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd
import streamlit as st

from config import INSTRUMENTS, YF_TICKERS

try:
    import yfinance as yf
    HAS_YF = True
except ImportError:
    HAS_YF = False

logger = logging.getLogger("konkurs.pricing")


def _flatten_yf(df) -> pd.DataFrame:
    """yfinance > 0.2 zwraca MultiIndex columns dla pojedynczego tickera."""
    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    return df


def _is_sane_price(v) -> bool:
    """yfinance czasem zwraca 0.0, NaN, ujemne (split-adjust). Filtruj."""
    import math
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0


@st.cache_data(ttl=55, show_spinner=False)
def fetch_live_prices() -> dict:
    """Batch live prices przez yf.Tickers (jedna sesja HTTP dla 4 tickerów)."""
    if not HAS_YF:
        return {}
    out: dict[str, Optional[float]] = {i: None for i in INSTRUMENTS}
    try:
        tickers = " ".join(YF_TICKERS.values())
        bundle = yf.Tickers(tickers)
        for inst, tkr in YF_TICKERS.items():
            try:
                px = bundle.tickers[tkr].fast_info.last_price
                out[inst] = float(px) if px is not None else None
            except Exception:
                logger.warning("live price miss: %s", inst)
    except Exception:
        logger.exception("fetch_live_prices batch failed")
    return out


@st.cache_data(ttl=300, show_spinner=False)
def fetch_hourly_df(inst: str):
    """Godzinowy OHLCV dla pojedynczego instrumentu (7d)."""
    if not HAS_YF:
        return None
    ticker = YF_TICKERS.get(inst)
    if not ticker:
        return None
    try:
        df = yf.download(
            ticker, period="7d", interval="1h",
            auto_adjust=True, progress=False, threads=False,
        )
        return _flatten_yf(df) if df is not None and not df.empty else None
    except Exception:
        logger.exception("fetch_hourly_df failed: %s", inst)
        return None


@st.cache_data(ttl=900, show_spinner=False)
def fetch_weekly_bounds_yf(inst: str, week_start_iso: str) -> Tuple[Optional[float], Optional[float]]:
    """Zwraca (open_price, close_price) dla tygodnia [ws, ws+7).

    Fallbacki: brak daily baru → ostatni close z 14 dni wstecz jako open-proxy;
    brak close (tydzień w trakcie) → fast_info.last_price.
    """
    if not HAS_YF or not week_start_iso:
        return None, None
    ticker = YF_TICKERS.get(inst)
    if not ticker:
        return None, None
    try:
        ws = datetime.strptime(week_start_iso, "%Y-%m-%d").date()
        end = ws + timedelta(days=7)
        df = yf.download(
            ticker,
            start=ws.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d", auto_adjust=True, progress=False, threads=False,
        )
        df = _flatten_yf(df)

        open_px = None
        close_px = None
        if df is not None and not df.empty:
            try:
                v = float(df["Open"].iloc[0])
                if _is_sane_price(v):
                    open_px = v
            except (TypeError, ValueError):
                pass
            try:
                v = float(df["Close"].iloc[-1])
                if _is_sane_price(v):
                    close_px = v
            except (TypeError, ValueError):
                pass

        if open_px is None:
            back = yf.download(
                ticker,
                start=(ws - timedelta(days=14)).strftime("%Y-%m-%d"),
                end=ws.strftime("%Y-%m-%d"),
                interval="1d", auto_adjust=True, progress=False, threads=False,
            )
            back = _flatten_yf(back)
            if back is not None and not back.empty:
                open_px = float(back["Close"].iloc[-1])

        if close_px is None:
            try:
                close_px = float(yf.Ticker(ticker).fast_info.last_price)
            except Exception:
                pass
        return open_px, close_px
    except Exception:
        logger.exception("fetch_weekly_bounds_yf failed: %s %s", inst, week_start_iso)
        return None, None


@st.cache_data(ttl=900, show_spinner=False)
def fetch_week_hourly_prices(week_start_iso: str) -> dict:
    """Batch download 1h prices dla 4 instrumentów w danym tygodniu.

    Jedna sesja HTTP dla wszystkich tickerów (group_by=ticker).
    Zwraca {inst: pd.Series[Close]} (pusty dict gdy brak danych).
    """
    if not HAS_YF or not week_start_iso:
        return {}
    try:
        ws = datetime.strptime(week_start_iso, "%Y-%m-%d")
        end = ws + timedelta(days=7)
        tickers = list(YF_TICKERS.values())
        df = yf.download(
            tickers,
            start=ws.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1h", auto_adjust=True, progress=False,
            group_by="ticker", threads=True,
        )
        out: dict = {}
        if df is None or df.empty:
            return out
        for inst, tkr in YF_TICKERS.items():
            try:
                if isinstance(df.columns, pd.MultiIndex):
                    sub = df[tkr]["Close"]
                else:
                    sub = df["Close"]
                sub = sub.dropna()
                if not sub.empty:
                    out[inst] = sub
            except Exception:
                continue
        return out
    except Exception:
        logger.exception("fetch_week_hourly_prices failed for %s", week_start_iso)
        return {}


def effective_prices(week: dict) -> Tuple[dict, dict]:
    """Merge manualnych cen (stooq) z yfinance fallback.

    Zwraca (prices_dict, sources):
      prices_dict = {"open": {inst: val|None}, "close": {inst: val|None}}
      sources     = {"open": {inst: "manual"|"yfinance"|"missing"}, "close": ...}

    P0 guard: week["prices"] może być None - traktujemy jak pusty dict.
    """
    raw = week.get("prices") or {}
    raw_op = (raw.get("open") if isinstance(raw, dict) else None) or {}
    raw_cl = (raw.get("close") if isinstance(raw, dict) else None) or {}
    ws_iso = week.get("week_start")

    opens: dict = {}
    closes: dict = {}
    sources = {"open": {}, "close": {}}

    yf_cache: dict = {}
    for inst in INSTRUMENTS:
        if (not raw_op.get(inst)) or (not raw_cl.get(inst)):
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
    """True gdy choć jedna efektywna cena pochodzi z yfinance (nie ze stooq)."""
    for side in ("open", "close"):
        for s in sources.get(side, {}).values():
            if s == "yfinance":
                return True
    return False


def price_changes(prices: dict) -> dict:
    op = prices.get("open") or {}
    cl = prices.get("close") or {}
    out = {}
    for inst in INSTRUMENTS:
        o = op.get(inst)
        c = cl.get(inst)
        if _is_sane_price(o) and _is_sane_price(c):
            out[inst] = c / o - 1
        else:
            out[inst] = None
    return out


def live_changes(week_opens: dict, live_prices: dict) -> dict:
    return {
        inst: (live_prices[inst] / week_opens[inst] - 1)
              if (week_opens.get(inst) and live_prices.get(inst)) else None
        for inst in INSTRUMENTS
    }
