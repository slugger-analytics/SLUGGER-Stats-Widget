"""The Findings tab. Every number is read from data/league_baselines.json, so
the text cannot drift from the analysis that produced it.

Layout. A summary table lists every finding with its strength and one key
number. Detail sits below in three groups, each finding collapsed until opened.
Two charts in total. Nulls are listed on purpose, since learning that clutch
hitting is not detectable is a result.
"""
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from charts import reliability_panel, team_bars

STRENGTH = {"strong": "Strong", "suggestive": "Suggestive", "null": "None detected"}
STRENGTH_NOTE = {
    "strong": "Strong evidence. Large effect, consistent across the league.",
    "suggestive": "Suggestive. A real pattern, but easy to over-read.",
    "null": "No effect detected. The data cannot tell this apart from chance.",
}
GROUPS = ["Skill and luck", "Splits and situations", "Teams and parks"]


def _pct(x, digits=0):
    return f"{100 * x:.{digits}f}%"


class _Findings:
    """Collects findings so the summary table and the detail share one source."""

    def __init__(self):
        self.items = []

    def add(self, group, title, strength, key, body, caveat=None):
        self.items.append({"group": group, "title": title, "strength": strength,
                           "key": key, "body": body, "caveat": caveat})

    def table(self):
        return pd.DataFrame([{"Finding": i["title"], "Evidence": STRENGTH[i["strength"]],
                              "Key number": i["key"], "Area": i["group"]} for i in self.items])

    def render_group(self, group):
        for item in self.items:
            if item["group"] != group:
                continue
            with st.expander(item["title"]):
                st.caption(STRENGTH_NOTE[item["strength"]])
                st.markdown(item["body"])
                if item["caveat"]:
                    st.caption(f"Caveat. {item['caveat']}")


