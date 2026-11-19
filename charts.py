"""Matplotlib figures. Each returns a Figure and the caller closes it."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from display import ACCENT, GRID, INK, MUTED, QUAD_BAD, QUAD_GOOD


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
    ax.set_xlabel("FIP", color=MUTED, fontsize=8)
    ax.set_ylabel("ERA", color=MUTED, fontsize=8)
    ax.text(0.03, 0.96, "ERA worse than FIP", transform=ax.transAxes, fontsize=8,
            color=QUAD_BAD, va="top", fontweight="bold")
    ax.text(0.97, 0.04, "ERA better than FIP", transform=ax.transAxes, fontsize=8,
            color=QUAD_GOOD, ha="right", fontweight="bold")
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color=INK)
    _style(ax)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    fig.tight_layout()
    return fig
