"""Matplotlib figures. Each returns a Figure and the caller closes it."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Rectangle

from display import (ACCENT, GRID, INK, MUTED, QUAD_BAD, QUAD_GOOD,
                     QUAD_MIXED_A, QUAD_MIXED_B)


def short_name(name):
    """'Batter, Bob' becomes 'Batter B.' so teammates sharing a surname stay distinct."""
    parts = str(name).split(",")
    if len(parts) > 1 and parts[1].strip():
        return f"{parts[0].strip()} {parts[1].strip()[:1]}."
    parts = str(name).split()
    if len(parts) > 1:
        return f"{parts[0][:1]}. {parts[-1]}"
    return str(name)


def _style(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def quadrant_chart(df, x_col, y_col, x_cut, y_cut, x_low_good, y_low_good,
                   x_label, y_label, quad_map, highlight=None, title=None):
    """Scatter with cutoff lines. Both axes are oriented so good is right and up."""
    quad_colors = {
        quad_map[(True, True)]: QUAD_GOOD, quad_map[(False, True)]: QUAD_MIXED_A,
        quad_map[(True, False)]: QUAD_MIXED_B, quad_map[(False, False)]: QUAD_BAD,
    }
    xs = pd.to_numeric(df[x_col], errors="coerce")
    ys = pd.to_numeric(df[y_col], errors="coerce")

    def bounds(vals, cut):
        lo, hi = min(vals.min(), cut), max(vals.max(), cut)
        pad = (hi - lo) * 0.12 or 1.0
        return lo - pad, hi + pad

    x_lo, x_hi = bounds(xs, x_cut)
    y_lo, y_hi = bounds(ys, y_cut)
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    x_good = (x_lo, x_cut) if x_low_good else (x_cut, x_hi)
    x_bad = (x_cut, x_hi) if x_low_good else (x_lo, x_cut)
    y_good = (y_lo, y_cut) if y_low_good else (y_cut, y_hi)
    y_bad = (y_cut, y_hi) if y_low_good else (y_lo, y_cut)
    for (xa, xb), (ya, yb), color in [
        (x_good, y_good, QUAD_GOOD), (x_bad, y_good, QUAD_MIXED_A),
        (x_good, y_bad, QUAD_MIXED_B), (x_bad, y_bad, QUAD_BAD),
    ]:
        ax.add_patch(Rectangle((xa, ya), xb - xa, yb - ya, facecolor=color,
                               alpha=0.10, linewidth=0, zorder=1))

    ax.scatter(xs, ys, c=[quad_colors[q] for q in df["QUADRANT"]], s=70,
               edgecolor="white", linewidth=1.5, zorder=3)
    if highlight is not None:
        picked = df["PLAYER"] == highlight
        if picked.any():
            ax.scatter(xs[picked], ys[picked], s=240, facecolors="none",
                       edgecolors=INK, linewidths=2, zorder=6)
    for name, x, y in zip(df["PLAYER"], xs, ys):
        ax.annotate(short_name(name), (x, y), xytext=(5, 4), textcoords="offset points",
                    fontsize=7, color=INK, zorder=4)

    ax.axvline(x_cut, color=INK, linestyle="--", linewidth=1, zorder=2)
    ax.axhline(y_cut, color=INK, linestyle="--", linewidth=1, zorder=2)
    ax.set_xlim((x_hi, x_lo) if x_low_good else (x_lo, x_hi))
    ax.set_ylim((y_hi, y_lo) if y_low_good else (y_lo, y_hi))
    ax.set_xlabel(x_label + (" (lower is better)" if x_low_good else " (higher is better)"),
                  color=MUTED, fontsize=9)
    ax.set_ylabel(y_label + (" (lower is better)" if y_low_good else " (higher is better)"),
                  color=MUTED, fontsize=9)
    for cx, cy, ha, va, text, color in [
        (0.98, 0.97, "right", "top", quad_map[(True, True)], QUAD_GOOD),
        (0.02, 0.97, "left", "top", quad_map[(False, True)], "#9a6b00"),
        (0.98, 0.03, "right", "bottom", quad_map[(True, False)], QUAD_MIXED_B),
        (0.02, 0.03, "left", "bottom", quad_map[(False, False)], QUAD_BAD),
    ]:
        ax.text(cx, cy, text, transform=ax.transAxes, ha=ha, va=va,
                fontsize=9, fontweight="bold", color=color, zorder=5)
    if title:
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=INK)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    return fig


def reliability_chart(stats: dict, title: str):
    """Horizontal bars, full-season reliability per stat. Longer means more skill."""
    items = sorted(((k, v["season_r"]) for k, v in stats.items() if v["season_r"] == v["season_r"]),
                   key=lambda kv: kv[1])
    fig, ax = plt.subplots(figsize=(6, 3.4))
    names = [k for k, _ in items]
    vals = [max(v, 0) for _, v in items]
    bars = ax.barh(names, vals, color=[QUAD_GOOD if v >= 0.6 else "#9ca3af" for v in vals],
                   height=0.62)
    for b, (_, v) in zip(bars, items):
        ax.text(max(b.get_width(), 0) + 0.015, b.get_y() + b.get_height() / 2,
                f"{v:.2f}", va="center", fontsize=8, color=INK)
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("Reliability over a season (1.0 = pure skill, 0 = pure noise)",
                  color=MUTED, fontsize=8)
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    fig.tight_layout()
    return fig


def team_bars(rows: pd.DataFrame, col: str, title: str, fmt: str, center: float,
              highlight: str | None = None, sort_ascending: bool = True,
              xlabel: str | None = None):
    """One bar per team around a league reference line, the highlighted team in red."""
    df = rows.sort_values(col, ascending=sort_ascending)
    fig, ax = plt.subplots(figsize=(5.6, 3.3))
    colors = [ACCENT if t == highlight else "#9ca3af" for t in df["TEAM"]]
    bars = ax.barh(df["TEAM"], df[col] - center, left=center, color=colors, height=0.62)
    for b, v in zip(bars, df[col]):
        side = 1 if v >= center else -1
        ax.text(v + side * abs(df[col] - center).max() * 0.02, b.get_y() + b.get_height() / 2,
                format(v, fmt), va="center", ha="left" if side > 0 else "right",
                fontsize=8, color=INK)
    ax.axvline(center, color=INK, linewidth=1)
    span = abs(df[col] - center).max() * 1.35 or 1
    ax.set_xlim(center - span, center + span)
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK)
    if xlabel:
        ax.set_xlabel(xlabel, color=MUTED, fontsize=8)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    fig.tight_layout()
    return fig


def era_fip_chart(pit: pd.DataFrame, highlight: str | None = None, title: str = "ERA against FIP"):
    """Pitchers above the diagonal have an ERA worse than their peripherals say."""
    d = pit.dropna(subset=["ERA", "FIP"])
    fig, ax = plt.subplots(figsize=(5.2, 3.9))
    lo, hi = min(d["ERA"].min(), d["FIP"].min()) - 0.5, max(d["ERA"].max(), d["FIP"].max()) + 0.5
    ax.plot([lo, hi], [lo, hi], color=INK, linewidth=1, linestyle="--", zorder=1)
    ax.scatter(d["FIP"], d["ERA"], s=46, color="#9ca3af", edgecolor="white",
               linewidth=1.2, zorder=3)
    if highlight is not None:
        pick = d[d["PLAYER"] == highlight]
        ax.scatter(pick["FIP"], pick["ERA"], s=110, color=ACCENT, edgecolor="white",
                   linewidth=1.5, zorder=5)
    gap = (d["ERA"] - d["FIP"])
    for idx in list(gap.nlargest(2).index) + list(gap.nsmallest(2).index):
        r = d.loc[idx]
        ax.annotate(short_name(r["PLAYER"]), (r["FIP"], r["ERA"]), xytext=(5, 4),
                    textcoords="offset points", fontsize=7, color=INK)
    ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_xlabel("FIP (what his strikeouts, walks and homers say)", color=MUTED, fontsize=8)
    ax.set_ylabel("ERA (what happened)", color=MUTED, fontsize=8)
    ax.text(0.03, 0.96, "ERA worse than FIP", transform=ax.transAxes, fontsize=8,
            color=QUAD_BAD, va="top", fontweight="bold")
    ax.text(0.97, 0.04, "ERA better than FIP", transform=ax.transAxes, fontsize=8,
            color=QUAD_GOOD, ha="right", fontweight="bold")
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK)
    _style(ax)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    fig.tight_layout()
    return fig


def reliability_panel(hit_stats: dict, pit_stats: dict, n_hit: int, n_pit: int):
    """Hitters and pitchers side by side in one figure, so the page carries one chart."""
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 2.9), sharex=True)
    for ax, stats, title in ((axes[0], hit_stats, f"Hitters (n = {n_hit})"),
                             (axes[1], pit_stats, f"Pitchers (n = {n_pit})")):
        items = sorted(((k, v["season_r"]) for k, v in stats.items()
                        if v["season_r"] == v["season_r"]), key=lambda kv: kv[1])
        vals = [max(v, 0) for _, v in items]
        bars = ax.barh([k for k, _ in items], vals,
                       color=[QUAD_GOOD if v >= 0.6 else "#9ca3af" for v in vals], height=0.62)
        for b, (_, v) in zip(bars, items):
            ax.text(max(b.get_width(), 0) + 0.015, b.get_y() + b.get_height() / 2,
                    f"{v:.2f}", va="center", fontsize=7, color=INK)
        ax.set_xlim(0, 1.05)
        ax.set_title(title, loc="left", fontsize=9, fontweight="bold", color=INK)
        _style(ax)
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=GRID, linewidth=0.6)
    fig.supxlabel("Reliability over a season (1.0 is pure skill, 0 is pure noise)",
                  color=MUTED, fontsize=8)
    fig.tight_layout()
    return fig