def _build(report):
    base = report["base"]
    f = _Findings()

    # ---------------------------------------------------------------- skill and luck
    rel_h, rel_p = report["reliability"]["hitters"], report["reliability"]["pitchers"]
    hs, ps = rel_h["stats"], rel_p["stats"]
    h_babip = report["noise"]["hit_BABIP"]["share"]
    p_babip = report["noise"]["pit_BABIP"]["share"]
    f.add("Skill and luck", "Strikeouts and walks are skill, BABIP is mostly luck", "strong",
          f"K% {hs['K%']['season_r']:.2f}, BABIP {hs['BABIP']['season_r']:.2f}",
          f"A hitter's strikeout rate repeats almost perfectly across his home and road halves "
          f"(full season reliability {hs['K%']['season_r']:.2f}), and pitcher strikeout and walk rates "
          f"are nearly as stable ({ps['K%']['season_r']:.2f} and {ps['BB%']['season_r']:.2f}). "
          f"BABIP barely repeats ({hs['BABIP']['season_r']:.2f} for hitters, {ps['BABIP']['season_r']:.2f} "
          f"for pitchers). Chance alone would produce about {_pct(h_babip)} of the spread in hitter "
          f"BABIP and {_pct(p_babip)} for pitchers. That is why player cards show a regressed "
          f"BABIP, pulled toward the league rate of {base['hit_BABIP']:.3f}.",
          "Reliability is measured within one season. Home and road halves differ by park, which "
          "pushes park sensitive stats such as home run rate a little low.")

    pred = report["predictive"]["r"]
    f.add("Skill and luck", "K-BB% predicts a pitcher's future runs better than ERA or FIP", "strong",
          f"r {pred['K-BB%']:.2f} vs FIP {pred['FIP']:.2f}",
          f"Using each pitcher's home games to predict his road games (n = {report['predictive']['n']}), "
          f"strikeouts minus walks per batter faced correlates at r = {pred['K-BB%']:.2f} with future "
          f"runs per batter. FIP manages {pred['FIP']:.2f}, ERA {pred['ERA']:.2f}, and BABIP allowed "
          f"{pred['BABIP allowed']:.2f}, which is effectively zero. The Pitchers tab has a K-BB% "
          "column for this reason.",
          "FIP leans on home runs allowed, and pitcher home run rate shows no repeatable skill in this "
          f"sample (reliability {ps['HR rate']['season_r']:.2f}). That drags FIP down. "
          "Home and road halves are not a true out of sample forecast across seasons.")

    sr = report["strike_throwing"]
    f.add("Skill and luck", "Throwing strikes is nearly the whole walk rate", "strong",
          f"r {sr['r']:.2f}",
          f"Among {sr['n']} qualified pitchers, strike percentage and walk rate correlate at "
          f"r = {sr['r']:.2f}. Each extra point of strike percentage goes with about "
          f"{abs(sr['slope']):.1f} fewer points of walk rate.")

    tr = report["hitter_tradeoffs"]
    f.add("Skill and luck", "Strikeouts do not cost ALPB hitters power", "suggestive",
          f"K% vs ISO r {tr['K_vs_ISO']:.2f}",
          f"Across {tr['n']} qualified hitters, K% and ISO are essentially uncorrelated "
          f"(r = {tr['K_vs_ISO']:.2f}). Power is what separates hitters (ISO against wOBA r = {tr['ISO_vs_wOBA']:.2f}). "
          f"Strikeouts hurt overall value (r = {tr['K_vs_wOBA']:.2f}) and walks help it "
          f"(r = {tr['BB_vs_wOBA']:.2f}), but the supposed trade of contact for power does not show up here.",
          f"Correlation among {tr['n']} hitters in one league and one season. It does not say what any "
          "single hitter would gain by changing approach.")

    # ---------------------------------------------------------------- splits
    pl = report["platoon"]
    ind = pl["individual"]
    hr_, hl_ = pl["hitters_R"], pl["hitters_L"]
    pr_, plf = pl["pitchers_R"], pl["pitchers_L"]
    f.add("Splits and situations",
          "The platoon edge shows up league wide but almost never proves out for one hitter",
          "suggestive", f"{ind['survive_fdr']} of {ind['tested']} survive correction",
          f"League wide, right handed hitters gain {hr_['edge']:+.3f} wOBA against left handed "
          f"pitching and left handed hitters gain {hl_['edge']:+.3f} against righties. "
          f"Right handed pitchers allow {pr_['edge']:+.3f} more wOBA to opposite handed batters "
          f"(margin of error about {pr_['se']:.3f}), while left handed pitchers show a gap of "
          f"{plf['edge']:+.3f} (margin {plf['se']:.3f}), too small to separate from zero. "
          f"For individuals, {ind['tested']} hitters with 40 or more PA on each side were tested. "
          f"{ind['raw_p05']} cleared p < .05, against {ind['expected_by_chance']:.1f} expected from "
          f"chance alone. After a false discovery rate correction only {ind['survive_fdr']} "
          f"remain ({', '.join(ind['flagged']) or 'none'}). Treat a hitter's individual "
          "platoon split as noise unless the sample is very large.",
          "wOBA standard errors are approximate. Left handed samples are small because left handed "
          "pitchers are a minority of pitching.")

    rp = report["risp"]
    f.add("Splits and situations", "There is no detectable clutch skill", "null",
          f"{rp['survive_fdr']} of {rp['tested']} survive correction",
          f"With runners in scoring position the league posts {rp['wOBA_risp']:.3f} wOBA against "
          f"{rp['wOBA_empty']:.3f} with the bases empty, and the gap comes from walks "
          f"({_pct(rp['BB%_risp'], 1)} of PA against {_pct(rp['BB%_empty'], 1)}). Pitchers work "
          f"around hitters with first base open, so this is a feature of the situation. "
          f"Testing {rp['tested']} hitters for an individual RISP edge beyond that league wide shift, "
          f"{rp['survive_fdr']} survive the false discovery correction. The spread of results across "
          f"hitters (z sd {rp['z_sd']:.2f}) is close to what pure chance produces (1.00).",
          "Absence of detection is not proof of absence. A season of RISP plate appearances is "
          "about 100 for a regular, which can only reveal very large effects.")

    ct = report["counts"]
    f.add("Splits and situations", "Count is the biggest swing in a plate appearance", "suggestive",
          f"{ct['Ahead']:.3f} ahead, {ct['Behind']:.3f} behind",
          f"Hitters post a {ct['Ahead']:.3f} wOBA when ahead in the count, {ct['Even']:.3f} when even, "
          f"and {ct['Behind']:.3f} when behind. The gap between ahead and behind is "
          f"{ct['Ahead'] - ct['Behind']:.3f}, several times the largest platoon edge.",
          "Counts are partly outcomes of how the plate appearance went, not only causes. "
          "Read this as descriptive.")

    # ---------------------------------------------------------------- teams and parks
    teams = pd.DataFrame(report["teams"])
    by_park = teams.sort_values("park_wOBA")
    top_park, low_park = by_park.iloc[-1], by_park.iloc[0]
    by_hr = teams.sort_values("park_HR")
    f.add("Teams and parks", "Parks matter at the extremes only", "suggestive",
          f"{low_park['park_wOBA']:.0f} to {top_park['park_wOBA']:.0f} wOBA index",
          f"{top_park['TEAM']} games run {top_park['park_wOBA'] - 100:.0f}% above road games in "
          f"offense and {low_park['TEAM']} games run {100 - low_park['park_wOBA']:.0f}% below. "
          f"Home run rates swing wider, with a margin of error near "
          f"{teams['park_HR_se'].mean():.0f} points per team, so only the largest gaps "
          f"({by_hr.iloc[0]['TEAM']} at {by_hr.iloc[0]['park_HR']:.0f}, "
          f"{by_hr.iloc[-1]['TEAM']} at {by_hr.iloc[-1]['park_HR']:.0f}) are clearly outside noise.",
          "This compares a team's home games with its own road games in a single season. It mixes "
          "park effects with that roster's strengths at home, so it is a rough park factor.")

    worst = teams.sort_values("def_BABIP").iloc[-1]
    others_max_z = teams[teams["TEAM"] != worst["TEAM"]]["def_z"].abs().max()
    f.add("Teams and parks",
          f"{worst['TEAM']} allowed far more hits on balls in play than the rest of the league",
          "strong", f"z = {worst['def_z']:.1f}, about {abs(worst['def_hits_vs_avg']):.0f} extra hits",
          f"Opponents hit {worst['def_BABIP']:.3f} on balls in play against them, "
          f"{worst['def_z']:.1f} standard errors above the league rate of {base['pit_BABIP']:.3f}. "
          f"That is about {abs(worst['def_hits_vs_avg']):.0f} extra hits. Their team ERA of "
          f"{worst['ERA']:.2f} sits above their FIP of {worst['FIP']:.2f}, so run prevention was worse "
          "than their strikeouts, walks and homers alone predict. No other team is further than "
          f"{others_max_z:.1f} standard errors from the league rate.",
          "BABIP allowed blends defense, pitcher contact quality, park, and luck. This data cannot "
          "separate them.")

    ro = report["roles"]
    f.add("Teams and parks", "Starters and relievers post similar ERAs with different shapes",
          "suggestive", f"ERA {ro['SP']['ERA']:.2f} SP, {ro['RP']['ERA']:.2f} RP",
          f"Starters run a {ro['SP']['ERA']:.2f} ERA and relievers {ro['RP']['ERA']:.2f}. Relievers "
          f"strike out more batters ({ro['RP']['K%']:.1f}% against {ro['SP']['K%']:.1f}%) and also "
          f"walk more ({ro['RP']['BB%']:.1f}% against {ro['SP']['BB%']:.1f}%).",
          "Roles are assigned from starts versus appearances. Relievers pitch fewer innings each, "
          "so their rates are noisier.")
    return f, teams


