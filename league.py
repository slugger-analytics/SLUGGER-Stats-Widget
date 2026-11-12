"""League-wide research on a saved iScore snapshot.

``build_league_report`` turns ``data/snapshot_*.json`` (written by
``scripts/snapshot_league.py``) into ``data/league_baselines.json``, a small
file the widget ships with. It holds the league rates every comparison needs,
percentile tables, park factors, team defense, and the research findings shown
on the Findings tab.

Why a file and not a live computation: league context needs all ~530 players,
which is ~550 iScore calls. The widget loads one team at a time, so it reads
league context from this file instead. The 2026 season is over, so the numbers
do not go stale. Rebuild with ``python scripts/build_league_report.py``.

Pure and Streamlit-free. Uses numpy and pandas only.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from metrics import (
    add_fip,
    league_baselines,
    line_from_counts,
    pitching_row,
    batting_row,
    two_prop_z,
    bh_reject,
)

# Minimum samples for the league tables. Below these a player's rates are too
# noisy to anchor a percentile or a correlation.
HIT_MIN_PA = 150
PIT_MIN_BF = 150

HIT_PCT_STATS = ["AVG", "OBP", "SLG", "OPS", "wOBA", "ISO", "K%", "BB%", "BABIP"]
PIT_PCT_STATS = ["ERA", "FIP", "WHIP", "K%", "BB%", "K-BB%", "HR9", "BABIP_A", "STR%", "K9", "BB9"]


# ---------------------------------------------------------------------------
# Snapshot -> frames
# ---------------------------------------------------------------------------
def frames_from_snapshot(snap: dict):
    hit, pit = [], []
    for team in snap["teams"]:
        for p in team["players"]:
            season = p.get("stats")
            if not season:
                continue
            b = batting_row(p["name"], p.get("bats"), season)
            if b:
                hit.append({**b, "TEAM": team["name"], "guid": p["guid"]})
            q = pitching_row(p["name"], p.get("throws"), season)
            if q:
                pit.append({**q, "TEAM": team["name"], "guid": p["guid"]})
    return pd.DataFrame(hit), pd.DataFrame(pit)


def _block(season, side, group, name):
    return (((season or {}).get(side) or {}).get(group) or {}).get(name) or {}


def _r(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = ~(np.isnan(a) | np.isnan(b))
    if m.sum() < 3:
        return float("nan")
    return float(np.corrcoef(a[m], b[m])[0, 1])


def _clean(x):
    """Make numpy and NaN JSON-safe."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if math.isnan(float(x)) else round(float(x), 4)
    if isinstance(x, np.integer):
        return int(x)
    return x


# ---------------------------------------------------------------------------
# Research pieces
# ---------------------------------------------------------------------------
def _half_rates(season, side, loc):
    c = _block(season, side, "byLocation", loc)
    n = c.get("PA") or c.get("BF") or 0
    line = line_from_counts(c)
    rate = (lambda k: c.get(k, 0) / n) if n else (lambda k: float("nan"))
    return n, {
        "K%": rate("SO"), "BB%": rate("BB"), "HR rate": rate("HR"),
        "ISO": line["SLG"] - line["AVG"], "AVG": line["AVG"],
        "BABIP": line["BABIP"], "OBP": line["OBP"], "wOBA": line["wOBA"],
    }


def split_half_reliability(snap, side: str, min_half: int):
    """How much of each stat is skill, using a player's home and road halves.

    Correlate each player's home line with his road line. A stat that is
    mostly skill repeats across halves. Spearman-Brown scales the half-season
    correlation up to a full season. Halves are not random (parks differ), so
    stats parks move, like HR rate, read a little low.
    """
    pairs = []
    for team in snap["teams"]:
        for p in team["players"]:
            s = p.get("stats")
            nh, home = _half_rates(s, side, "home")
            na, away = _half_rates(s, side, "away")
            if nh >= min_half and na >= min_half:
                pairs.append((nh + na, home, away))
    out = {}
    for stat in ["K%", "BB%", "HR rate", "ISO", "AVG", "BABIP", "OBP", "wOBA"]:
        r = _r([h[stat] for _, h, _ in pairs], [a[stat] for _, _, a in pairs])
        out[stat] = {"half_r": r, "season_r": 2 * r / (1 + r) if r == r and r > -1 else r}
    return {"n": len(pairs),
            "avg_opportunities": float(np.mean([n for n, _, _ in pairs])) if pairs else 0,
            "stats": out}


