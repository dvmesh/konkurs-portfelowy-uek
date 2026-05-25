"""Obliczenia portfelowe: portfolio_value, benchmark, metryki ryzyka."""
from __future__ import annotations

import math
import statistics
from typing import Optional

from config import INSTRUMENTS, WEEKS_PER_YEAR


def portfolio_value(start: float, positions: dict, changes: dict) -> float:
    """Wycena portfela: long (p>0) zarabia gdy chg>0, short (p<0) zarabia gdy chg<0.

    free = start - Σ|p|  (alokacja w abs pozycji)
    total = free + Σ(|p| + p * chg)
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


def weekly_returns(values) -> list[float]:
    """Stopy zwrotu między kolejnymi wartościami w serii."""
    out: list[float] = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev:
            out.append(values[i] / prev - 1)
    return out


def sharpe_ratio(values, rf_per_week: float = 0.0) -> Optional[float]:
    """Roczny Sharpe z tygodniowych zwrotów."""
    rets = weekly_returns(values)
    if len(rets) < 2:
        return None
    try:
        mean = sum(rets) / len(rets) - rf_per_week
        stdev = statistics.pstdev(rets)
        if stdev == 0:
            return None
        return (mean / stdev) * math.sqrt(WEEKS_PER_YEAR)
    except Exception:
        return None


def volatility_annual(values) -> Optional[float]:
    """Roczna zmienność portfela (sd tygodniowych zwrotów × √52)."""
    rets = weekly_returns(values)
    if len(rets) < 2:
        return None
    try:
        return statistics.pstdev(rets) * math.sqrt(WEEKS_PER_YEAR)
    except Exception:
        return None


def max_drawdown(values) -> Optional[float]:
    """Maksymalny drawdown z serii equity. Zwraca wartość ujemną (np. -0.12 = -12%)."""
    if not values or len(values) < 2:
        return None
    peak = values[0]
    dd = 0.0
    for v in values[1:]:
        if v > peak:
            peak = v
        if peak > 0:
            dd = min(dd, v / peak - 1)
    return dd


def win_rate(values) -> Optional[float]:
    """Udział tygodni z dodatnim zwrotem."""
    rets = weekly_returns(values)
    if not rets:
        return None
    wins = sum(1 for r in rets if r > 0)
    return wins / len(rets)


def benchmark_value(start: float, changes: dict) -> float:
    """Benchmark 4×25% long: średnia ze zmian per instrument."""
    avg = sum((changes.get(i) or 0) for i in INSTRUMENTS) / len(INSTRUMENTS)
    return start * (1 + avg)


def position_summary(positions: dict) -> dict:
    """Per-grupa: alokacja long/short/abs, liczba long/short positions."""
    longs = {i: max(0.0, positions.get(i) or 0) for i in INSTRUMENTS}
    shorts = {i: max(0.0, -(positions.get(i) or 0)) for i in INSTRUMENTS}
    return {
        "long_total": sum(longs.values()),
        "short_total": sum(shorts.values()),
        "abs_total": sum(longs.values()) + sum(shorts.values()),
        "n_long": sum(1 for v in longs.values() if v > 0),
        "n_short": sum(1 for v in shorts.values() if v > 0),
        "n_zero": sum(
            1 for inst in INSTRUMENTS if not (positions.get(inst) or 0)
        ),
    }


def validate_positions(positions: dict, tolerance: float = 0.01) -> list[str]:
    """Sprawdza pozycje grupy. Zwraca listę naruszeń (pustą gdy OK).

    P0: hard-block na |sum| > 100, NaN/inf, brak instrumentu.
    """
    errors: list[str] = []
    abs_sum = 0.0
    for inst in INSTRUMENTS:
        v = positions.get(inst)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            errors.append(f"{inst}: nie-numeryczna wartość {v!r}")
            continue
        if not math.isfinite(fv):
            errors.append(f"{inst}: wartość niefinitna ({fv})")
            continue
        if abs(fv) > 100 + tolerance:
            errors.append(f"{inst}: pojedyncza pozycja > 100 ({fv:+.2f})")
        abs_sum += abs(fv)
    if abs_sum > 100 + tolerance:
        errors.append(f"|sum| = {abs_sum:.2f} > 100 (nadalokacja)")
    return errors
