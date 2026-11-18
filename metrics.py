"""Turn iScore's raw season blobs into one row per player, plus derived stats.

Pure and Streamlit-free so it can be unit tested and reused by the offline
analysis in ``scripts/``. Every rate is recomputed from counts rather than
read from iScore's RATES block, so a stat means exactly one thing everywhere
(the table, the card, the PDF, the findings) and splits stay comparable to
the overall line.
"""
from __future__ import annotations

import math

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# wOBA linear weights. These are MLB weights (FanGraphs, recent seasons), not
# ALPB-specific ones, which would need play-by-play run expectancy we do not
# have. The ordering of hitters is what matters here, and it is insensitive to
# small changes in the weights. Not scaled to OBP, so the league mean is
# whatever it is rather than forced to equal league OBP.
WOBA_W = {"uBB": 0.69, "HBP": 0.72, "1B": 0.88, "2B": 1.25, "3B": 1.58, "HR": 2.03}

# Sample size at which a stat is roughly half signal, half noise (split-half
# reliability of 0.5). From Russell Carleton's stabilization work on MLB data.
# Used as the "k" in empirical Bayes shrinkage, est = (x + k*mean) / (n + k).
STABILIZE = {
    "hit_K%": 60,     # PA
    "hit_BB%": 120,   # PA
    "hit_BABIP": 820,  # balls in play
    "pit_K%": 70,     # BF
    "pit_BB%": 170,   # BF
    "pit_BABIP": 2000,  # balls in play, which is why pitcher BABIP is mostly noise
}

# Split blocks pulled from iScore, as (column prefix, path under batting/pitching).
SPLITS = {
    "vsL": ("byHand", "vsL"),
    "vsR": ("byHand", "vsR"),
    "RISP": ("bySituation", "risp"),
    "Empty": ("bySituation", "basesEmpty"),
    "Home": ("byLocation", "home"),
    "Away": ("byLocation", "away"),
    "Ahead": ("bySituation", "aheadInCount"),
    "Behind": ("bySituation", "behindInCount"),
}


def _n(d: dict, key: str) -> float:
    v = d.get(key)
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _div(a: float, b: float) -> float:
    return a / b if b else float("nan")


# ---------------------------------------------------------------------------
# One batting line, from counts
# ---------------------------------------------------------------------------
def line_from_counts(c: dict) -> dict:
    """Slash line, wOBA and BABIP from one counting block.

    Works for an overall line and for any split, and for both a hitter's line
    and the line a pitcher allowed, since iScore uses the same keys.
    """
    ab, h, bb, hbp, sf = (_n(c, k) for k in ("AB", "H", "BB", "HBP", "SF"))
    ibb, so, hr = _n(c, "IBB"), _n(c, "SO"), _n(c, "HR")
    d2 = _n(c, "2B") or _n(c, "H_2B")
    d3 = _n(c, "3B") or _n(c, "H_3B")
    singles = _n(c, "1B") or _n(c, "H_1B") or max(h - d2 - d3 - hr, 0)
    tb = singles + 2 * d2 + 3 * d3 + 4 * hr
    on_base = h + bb + hbp
    obp_den = ab + bb + hbp + sf
    woba_den = ab + bb - ibb + sf + hbp
    woba_num = (WOBA_W["uBB"] * (bb - ibb) + WOBA_W["HBP"] * hbp
                + WOBA_W["1B"] * singles + WOBA_W["2B"] * d2
                + WOBA_W["3B"] * d3 + WOBA_W["HR"] * hr)
    bip = ab - so - hr + sf
    avg, obp, slg = _div(h, ab), _div(on_base, obp_den), _div(tb, ab)
    return {
        "PA": _n(c, "PA") or _n(c, "BF") or obp_den,
        "AVG": avg, "OBP": obp, "SLG": slg, "OPS": obp + slg,
        "wOBA": _div(woba_num, woba_den), "BABIP": _div(h - hr, bip),
        # Counts kept so splits can be tested, not just compared by eye.
        "_ON": on_base, "_OBPD": obp_den, "_HNOHR": h - hr, "_BIP": bip,
        "_WNUM": woba_num, "_WDEN": woba_den,
    }


def _splits(block: dict, *, min_pa: int = 1) -> dict:
    out = {}
    for prefix, (group, name) in SPLITS.items():
        c = block.get(group, {}).get(name) or {}
        line = line_from_counts(c)
        if line["_OBPD"] < min_pa:
            continue
        for k, v in line.items():
            # Counts stay hidden behind a leading underscore: _vsR_ON, _vsR_OBPD.
            out[f"_{prefix}{k}" if k.startswith("_") else f"{prefix}_{k}"] = v
    return out