def noise_share(df, stat, trials_col, league_rate):
    """Share of the spread in a rate that binomial chance alone would produce."""
    vals = df[stat] / (100 if stat.endswith("%") else 1)
    observed = vals.var(ddof=1)
    expected = float(np.mean(league_rate * (1 - league_rate) / df[trials_col]))
    return {"n": int(len(df)), "share": expected / observed if observed else float("nan")}


def _pooled(df, prefix):
    if f"_{prefix}_WNUM" not in df:       # no split data for this league or season
        return float("nan"), 0.0
    num, den = df[f"_{prefix}_WNUM"].sum(), df[f"_{prefix}_WDEN"].sum()
    return (num / den if den else float("nan")), float(den)


def platoon(hit, pit):
    """League platoon edges, plus how many individual splits are real."""
    out = {}
    for label, df, hand_col in (("hitters", hit, "BATS"), ("pitchers", pit, "THROWS")):
        for hand in ("R", "L"):
            sub = df[df[hand_col] == hand]
            same, opp = ("vsR", "vsL") if hand == "R" else ("vsL", "vsR")
            w_same, n_same = _pooled(sub, same)
            w_opp, n_opp = _pooled(sub, opp)
            # wOBA per PA has an sd near 0.5, which sets a rough standard error.
            se = 0.5 * math.sqrt(1 / n_same + 1 / n_opp) if n_same and n_opp else float("nan")
            out[f"{label}_{hand}"] = {"same": w_same, "opposite": w_opp,
                                     "edge": w_opp - w_same, "se": se,
                                     "n_same": n_same, "n_opp": n_opp}
    have = {"_vsL_OBPD", "_vsR_OBPD"} <= set(hit.columns)
    q = hit[(hit["_vsL_OBPD"] >= 40) & (hit["_vsR_OBPD"] >= 40)] if have else hit.iloc[0:0]
    tests = [two_prop_z(r["_vsL_ON"], r["_vsL_OBPD"], r["_vsR_ON"], r["_vsR_OBPD"])
             for _, r in q.iterrows()]
    pv = [t[2] for t in tests]
    keep = bh_reject(pv, 0.10)
    out["individual"] = {
        "tested": len(q), "raw_p05": sum(p < 0.05 for p in pv),
        "expected_by_chance": 0.05 * len(q), "survive_fdr": sum(keep),
        "z_sd": float(np.std([t[1] for t in tests], ddof=1)) if tests else float("nan"),
        "flagged": [r["PLAYER"] for (_, r), k in zip(q.iterrows(), keep) if k],
    }
    return out


def risp(hit, snap):
    """League RISP bump and whether any individual hitter is 'clutch'."""
    def rate(prefix, stat):
        name = {"RISP": "risp", "Empty": "basesEmpty"}[prefix]
        num = den = 0
        for team in snap["teams"]:
            for p in team["players"]:
                c = _block(p.get("stats"), "batting", "bySituation", name)
                num += c.get(stat, 0)
                den += c.get("PA", 0)
        return num / den if den else float("nan")

    have = {"_RISP_OBPD", "_Empty_OBPD"} <= set(hit.columns)
    q = hit[(hit["_RISP_OBPD"] >= 40) & (hit["_Empty_OBPD"] >= 40)] if have else hit.iloc[0:0]
    tests = [two_prop_z(r["_RISP_ON"], r["_RISP_OBPD"], r["_Empty_ON"], r["_Empty_OBPD"])
             for _, r in q.iterrows()]
    z = np.array([t[1] for t in tests])
    # Test each hitter against the league-wide RISP shift, not against zero,
    # or the shift every hitter gets reads as individual clutch.
    centered = [2 * (0.5 * math.erfc(abs(x - z.mean()) / math.sqrt(2))) for x in z]
    nan = float("nan")
    return {
        "wOBA_risp": _pooled(hit, "RISP")[0], "wOBA_empty": _pooled(hit, "Empty")[0],
        "OBP_risp": hit["_RISP_ON"].sum() / hit["_RISP_OBPD"].sum() if have else nan,
        "OBP_empty": hit["_Empty_ON"].sum() / hit["_Empty_OBPD"].sum() if have else nan,
        "BB%_risp": rate("RISP", "BB"), "BB%_empty": rate("Empty", "BB"),
        "K%_risp": rate("RISP", "SO"), "K%_empty": rate("Empty", "SO"),
        "tested": len(q), "survive_fdr": sum(bh_reject(centered, 0.10)),
        "z_sd": float(z.std(ddof=1)) if len(z) > 1 else float("nan"),
    }