def render_findings(report, team):
    if not report:
        st.info("League findings are not built yet. Run scripts/snapshot_league.py "
                "and then scripts/build_league_report.py.")
        return

    m = report["meta"]
    findings, teams = _build(report)

    st.subheader("What the 2026 league data says")
    st.caption(
        f"{m['hitters']} hitters and {m['pitchers']} pitchers across all 10 teams. Player level "
        f"results use hitters with {m['hit_min_pa']}+ PA and pitchers with {m['pit_min_bf']}+ batters faced. "
        "Split and situation tests correct for running many comparisons at once, which is why most "
        "individual flags disappear.")

    st.table(findings.table().set_index("Finding"))

    skill, splits, parks = st.tabs(GROUPS)

    with skill:
        rel_h, rel_p = report["reliability"]["hitters"], report["reliability"]["pitchers"]
        fig = reliability_panel(rel_h["stats"], rel_p["stats"], rel_h["n"], rel_p["n"])
        st.pyplot(fig)
        plt.close(fig)
        st.caption("Each player's home games and road games are treated as two samples. If a stat is "
                   "skill, the two halves agree. Half season agreement is scaled up to a full season "
                   "with the Spearman-Brown formula.")
        findings.render_group("Skill and luck")

    with splits:
        findings.render_group("Splits and situations")

    with parks:
        chart_col, note_col = st.columns([3, 2])
        with chart_col:
            fig = team_bars(teams, "park_wOBA", "Home offense vs road offense (100 is neutral)",
                            ".0f", 100, highlight=team, sort_ascending=False,
                            xlabel="Home wOBA as a percent of road wOBA")
            st.pyplot(fig)
            plt.close(fig)
        with note_col:
            st.caption("Above 100 favors hitters at home. The team selected at the top is in red.")
        findings.render_group("Teams and parks")

    st.caption(
        "Method notes. wOBA uses MLB linear weights because ALPB run values are not available, "
        "so it ranks hitters well but its scale is approximate. Regressed estimates use the "
        f"stabilization points in metrics.py. Data snapshot taken {m['taken_at'][:10]} from the "
        "iScore public API. Rebuild with scripts/snapshot_league.py then scripts/build_league_report.py.")