# ---------------------------------------------------------------------------
# Player rows
# ---------------------------------------------------------------------------
def batting_row(name: str, bats: str, season: dict) -> dict | None:
    b = (season.get("batting") or {})
    o = b.get("overall") or {}
    if _n(o, "PA") <= 0:
        return None
    line = line_from_counts(o)
    # The league office publishes iScore's own slash line, so show that when it
    # is there. On real 2026 data it matches the recomputed values exactly.
    rates = o.get("RATES") or {}
    for k in ("AVG", "OBP", "SLG", "OPS"):
        if rates.get(k) is not None:
            line[k] = float(rates[k])
    pa = _n(o, "PA")
    row = {
        "PLAYER": name, "BATS": bats,
        "G": _n(o, "GP"), "PA": pa, "AB": _n(o, "AB"), "R": _n(o, "R"),
        "H": _n(o, "H"), "2B": _n(o, "2B"), "3B": _n(o, "3B"), "HR": _n(o, "HR"),
        "RBI": _n(o, "RBI"), "BB": _n(o, "BB"), "SO": _n(o, "SO"),
        "HBP": _n(o, "HBP"),
        "SB": _n((season.get("running") or {}).get("overall") or {}, "SB"),
        "AVG": line["AVG"], "OBP": line["OBP"], "SLG": line["SLG"], "OPS": line["OPS"],
        "ISO": line["SLG"] - line["AVG"],
        "BB%": 100 * _div(_n(o, "BB"), pa), "K%": 100 * _div(_n(o, "SO"), pa),
        "BB/K": _div(_n(o, "BB"), _n(o, "SO")),
        "wOBA": line["wOBA"], "BABIP": line["BABIP"],
        "_ON": line["_ON"], "_OBPD": line["_OBPD"], "_HNOHR": line["_HNOHR"],
        "_BIP": line["_BIP"], "_WNUM": line["_WNUM"], "_WDEN": line["_WDEN"],
    }
    row.update(_splits(b))
    return row


def pitching_row(name: str, throws: str, season: dict) -> dict | None:
    p = (season.get("pitching") or {})
    o = p.get("overall") or {}
    bf = _n(o, "BF")
    if bf <= 0:
        return None
    outs = int(_n(o, "OUTS_PITCHED"))
    inn = outs / 3
    rates = o.get("RATES") or {}
    so, bb, hbp, hr = _n(o, "SO"), _n(o, "BB"), _n(o, "HBP"), _n(o, "HR")
    gp, gs = _n(o, "GP"), _n(o, "GS")
    allowed = line_from_counts(o)
    row = {
        "PLAYER": name, "THROWS": throws,
        "ROLE": "SP" if gp and gs / gp >= 0.5 else "RP",
        "G": gp, "GS": gs, "W": _n(o, "W"), "L": _n(o, "L"), "SV": _n(o, "SV"),
        # Baseball notation (53.1 is 53 and a third) kept as a number so it sorts.
        "IP": float(f"{outs // 3}.{outs % 3}"), "INN": inn,
        "BF": bf, "NP": _n(o, "PITCHES"), "H": _n(o, "H"), "R": _n(o, "R"),
        "ER": _n(o, "ER"), "HR": hr, "BB": bb, "SO": so, "HBP": hbp,
        "ERA": float(rates["ERA"]) if rates.get("ERA") is not None else 9 * _div(_n(o, "ER"), inn),
        "WHIP": float(rates["WHIP"]) if rates.get("WHIP") is not None else _div(bb + _n(o, "H"), inn),
        "K9": float(rates["K9"]) if rates.get("K9") is not None else 9 * _div(so, inn),
        "BB9": float(rates["BB9"]) if rates.get("BB9") is not None else 9 * _div(bb, inn),
        "HR9": 9 * _div(hr, inn),
        "K/BB": _div(so, bb) if bb > 0 else float("nan"),
        "K%": 100 * _div(so, bf), "BB%": 100 * _div(bb, bf),
        "K-BB%": 100 * _div(so - bb, bf),
        "STR%": 100 * _div(_n(o, "STRIKES"), _n(o, "PITCHES")),
        "P/PA": _div(_n(o, "PITCHES"), bf),
        "OPS_A": allowed["OPS"], "wOBA_A": allowed["wOBA"], "BABIP_A": allowed["BABIP"],
        "_HNOHR": allowed["_HNOHR"], "_BIP": allowed["_BIP"],
        "_FIPNUM": 13 * hr + 3 * (bb + hbp) - 2 * so,
    }
    row.update(_splits(p))
    return row