def count_states(snap):
    out = {}
    for label, name in (("Ahead", "aheadInCount"), ("Even", "evenCount"), ("Behind", "behindInCount")):
        num = den = 0.0
        for team in snap["teams"]:
            for p in team["players"]:
                line = line_from_counts(_block(p.get("stats"), "batting", "bySituation", name))
                num += line["_WNUM"]
                den += line["_WDEN"]
        out[label] = num / den if den else float("nan")
    return out


def predictive_halves(snap, fip_c, min_bf=60):
    """Which home-half pitcher stat best predicts the same pitcher's road half."""
    rows = []
    for team in snap["teams"]:
        for p in team["players"]:
            s = p.get("stats")
            hm = _block(s, "pitching", "byLocation", "home")
            aw = _block(s, "pitching", "byLocation", "away")
            if hm.get("BF", 0) < min_bf or aw.get("BF", 0) < min_bf:
                continue
            h_inn, a_bf = hm.get("OUTS_PITCHED", 0) / 3, aw["BF"]
            rows.append({
                "K-BB%": (hm["SO"] - hm["BB"]) / hm["BF"],
                "FIP": (13 * hm["HR"] + 3 * (hm["BB"] + hm.get("HBP", 0)) - 2 * hm["SO"]) / h_inn + fip_c if h_inn else float("nan"),
                "ERA": 9 * hm.get("ER", 0) / h_inn if h_inn else float("nan"),
                "wOBA allowed": line_from_counts(hm)["wOBA"],
                "BABIP allowed": line_from_counts(hm)["BABIP"],
                "_future": aw.get("R", 0) / a_bf,
            })
    df = pd.DataFrame(rows)
    # Sign flipped so a bigger number always means a better predictor.
    sign = {"K-BB%": -1, "FIP": 1, "ERA": 1, "wOBA allowed": 1, "BABIP allowed": 1}
    return {"n": len(df), "r": {k: sign[k] * _r(df[k], df["_future"]) for k in sign} if len(df) else {}}


def team_tables(snap, hit, pit, base):
    """Park factors from home and road lines, and team defense from BABIP allowed."""
    rows = []
    for team in snap["teams"]:
        acc = {loc: {"wn": 0.0, "wd": 0.0, "hr": 0.0, "pa": 0.0} for loc in ("home", "away")}
        for p in team["players"]:
            for side, key in (("batting", "PA"), ("pitching", "BF")):
                for loc in acc:
                    c = _block(p.get("stats"), side, "byLocation", loc)
                    line = line_from_counts(c)
                    a = acc[loc]
                    a["wn"] += line["_WNUM"]; a["wd"] += line["_WDEN"]
                    a["hr"] += c.get("HR", 0); a["pa"] += c.get(key, 0) or 0
        h, a = acc["home"], acc["away"]
        th = hit[hit["TEAM"] == team["name"]]
        tp = pit[pit["TEAM"] == team["name"]]
        bip = tp["_BIP"].sum()
        babip = tp["_HNOHR"].sum() / bip if bip else float("nan")
        se = math.sqrt(base["pit_BABIP"] * (1 - base["pit_BABIP"]) / bip) if bip else float("nan")
        inn = tp["INN"].sum()
        rows.append({
            "TEAM": team["name"],
            "park_wOBA": 100 * (h["wn"] / h["wd"]) / (a["wn"] / a["wd"]) if h["wd"] and a["wd"] and a["wn"] else float("nan"),
            "park_HR": 100 * (h["hr"] / h["pa"]) / (a["hr"] / a["pa"]) if h["pa"] and a["pa"] and a["hr"] else float("nan"),
            "park_HR_se": 100 * math.sqrt(1 / h["hr"] + 1 / a["hr"]) if h["hr"] and a["hr"] else float("nan"),
            "def_BABIP": babip, "def_z": (babip - base["pit_BABIP"]) / se if se else float("nan"),
            "def_hits_vs_avg": (babip - base["pit_BABIP"]) * bip,
            "ERA": 9 * tp["ER"].sum() / inn if inn else float("nan"),
            "FIP": tp["_FIPNUM"].sum() / inn + base["FIP_C"] if inn else float("nan"),
            "hit_wOBA": th["_WNUM"].sum() / th["_WDEN"].sum() if len(th) else float("nan"),
            "hit_K%": 100 * th["SO"].sum() / th["PA"].sum() if len(th) else float("nan"),
            "hit_BB%": 100 * th["BB"].sum() / th["PA"].sum() if len(th) else float("nan"),
            "pit_K-BB%": 100 * (tp["SO"].sum() - tp["BB"].sum()) / tp["BF"].sum() if len(tp) else float("nan"),
        })
    return rows


