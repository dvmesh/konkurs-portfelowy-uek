"""Budowanie historii equity curve - tygodniowo i godzinowo.

iter_completed_weeks - DRY helper deduplikujący 4 miejsca w app.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Iterator, Tuple

import pandas as pd
import streamlit as st

from config import INSTRUMENTS, PORTFOLIO_START_VALUE
from pricing import (
    effective_prices,
    fetch_week_hourly_prices,
    price_changes,
    week_is_provisional,
)
from portfolio import benchmark_value, portfolio_value

logger = logging.getLogger("konkurs.history")


def iter_completed_weeks(data: dict) -> Iterator[Tuple[dict, dict, dict, dict]]:
    """DRY helper. Yieldy (week, eff_prices, sources, changes) tylko dla tygodni
    z kompletem cen open/close."""
    for week in data.get("weeks", []):
        if not week.get("completed"):
            continue
        eff, sources = effective_prices(week)
        if any(
            eff["open"].get(i) is None or eff["close"].get(i) is None
            for i in INSTRUMENTS
        ):
            continue
        yield week, eff, sources, price_changes(eff)


def _data_signature(data: dict) -> str:
    """Hash strukturalny - cache key dla build_history."""
    weeks = data.get("weeks", [])
    payload = []
    for w in weeks:
        payload.append({
            "ws": w.get("week_start"),
            "lbl": w.get("label"),
            "comp": w.get("completed"),
            "prices": w.get("prices"),
            "canon": w.get("canonical_values"),
            "pos_hash": hashlib.md5(
                json.dumps(w.get("positions") or {}, sort_keys=True).encode()
            ).hexdigest()[:8],
        })
    groups = sorted((data.get("groups") or {}).keys())
    return hashlib.sha256(
        json.dumps({"weeks": payload, "groups": groups}, sort_keys=True).encode()
    ).hexdigest()


@st.cache_data(ttl=120, show_spinner=False)
def _build_history_cached(sig: str, data: dict):
    return _build_history_impl(data)


def build_history(data: dict):
    """Cache'owana wersja - klucz to data_signature."""
    sig = _data_signature(data)
    return _build_history_cached(sig, data)


def _build_history_impl(data: dict):
    """Tygodniowa historia equity. Returns (hist, bench, labels, provisional_flags)."""
    groups = list(data.get("groups", {}).keys())
    hist = {g: [PORTFOLIO_START_VALUE] for g in groups}
    bench = [PORTFOLIO_START_VALUE]
    labels = ["Start"]
    provisional_flags = [False]

    for week, eff, sources, chg in iter_completed_weeks(data):
        labels.append(week["label"])
        provisional_flags.append(week_is_provisional(sources))
        bench.append(benchmark_value(bench[-1], chg))
        canonical = week.get("canonical_values") or {}
        for g in groups:
            pos = (week.get("positions") or {}).get(g) or {}
            computed = portfolio_value(hist[g][-1], pos, chg)
            override = canonical.get(g)
            hist[g].append(float(override) if override is not None else computed)

    return hist, bench, labels, provisional_flags


@st.cache_data(ttl=120, show_spinner=False)
def _build_hourly_history_cached(sig: str, data: dict):
    return _build_hourly_history_impl(data)


def build_hourly_history(data: dict):
    sig = _data_signature(data)
    return _build_hourly_history_cached(sig, data)


def _build_hourly_history_impl(data: dict):
    """Godzinowa equity curve. Returns (timestamps, hist, bench)."""
    groups = list(data.get("groups", {}).keys())
    out_ts: list = []
    out_hist = {g: [] for g in groups}
    out_bench: list = []

    state = {g: PORTFOLIO_START_VALUE for g in groups}
    bench_state = PORTFOLIO_START_VALUE

    for week in data.get("weeks", []):
        completed = week.get("completed")
        eff, _ = effective_prices(week)
        opens = {i: eff["open"].get(i) for i in INSTRUMENTS}
        if any(v is None for v in opens.values()):
            continue
        positions = week.get("positions") or {}
        canonical = week.get("canonical_values") or {}
        ws_iso = week.get("week_start")

        hourly = fetch_week_hourly_prices(ws_iso)
        all_ts = sorted(set().union(
            *[set(s.index) for s in hourly.values() if s is not None and not s.empty]
        )) if hourly else []

        if not all_ts:
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
            ts_end = datetime.strptime(ws_iso, "%Y-%m-%d") + timedelta(days=4, hours=22)
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
        week_points: list = []

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

        if completed and canonical and week_points:
            last_snap = week_points[-1][1]
            for g in groups:
                if g not in canonical:
                    continue
                target = float(canonical[g])
                start_val = start_state[g]
                last_val = last_snap[g]
                if abs(last_val - start_val) > 1e-9:
                    scale = (target - start_val) / (last_val - start_val)
                    for pt in week_points:
                        pt[1][g] = start_val + (pt[1][g] - start_val) * scale

        for (ts, snap, bench_snap) in week_points:
            out_ts.append(ts)
            for g in groups:
                out_hist[g].append(snap[g])
            out_bench.append(bench_snap)

        if week_points:
            last = week_points[-1]
            state = dict(last[1])
            bench_state = last[2]

    return out_ts, out_hist, out_bench


def cumulative_instrument_returns(data: dict) -> dict:
    """Iloczyn (1+chg) per instrument przez wszystkie completed weeks."""
    cum = {i: 1.0 for i in INSTRUMENTS}
    for _, _, _, chg in iter_completed_weeks(data):
        for inst in INSTRUMENTS:
            cum[inst] *= 1 + (chg.get(inst) or 0)
    return cum