# ---------------------------------------------------------------------------
# League context
# ---------------------------------------------------------------------------
def fip_constant(pitchers: pd.DataFrame) -> float:
    """League ERA minus league raw FIP, so league FIP equals league ERA."""
    inn = pitchers["INN"].sum()
    if not inn:
        return 3.10
    lg_era = 9 * pitchers["ER"].sum() / inn
    return lg_era - pitchers["_FIPNUM"].sum() / inn


def add_fip(pitchers: pd.DataFrame, constant: float) -> pd.DataFrame:
    df = pitchers.copy()
    df["FIP"] = df["_FIPNUM"] / df["INN"].where(df["INN"] > 0) + constant
    df["ERA-FIP"] = df["ERA"] - df["FIP"]
    return df


def league_baselines(hitters: pd.DataFrame, pitchers: pd.DataFrame) -> dict:
    """Pooled league rates, weighted by opportunity (not a mean of player rates)."""
    h, p = hitters, pitchers
    return {
        "hit_K%": h["SO"].sum() / h["PA"].sum(),
        "hit_BB%": h["BB"].sum() / h["PA"].sum(),
        "hit_BABIP": h["_HNOHR"].sum() / h["_BIP"].sum(),
        "hit_wOBA": h["_WNUM"].sum() / h["_WDEN"].sum(),
        "hit_OBP": h["_ON"].sum() / h["_OBPD"].sum(),
        "pit_K%": p["SO"].sum() / p["BF"].sum(),
        "pit_BB%": p["BB"].sum() / p["BF"].sum(),
        "pit_BABIP": p["_HNOHR"].sum() / p["_BIP"].sum(),
        "ERA": 9 * p["ER"].sum() / p["INN"].sum(),
        "FIP_C": fip_constant(p),
    }


def shrink(successes, trials, mean: float, k: float):
    """Empirical Bayes estimate of a rate, pulled toward ``mean`` by ``k`` trials.

    With n trials the estimate is (x + k*mean) / (n + k). At n == k it sits
    halfway between the observed rate and the league rate. This is what a
    small-sample .400 hitter "really" is, as far as the data can say.
    """
    return (successes + k * mean) / (trials + k)


def add_true_talent(hitters: pd.DataFrame, pitchers: pd.DataFrame, base: dict):
    """Regressed K%, BB% and BABIP, the numbers to trust over a raw small sample."""
    h, p = hitters.copy(), pitchers.copy()
    h["xK%"] = 100 * shrink(h["SO"], h["PA"], base["hit_K%"], STABILIZE["hit_K%"])
    h["xBB%"] = 100 * shrink(h["BB"], h["PA"], base["hit_BB%"], STABILIZE["hit_BB%"])
    h["xBABIP"] = shrink(h["_HNOHR"], h["_BIP"], base["hit_BABIP"], STABILIZE["hit_BABIP"])
    p["xK%"] = 100 * shrink(p["SO"], p["BF"], base["pit_K%"], STABILIZE["pit_K%"])
    p["xBB%"] = 100 * shrink(p["BB"], p["BF"], base["pit_BB%"], STABILIZE["pit_BB%"])
    return h, p


# ---------------------------------------------------------------------------
# Small statistics helpers, no scipy needed at runtime
# ---------------------------------------------------------------------------
def norm_sf(z: float) -> float:
    """Upper tail of the standard normal."""
    return 0.5 * math.erfc(z / math.sqrt(2))


def two_prop_z(x1, n1, x2, n2):
    """Two-proportion z test. Returns (difference, z, two-sided p)."""
    if min(n1, n2) <= 0:
        return float("nan"), float("nan"), float("nan")
    p1, p2 = x1 / n1, x2 / n2
    pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pool * (1 - pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return p1 - p2, 0.0, 1.0
    z = (p1 - p2) / se
    return p1 - p2, z, 2 * norm_sf(abs(z))


def bh_reject(pvals, alpha: float = 0.10):
    """Benjamini-Hochberg. True where a test survives at false discovery rate alpha.

    With 150 hitters tested for a platoon split, about 7 will clear p < 0.05 by
    pure chance. BH controls the share of flagged players that are flukes.
    """
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    m = len(pvals)
    cutoff = -1
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= alpha * rank / m:
            cutoff = rank
    keep = set(order[:cutoff]) if cutoff > 0 else set()
    return [i in keep for i in range(m)]