def _percentiles(df, stats):
    return {s: np.nanpercentile(df[s].astype(float), np.arange(101)).tolist()
            for s in stats if s in df and df[s].notna().sum() >= 10}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------
def build_league_report(snap: dict) -> dict:
    hit, pit = frames_from_snapshot(snap)
    base = league_baselines(hit, pit)
    pit = add_fip(pit, base["FIP_C"])
    qh = hit[hit["PA"] >= HIT_MIN_PA]
    qp = pit[pit["BF"] >= PIT_MIN_BF]

    spread = len(qp) > 2 and qp["STR%"].std() > 0
    str_fit = np.polyfit(qp["STR%"], qp["BB%"], 1) if spread else [float("nan")] * 2
    role = {r: {"ERA": 9 * g["ER"].sum() / g["INN"].sum(),
                "K%": 100 * g["SO"].sum() / g["BF"].sum(),
                "BB%": 100 * g["BB"].sum() / g["BF"].sum(),
                "IP": g["INN"].sum()} for r, g in pit.groupby("ROLE")}

    report = {
        "meta": {"taken_at": snap.get("taken_at"), "season_guid": snap.get("season_guid"),
                 "hitters": len(hit), "pitchers": len(pit),
                 "qualified_hitters": len(qh), "qualified_pitchers": len(qp),
                 "hit_min_pa": HIT_MIN_PA, "pit_min_bf": PIT_MIN_BF},
        "base": base,
        "percentiles": {"hitters": _percentiles(qh, HIT_PCT_STATS),
                        "pitchers": _percentiles(qp, PIT_PCT_STATS)},
        "reliability": {"hitters": split_half_reliability(snap, "batting", 100),
                        "pitchers": split_half_reliability(snap, "pitching", 80)},
        "noise": {
            "hit_BABIP": noise_share(hit[hit["_BIP"] >= 150], "BABIP", "_BIP", base["hit_BABIP"]),
            "pit_BABIP": noise_share(pit[pit["_BIP"] >= 120], "BABIP_A", "_BIP", base["pit_BABIP"]),
            "hit_K%": noise_share(qh, "K%", "PA", base["hit_K%"]),
            "hit_BB%": noise_share(qh, "BB%", "PA", base["hit_BB%"]),
            "pit_K%": noise_share(qp, "K%", "BF", base["pit_K%"]),
            "pit_BB%": noise_share(qp, "BB%", "BF", base["pit_BB%"]),
        },
        "platoon": platoon(hit, pit),
        "risp": risp(hit, snap),
        "counts": count_states(snap),
        "predictive": predictive_halves(snap, base["FIP_C"]),
        "strike_throwing": {"r": _r(qp["STR%"], qp["BB%"]), "slope": float(str_fit[0]), "n": len(qp)},
        "hitter_tradeoffs": {"K_vs_ISO": _r(qh["K%"], qh["ISO"]), "K_vs_wOBA": _r(qh["K%"], qh["wOBA"]),
                             "BB_vs_wOBA": _r(qh["BB%"], qh["wOBA"]), "ISO_vs_wOBA": _r(qh["ISO"], qh["wOBA"]),
                             "n": len(qh)},
        "roles": role,
        "teams": team_tables(snap, hit, pit, base),
    }
    return _clean(report)
