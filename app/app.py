"""WEAVING — Production Control.

    streamlit run app/app.py

Eight screens over one database. The sidebar chooses a grain (day, week, month
or quarter) and a period; every panel on every screen follows that choice and
is placed beside the period before it, because a number on its own tells the
floor nothing about whether the plant is getting better or worse.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import queries as Q                                            # noqa: E402
import theme                                                   # noqa: E402
from theme import (C, BAND_C, band, band_colour, plotly_template,  # noqa: E402
                   efficiency_scale, fmt_y, fmt_n, pct, pts, signed)
import floor_text as T                                         # noqa: E402

st.set_page_config(page_title="Weaving — Production Control",
                   page_icon="🧵", layout="wide",
                   initial_sidebar_state="expanded")
st.markdown(theme.css(), unsafe_allow_html=True)
plotly_template()
CH = dict(displayModeBar=False)

# --------------------------------------------------------------------------- #
try:
    META = Q.meta()
except Q.NoData as e:
    st.error("**The database has no production data yet.**", icon="⚠️")
    st.code(str(e))
    st.markdown("Load it with:  `python -m etl.load --rebuild <workbook.xlsx>`")
    st.stop()
except Exception as e:                                    # connection trouble
    st.error("**The dashboard cannot reach the database.**", icon="⚠️")
    st.markdown(
        "Nothing is wrong with the figures — this screen simply cannot see "
        "them. The database is expected at:")
    st.code(Q.db.describe())
    st.markdown("Check that the PostgreSQL service on the factory PC is "
                "running and that this PC can reach it over the department "
                "network. The error was:")
    st.code(str(e))
    st.stop()


# =========================================================================== #
#  SIDEBAR
# =========================================================================== #
with st.sidebar:
    st.markdown(f"<div style='font:800 14px Inter;letter-spacing:.12em;"
                f"color:{C['ink']}'>CONTROLS</div><div class='warp'></div>",
                unsafe_allow_html=True)

    grain = st.radio("Group by", Q.GRAINS, index=2, horizontal=True,
                     help="Everything on every screen follows this. Each period "
                          "is compared with the one before it.")
    P = Q.periods(grain)
    labels = dict(zip(P.period_key, P.period_label))
    keys = P.period_key.tolist()
    period = st.selectbox("Period", keys, index=len(keys) - 1,
                          format_func=lambda k: labels.get(k, k))
    prev_key = Q.previous_period(grain, period)

    st.markdown("---")
    st.caption("FILTERS — applied to every panel")
    o = Q.options()
    f_shift = st.multiselect("Shift", ["A", "B", "C", "DAY"], default=[])
    f_line = st.multiselect("Line group", o["line_groups"], default=[])
    f_peer = st.multiselect("Peer group", o["peers"], default=[])
    f_mach = st.multiselect("Machine", o["machines"], default=[])
    f_spec = st.multiselect("Specification", o["specs"], default=[])
    f_op = st.multiselect("Operator", o["operators"], default=[])

    st.markdown("---")
    measured = st.toggle("Measured readings only", value=False,
                         help="Drop rows that were reconstructed rather than "
                              "read off the meter. The strictest view.")
    real_only = st.toggle("Exclude un-split machine-days", value=False,
                          help="Removes the early rows that carry one reading "
                               "for the whole day instead of three shifts.")

    st.markdown("---")
    if st.button("Refresh data", width="stretch"):
        Q.refresh()
        st.rerun()
    st.caption(f"{int(META['rows']):,} machine-shift rows · "
               f"{int(META['machines'])} machines\n\n"
               f"{META['d0']} → {META['d1']}")
    if META.get("last_load"):
        st.caption(f"Last load {pd.to_datetime(META['last_load']):%d %b %Y %H:%M}")

d0, d1, ndays = Q.period_bounds(grain, period)
base = dict(shifts=tuple(f_shift), machines=tuple(f_mach), specs=tuple(f_spec),
            line_groups=tuple(f_line), peer_groups=tuple(f_peer),
            operators=tuple(f_op), measured_only=measured,
            real_shifts_only=real_only)
F = Q.Filters(d0=d0, d1=d1, **base)
K = Q.kpis(F)

if prev_key:
    p0, p1, pdays = Q.period_bounds(grain, prev_key)
    FP = Q.Filters(d0=p0, d1=p1, **base)
    KP = Q.kpis(FP)
    now_word, prev_word = Q.COMPARE_WORDS[grain]
    prev_label = Q.periods(grain).set_index("period_key").period_label.get(prev_key, prev_key)
else:
    FP = KP = None
    pdays = 0
    now_word, prev_word = Q.COMPARE_WORDS[grain]
    prev_label = None


# =========================================================================== #
#  MASTHEAD
# =========================================================================== #
st.markdown(f"""
<div class="mast">
  <div class="bd"><b>WEAVING</b><span>Production Control</span></div>
  <div class="sp">
    <div><u>Period</u><b>{labels.get(period, period)}</b></div>
    <div><u>Compared with</u><b>{prev_label or '—'}</b></div>
    <div><u>Working days</u><b>{int(K['days'])}{f" vs {int(pdays)}" if pdays else ""}</b></div>
    <div><u>Machines</u><b>{int(K['active'])} / {int(K['machines'])}</b></div>
    <div><u>Data trust</u><b><span class="dot"></span>{pct(K['trust'])}</b></div>
    <div><u>Latest record</u><b>{META['d1']}</b></div>
  </div>
</div><div class="warp"></div>""", unsafe_allow_html=True)


# =========================================================================== #
#  small helpers
# =========================================================================== #
def delta(cur, prv, invert=False, as_points=False):
    """The comparison chip. Green means the plant is better off."""
    if cur is None or prv is None or prv != prv or cur != cur or prv == 0:
        return "<span class='flat'>no comparison</span>"
    if as_points:
        d = cur - prv
        good = (d < 0) if invert else (d > 0)
        cls = "flat" if abs(d) < 0.002 else ("up" if good else "down")
        return f"<b class='{cls}'>{'▲' if d > 0 else '▼'} {abs(d)*100:,.1f} pts</b>"
    d = (cur - prv) / abs(prv)
    good = (d < 0) if invert else (d > 0)
    cls = "flat" if abs(d) < 0.002 else ("up" if good else "down")
    return f"<b class='{cls}'>{'▲' if d > 0 else '▼'} {abs(d)*100:,.1f}%</b>"


def kpi_card(label, value, unit="", cmp_html="", bar=None, bar_band=None, foot=None):
    bar_html = ""
    if bar is not None and bar == bar:
        col = BAND_C.get(bar_band or band(bar), C["data"])
        bar_html = (f"<div class='thread'><i style='width:"
                    f"{max(0, min(1, bar))*100:.1f}%;background:{col}'></i></div>")
    st.markdown(
        f"<div class='kpi'><div class='lab'>{label}</div>"
        f"<div class='val'>{value}{f'<small>{unit}</small>' if unit else ''}</div>"
        f"<div class='cmp'>{cmp_html}</div>{bar_html}"
        f"{f'<div class=foot>{foot}</div>' if foot else ''}</div>",
        unsafe_allow_html=True)


def acard(stripe, rank, title, sub, big=None, bigcol=None, pill=None, extra=None):
    st.markdown(
        f"<div class='acard'><div class='stripe' style='background:{stripe}'></div>"
        f"<div class='in'><div class='rank'>{rank}</div><h4>{title}</h4>"
        f"<div class='sub'>{sub}</div>"
        f"{f'<div class=big style=color:{bigcol}>{big}</div>' if big else ''}"
        f"{pill or ''}{extra or ''}</div></div>", unsafe_allow_html=True)


def sh(title, note=""):
    st.markdown(f"<div class='sh'><h3>{title}</h3><p>{note}</p></div>",
                unsafe_allow_html=True)


def no_rows():
    st.info("Nothing to show for this period and these filters.", icon="ℹ️")


# =========================================================================== #
TABS = st.tabs(["COMMAND CENTRE", "TREND & COMPARE", "MACHINES", "SHIFTS & PEOPLE",
                "QUALITY", "STOPPAGES", "DATA HEALTH", "FLOOR BOARD"])


# --------------------------------------------------------------------------- #
#  1 · COMMAND CENTRE
# --------------------------------------------------------------------------- #
with TABS[0]:
    sh("PLANT POSITION",
       f"{labels.get(period, period)} · {int(K['days'])} working day"
       f"{'s' if K['days'] != 1 else ''}"
       + (f", against {prev_label} ({int(pdays)} day{'s' if pdays != 1 else ''})"
          if prev_label else ""))

    c = st.columns(6)
    with c[0]:
        foot = None
        if KP and pdays and K["days"] != pdays:
            foot = (f"Per working day {fmt_y(K['per_day'])} vs "
                    f"{fmt_y(KP['per_day'])} "
                    f"{delta(K['per_day'], KP['per_day'])}")
        kpi_card("Actual production", fmt_y(K["net"]), "yd",
                 f"{delta(K['net'], KP['net'] if KP else None)} vs {prev_word}",
                 foot=foot)
    with c[1]:
        kpi_card("Production target", fmt_y(K["target"]) if K["target"] else "—", "yd",
                 f"{pct(K['achieved'])} of plan achieved" if K["achieved"]
                 else "no target set in this period",
                 bar=K["achieved"])
    with c[2]:
        kpi_card("Efficiency", pct(K["efficiency"]) if K["efficiency"] else "—", "",
                 f"{delta(K['efficiency'], KP['efficiency'] if KP else None, as_points=True)}"
                 f" vs {prev_word}", bar=K["efficiency"])
    with c[3]:
        kpi_card("Rejection rate", pct(K["rejection_rate"], 2), "",
                 f"{delta(K['rejection_rate'], KP['rejection_rate'] if KP else None, invert=True, as_points=True)}"
                 f" vs {prev_word}",
                 bar=min(1, K["rejection_rate"] / 0.05),
                 bar_band=band(1 - K["rejection_rate"] / 0.05),
                 foot=f"{fmt_y(K['rejection'])} yd failed inspection")
    with c[4]:
        kpi_card("Looms that ran", f"{int(K['active'])} / {int(K['machines'])}", "",
                 f"{pct(K['availability'])} of the fleet"
                 + (f" · {signed(int(K['active']) - int(KP['active']))} vs {prev_word}" if KP else ""),
                 bar=K["availability"])
    with c[5]:
        kpi_card("Short of target",
                 ("−" + fmt_y(abs(K["gap"]))) if K["gap"] is not None else "—", "yd",
                 f"{pct(1 - K['achieved'])} below plan" if K["achieved"] else "no target set",
                 foot=f"Worth about ₹{fmt_y(K['gap'] * (K['value']/K['net'] if K['net'] else 0))}"
                      if K["gap"] and K["net"] else None)

    # ---- attention ------------------------------------------------------- #
    sh("WHAT NEEDS A DECISION",
       "Ranked by the yards behind it. Each card names the thing, the size of "
       "the loss and who can act on it.")

    S = Q.by_shift(F)
    M = Q.by_machine(F)
    a = st.columns(5)

    # ① weakest shift
    with a[0]:
        Sr = S[S.shift_code.isin(["A", "B", "C"])].dropna(subset=["efficiency"])
        if len(Sr) >= 2:
            lo, hi = Sr.loc[Sr.efficiency.idxmin()], Sr.loc[Sr.efficiency.idxmax()]
            spread = float(hi.efficiency - lo.efficiency)
            balanced = spread < 0.02
            drag = M.nlargest(3, "gap") if "gap" in M else pd.DataFrame()
            rows = "".join(
                f"<div style='display:flex;gap:8px;font-size:11px;margin-top:3px'>"
                f"<span style='font-family:IBM Plex Mono;color:{C['ink2']};width:52px'>{r.machine_code}</span>"
                f"<span style='flex:1;height:5px;background:{C['line_soft']};border-radius:2px;"
                f"align-self:center'><i style='display:block;height:100%;width:"
                f"{r.gap/drag.gap.max()*100:.0f}%;background:{C['deep']};border-radius:2px'></i></span>"
                f"<b style='font-family:IBM Plex Mono;font-size:10.5px;color:{C['ink2']}'>"
                f"{fmt_y(r.gap)}</b></div>" for _, r in drag.iterrows()) if len(drag) else ""
            acard(C["neutral"] if balanced else C["warn"], "① Weakest shift",
                  f"{lo.shift_code} · {lo.shift_name_en}",
                  f"{pct(lo.efficiency)} efficiency across {int(lo.days)} days",
                  pill=(f"<span class='pill p-neut'>Balanced — {spread*100:.1f} pts apart</span>"
                        if balanced else
                        f"<span class='pill p-warn'>{pts(lo.efficiency-hi.efficiency)} pts behind shift {hi.shift_code}</span>"),
                  extra=(f"<div style='border-top:1px solid {C['line_soft']};margin-top:9px;"
                         f"padding-top:7px;font:600 9px Inter;letter-spacing:.13em;"
                         f"color:{C['ink3']}'>BIGGEST LOSSES IN THE PERIOD</div>{rows}") if rows else None)
        else:
            acard(C["neutral"], "① Weakest shift", "—", "no shift split in this period")

    # ② biggest machine loss
    with a[1]:
        if len(M) and M.gap.sum() > 0:
            b = M.loc[M.gap.idxmax()]
            acard(C["crit"], "② Biggest loom loss", b.machine_code,
                  f"running at {pct(b.efficiency)} · {int(b.days_producing)} of "
                  f"{int(b.days_seen)} days produced",
                  "−" + fmt_y(b.gap) + " yd", C["crit"],
                  f"<span class='pill p-crit'>{b.gap/M.gap.sum()*100:.0f}% of the plant's shortfall</span>")
        else:
            acard(C["neutral"], "② Biggest loom loss", "—", "no target in this period")

    # ③ quality
    with a[2]:
        big = M[M.gross > M.gross.quantile(0.6)] if len(M) else M
        if len(big) and big.rejection_rate.notna().any():
            r = big.loc[big.rejection_rate.idxmax()]
            plant = K["rejection_rate"] or 0.0001
            rr = Q.rejection_by(Q.Filters(d0=d0, d1=d1, **{**base, "machines": (r.machine_code,)}),
                                "reason")
            top = rr.iloc[0].k if len(rr) else "not stated"
            acard(C["crit"], "③ Quality alert", r.machine_code,
                  f"plant average is {pct(plant, 2)}", pct(r.rejection_rate, 2), C["crit"],
                  f"<span class='pill p-crit'>{r.rejection_rate/plant:.1f}× the plant rate</span>"
                  f"<div class='sub' style='margin-top:7px'>Main cause · {top}</div>")
        else:
            acard(C["neutral"], "③ Quality alert", "—", "no rejection recorded")

    # ④ idle fleet
    with a[3]:
        idle = M[(M.days_producing == 0) & (M.target > 0)] if len(M) else M
        if len(idle):
            acard(C["warn"], "④ Looms that never ran",
                  f"{len(idle)} loom{'s' if len(idle) != 1 else ''}",
                  ", ".join(idle.machine_code.head(6)) + ("…" if len(idle) > 6 else ""),
                  "−" + fmt_y(idle.target.sum()) + " yd", C["warn"],
                  "<span class='pill p-warn'>Target booked, nothing produced</span>")
        else:
            acard(C["good"], "④ Looms that never ran", "None",
                  "every loom with a target produced something",
                  pill="<span class='pill p-good'>Whole fleet active</span>")

    # ⑤ changeover cost
    with a[4]:
        ch = Q.changeovers(F)
        if len(ch) and ch.cost_yards.notna().any():
            worst = ch.iloc[0]
            acard(C["warn"], "⑤ Cost of changeovers",
                  f"{len(ch)} event{'s' if len(ch) != 1 else ''}",
                  f"worst was {worst.machine_code} on "
                  f"{pd.to_datetime(worst.event_date):%d %b}",
                  "−" + fmt_y(ch.cost_yards.sum()) + " yd", C["warn"],
                  f"<span class='pill p-warn'>{fmt_y(ch.cost_yards.mean())} yd per event</span>")
        else:
            acard(C["neutral"], "⑤ Cost of changeovers", "None",
                  "no changeover or reset in this period")

    # ---- waterfall + shift bars ------------------------------------------ #
    left, right = st.columns([1.35, 1])
    with left:
        sh("WHERE THE YARDS WENT", "From what the plan asked for, down to what was delivered.")
        w = Q.loss_waterfall(F)
        if len(w) and w.yards.abs().sum() > 0:
            fig = go.Figure(go.Waterfall(
                orientation="v",
                measure=["absolute"] + ["relative"] * (len(w) - 2) + ["total"],
                x=w.step, y=w.yards, text=[fmt_y(v) for v in w.yards],
                textposition="outside", textfont=dict(size=11),
                connector=dict(line=dict(color=C["line"], width=1)),
                increasing=dict(marker=dict(color=C["good"])),
                decreasing=dict(marker=dict(color=C["crit"])),
                totals=dict(marker=dict(color=C["data"])),
                hovertemplate="%{x}<br>%{y:,.0f} yd<extra></extra>"))
            fig.update_layout(height=330, yaxis_title="yards", showlegend=False)
            st.plotly_chart(fig, width="stretch", config=CH)
            st.caption(" · ".join(f"**{r.step}** — {r.note}" for _, r in w.iterrows()))
        else:
            no_rows()

    with right:
        sh("SHIFT AGAINST SHIFT", "Same period, same filters, three shifts.")
        Sr = S[S.shift_code.isin(["A", "B", "C"])].dropna(subset=["efficiency"])
        if len(Sr):
            SP = Q.by_shift(FP) if FP else None
            fig = go.Figure()
            fig.add_bar(x=Sr.shift_code + " · " + Sr.shift_name_en,
                        y=Sr.efficiency * 100, name=now_word.title(),
                        marker_color=[band_colour(v) for v in Sr.efficiency],
                        text=[pct(v) for v in Sr.efficiency], textposition="outside")
            if SP is not None:
                SPr = SP[SP.shift_code.isin(["A", "B", "C"])].dropna(subset=["efficiency"])
                if len(SPr):
                    fig.add_scatter(x=SPr.shift_code + " · " + SPr.shift_name_en,
                                    y=SPr.efficiency * 100, mode="markers",
                                    name=prev_word.title(),
                                    marker=dict(color=C["deep"], size=13,
                                                symbol="line-ew-open",
                                                line=dict(width=3, color=C["deep"])))
            fig.update_layout(height=330, yaxis_title="efficiency %",
                              yaxis_range=[0, max(100, Sr.efficiency.max() * 118)])
            st.plotly_chart(fig, width="stretch", config=CH)
            gap = Sr.efficiency.max() - Sr.efficiency.min()
            wk = Sr.loc[Sr.efficiency.idxmin()]
            st.caption(
                f"Shift **{wk.shift_code}** is the weakest at {pct(wk.efficiency)}. "
                f"Bringing it to the best shift's rate would be worth about "
                f"**{fmt_y(wk.target * gap)} yards** in this period alone.")
        else:
            no_rows()


# --------------------------------------------------------------------------- #
#  2 · TREND & COMPARE
# --------------------------------------------------------------------------- #
with TABS[1]:
    sh("IS THE PLANT GETTING BETTER OR WORSE",
       f"Every {grain.lower()} beside the {grain.lower()} before it. "
       f"Yards per working day is the honest comparison, because the number of "
       f"working days changes with the festival calendar.")

    series = Q.period_series(grain)
    if series.empty:
        no_rows()
    else:
        cur = series[series.period_key == period]
        if len(cur):
            r = cur.iloc[0]
            cc = st.columns(4)
            dirn = r.direction
            col = {"IMPROVING": C["good"], "DEGRADING": C["crit"]}.get(dirn, C["neutral"])
            with cc[0]:
                kpi_card(f"{grain.title()} direction",
                         f"<span style='color:{col}'>{dirn.title()}</span>", "",
                         f"on yards per working day, {now_word} against {prev_word}")
            with cc[1]:
                kpi_card("Yards per working day", fmt_y(r.net_per_day), "yd",
                         f"{delta(r.net_per_day, r.prev_net_per_day)} vs {prev_word}",
                         foot=f"{prev_word.title()}: {fmt_y(r.prev_net_per_day)} yd")
            with cc[2]:
                kpi_card("Efficiency", pct(r.efficiency), "",
                         f"{delta(r.efficiency, r.prev_efficiency, as_points=True)} vs {prev_word}",
                         bar=r.efficiency)
            with cc[3]:
                kpi_card("Rejection rate", pct(r.rejection_rate, 2), "",
                         f"{delta(r.rejection_rate, r.prev_rejection_rate, invert=True, as_points=True)} vs {prev_word}")

        s = series.copy()
        s["lab"] = s.period_label
        fig = go.Figure()
        fig.add_bar(x=s.lab, y=s.net_per_day, name="Yards per working day",
                    marker_color=C["data"], opacity=.85,
                    hovertemplate="%{x}<br>%{y:,.0f} yd/day<extra></extra>")
        if s.target_yards.notna().any():
            fig.add_scatter(x=s.lab, y=s.efficiency * 100, name="Efficiency %",
                            yaxis="y2", mode="lines+markers",
                            line=dict(color=C["accent"], width=2.5),
                            marker=dict(size=7),
                            hovertemplate="%{x}<br>%{y:.1f}%<extra></extra>")
        sel = s.index[s.period_key == period]
        if len(sel):
            fig.add_vline(x=s.loc[sel[0], "lab"], line=dict(color=C["ink3"],
                          width=1, dash="dot"))
        fig.update_layout(
            height=400, yaxis_title="yards per working day",
            yaxis2=dict(title="efficiency %", overlaying="y", side="right",
                        showgrid=False, range=[0, 100]),
            hovermode="x unified")
        st.plotly_chart(fig, width="stretch", config=CH)

        sh("THE SAME THING AS A TABLE", "Sorted newest last, so the trend reads downward.")
        t = s[["period_label", "working_days", "net_yards", "net_per_day",
               "pc_net_per_day", "efficiency", "d_efficiency", "rejection_rate",
               "machines_producing", "direction"]].copy()
        t.columns = ["Period", "Working days", "Net yards", "Yards per day",
                     "vs previous", "Efficiency", "Efficiency change",
                     "Rejection", "Looms running", "Direction"]
        # the first period has nothing before it; that is a dash, not "None"
        t = t.astype(object).where(pd.notna(t), None)
        st.dataframe(
            t.style.format({
                "Net yards": "{:,.0f}", "Yards per day": "{:,.0f}",
                "vs previous": lambda v: "—" if v is None or pd.isna(v) else f"{v*100:+.1f}%",
                "Efficiency": lambda v: "—" if v is None or pd.isna(v) else f"{v*100:.1f}%",
                "Efficiency change": lambda v: "—" if v is None or pd.isna(v) else f"{v*100:+.1f} pts",
                "Rejection": lambda v: "—" if v is None or pd.isna(v) else f"{v*100:.2f}%"})
             .map(lambda v: f"color:{C['good']}" if v == "IMPROVING"
                  else (f"color:{C['crit']}" if v == "DEGRADING" else ""),
                  subset=["Direction"]),
            width="stretch", hide_index=True, height=min(520, 40 + 35*len(t)))

        st.caption(
            "**Direction** is set on yards per working day, not on the month "
            "total: a short month is not a bad month. Anything within ±2% of "
            "the previous period is called holding rather than a change.")


# --------------------------------------------------------------------------- #
#  3 · MACHINES
# --------------------------------------------------------------------------- #
with TABS[2]:
    sh("EVERY LOOM, EVERY DAY",
       "Green is at or above 75% of target, amber 60–75%, red below 60%. "
       "A blank square is a day the loom has no row at all.")

    grid = Q.machine_day_grid(F)
    if grid.empty:
        no_rows()
    else:
        piv = grid.pivot_table(index="machine_code", columns="date_key",
                               values="efficiency", aggfunc="mean")
        piv = piv.reindex(sorted(piv.index, reverse=True))
        # A pivot drops any column that is entirely empty for its value, so the
        # three grids can come back different shapes — reindexing them onto the
        # efficiency grid keeps every hover box pointing at its own cell.
        def aligned(value, how):
            return (grid.pivot_table(index="machine_code", columns="date_key",
                                     values=value, aggfunc=how)
                        .reindex(index=piv.index, columns=piv.columns))
        yards = aligned("net", "sum")
        ops = aligned("operators", "first")
        custom = np.dstack([yards.values, ops.fillna("—").values])
        fig = go.Figure(go.Heatmap(
            z=piv.values * 100,
            x=[pd.Timestamp(c).strftime("%d %b") for c in piv.columns],
            y=piv.index, customdata=custom,
            colorscale=efficiency_scale(125), zmin=0, zmax=125, xgap=1, ygap=1,
            colorbar=dict(title="eff %", thickness=11, len=.7,
                          tickvals=[0, 60, 75, 100, 125]),
            hovertemplate="<b>%{y}</b> · %{x}<br>Efficiency %{z:.0f}%"
                          "<br>Net %{customdata[0]:,.0f} yd"
                          "<br>Operator %{customdata[1]}<extra></extra>"))
        fig.update_layout(height=max(420, 15 * len(piv)) + 60,
                          margin=dict(b=70),
                          xaxis=dict(showgrid=False, tickangle=-90,
                                     tickfont=dict(size=10)),
                          yaxis=dict(showgrid=False, tickfont=dict(size=10)))
        st.plotly_chart(fig, width="stretch", config=CH)

        sh("LOOM BY LOOM", "Sorted by the yards each is behind its target.")
        M = Q.by_machine(F).sort_values("gap", ascending=False)
        cons = Q.consistency(F).set_index("machine_code")
        M = M.join(cons[["cv", "days_below_60", "slope_per_day"]], on="machine_code")
        show = M[["machine_code", "peer_group", "lines_fitted", "days_producing",
                  "days_seen", "net", "target", "gap", "efficiency",
                  "rejection_rate", "cv", "days_below_60", "operators"]].copy()
        show.columns = ["Loom", "Peer group", "Lines", "Days run", "Days seen",
                        "Net yards", "Target", "Behind by", "Efficiency",
                        "Rejection", "Swing", "Days under 60%", "Operators"]
        st.dataframe(
            show.style.format({
                "Net yards": "{:,.0f}", "Target": "{:,.0f}", "Behind by": "{:,.0f}",
                "Efficiency": lambda v: "—" if pd.isna(v) else f"{v*100:.1f}%",
                "Rejection": lambda v: "—" if pd.isna(v) else f"{v*100:.2f}%",
                "Swing": lambda v: "—" if pd.isna(v) else f"{v:.2f}"})
             .background_gradient(subset=["Behind by"], cmap="Reds"),
            width="stretch", hide_index=True, height=480)
        st.caption(
            "**Swing** is how much a loom's daily efficiency moves about its own "
            "average. A high swing with a decent average is a loom that breaks "
            "down and recovers; a low swing with a poor average is a loom that "
            "is set up wrong or carries the wrong target. They need different people.")

        sh("ONE LOOM IN DETAIL", "")
        pick = st.selectbox("Loom", sorted(M.machine_code.tolist()),
                            key="machine_pick")
        det = Q.machine_detail(pick, d0, d1)
        if det.empty:
            no_rows()
        else:
            dd = det.groupby("date_key").agg(
                net=("net_yards", "sum"), target=("target_yards", "sum")).reset_index()
            fig = go.Figure()
            fig.add_bar(x=dd.date_key, y=dd.net, name="Net yards",
                        marker_color=C["data"])
            fig.add_scatter(x=dd.date_key, y=dd.target, name="Target",
                            mode="lines", line=dict(color=C["accent"], width=2, dash="dot"))
            fig.update_layout(height=260, yaxis_title="yards")
            st.plotly_chart(fig, width="stretch", config=CH)
            st.dataframe(det.head(200), width="stretch", hide_index=True,
                         height=300)


# --------------------------------------------------------------------------- #
#  4 · SHIFTS & PEOPLE
# --------------------------------------------------------------------------- #
with TABS[3]:
    sh("SHIFT PERFORMANCE OVER TIME",
       "Three lines. Where they separate, the difference is the shift, not the loom.")
    sd = Q.shift_by_day(F)
    if sd.empty:
        st.info("No shift-split rows in this period.", icon="ℹ️")
    else:
        fig = go.Figure()
        for i, (code, g) in enumerate(sd.groupby("shift_code")):
            g = g.sort_values("date_key")
            fig.add_scatter(x=g.date_key, y=g.efficiency * 100, name=f"Shift {code}",
                            mode="lines", line=dict(width=2))
        fig.update_layout(height=320, yaxis_title="efficiency %", hovermode="x unified")
        st.plotly_chart(fig, width="stretch", config=CH)

    # ---- the staffing question ------------------------------------------- #
    sh("WHAT HAPPENS IF WE PUT MORE OPERATORS ON",
       "Each point is one operator on one shift on one day. The question is "
       "whether efficiency falls as the number of looms per operator rises.")

    span = Q.span_of_control(F)
    if len(span) < 30:
        st.info(
            "Not enough shifts name an operator in this period to answer this "
            "honestly. Operator names were only recorded from April onward, and "
            "patchily before August — widen the period, or wait for the paper "
            "form to fill this in.", icon="ℹ️")
    else:
        g = (span.groupby("machines_covered")
                 .agg(shifts=("efficiency", "size"),
                      efficiency=("efficiency", "mean"),
                      spread=("efficiency", "std"),
                      net=("net_yards", "mean"))
                 .reset_index())
        g = g[g.shifts >= 5]

        x = span.machines_covered.astype(float).values
        y = span.efficiency.astype(float).values
        ok = np.isfinite(x) & np.isfinite(y)
        x, y = x[ok], y[ok]
        slope = intercept = r2 = None
        if len(x) > 20 and x.std() > 0:
            slope, intercept = np.polyfit(x, y, 1)
            pred = intercept + slope * x
            ss_res = float(((y - pred) ** 2).sum())
            ss_tot = float(((y - y.mean()) ** 2).sum())
            r2 = 1 - ss_res / ss_tot if ss_tot else 0.0

        cl, cr = st.columns([1.25, 1])
        with cl:
            fig = go.Figure()
            fig.add_scatter(x=span.machines_covered, y=span.efficiency * 100,
                            mode="markers", name="One operator-shift",
                            marker=dict(color=C["data"], size=5, opacity=.35),
                            hovertemplate="%{x} looms<br>%{y:.0f}%<extra></extra>")
            if len(g):
                fig.add_scatter(x=g.machines_covered, y=g.efficiency * 100,
                                mode="lines+markers", name="Average at that load",
                                line=dict(color=C["accent"], width=2.5),
                                marker=dict(size=9))
            if slope is not None:
                xs = np.array([x.min(), x.max()])
                fig.add_scatter(x=xs, y=(intercept + slope * xs) * 100, mode="lines",
                                name="Fitted line", line=dict(color=C["deep"],
                                width=1.5, dash="dash"))
            fig.update_layout(height=330, xaxis_title="looms covered by one operator",
                              yaxis_title="efficiency %")
            st.plotly_chart(fig, width="stretch", config=CH)

        with cr:
            cur_load = float(span.machines_covered.mean())
            cur_eff = float(span.efficiency.mean())
            ops_now = int(span.groupby(["date_key", "shift_code"]).operator_id
                          .nunique().mean().round())
            looms = int(span.groupby(["date_key", "shift_code"])
                        .machines_covered.sum().mean().round())
            add = st.slider("Operators added to each shift", 0, 4, 2)
            if slope is not None and ops_now + add > 0:
                new_load = looms / (ops_now + add)
                new_eff = intercept + slope * new_load
                lift = new_eff - cur_eff
                monthly_target = K["target"] or 0
                gain = lift * monthly_target if monthly_target else 0
                st.markdown(f"""
<div class='floor'>
<div class='en' style='font-size:12px'>Today, on the shifts that name an operator,
one operator carries <b>{cur_load:.1f} looms</b> and those looms run at
<b>{pct(cur_eff)}</b>.</div>
<div class='en' style='font-size:12px;margin-top:9px'>With <b>{add} more
operator{'s' if add != 1 else ''}</b> on each shift, the same {looms} looms would be
carried by {ops_now + add} people — <b>{new_load:.1f} looms each</b>. Operators
already working at that load average <b>{pct(new_eff)}</b>.</div>
<div class='big-te' style='font-family:Inter;margin-top:11px;color:{C["good"] if lift>0 else C["crit"]}'>
{pts(lift)} pts &nbsp;·&nbsp; {fmt_y(gain)} yd in this period</div>
</div>""", unsafe_allow_html=True)
                st.caption(
                    f"Fitted on {len(x):,} operator-shifts. The line explains "
                    f"**{r2*100:.0f}%** of the variation, so it is a real pattern "
                    f"but far from the whole story — a loom that breaks down does "
                    f"not care how many people are on the shift. Treat this as "
                    f"the size of the prize, not a promise, and confirm it by "
                    f"running one shift at the lower load for a fortnight.")
            else:
                st.info("Not enough spread in the loom-per-operator load to fit "
                        "a relationship in this period.", icon="ℹ️")

    # ---- operator × loom -------------------------------------------------- #
    sh("OPERATOR AGAINST LOOM",
       "Where one person is strong on most looms and weak on one, that is a "
       "training gap on that loom. Where a person is weak everywhere, look at "
       "the shift they are on.")
    oms = Q.operator_machine_shift(F)
    if oms.empty:
        st.info("No operator names recorded in this period.", icon="ℹ️")
    else:
        piv = oms.pivot_table(index="operator_name", columns="machine_code",
                              values="efficiency", aggfunc="mean")
        piv = piv.dropna(how="all", axis=0).dropna(how="all", axis=1)
        if piv.size:
            fig = go.Figure(go.Heatmap(
                z=piv.values * 100, x=piv.columns, y=piv.index,
                colorscale=efficiency_scale(125), zmin=0, zmax=125, xgap=1, ygap=1,
                colorbar=dict(title="eff %", thickness=11, len=.7,
                              tickvals=[0, 60, 75, 100, 125]),
                hovertemplate="<b>%{y}</b> on %{x}<br>%{z:.0f}%<extra></extra>"))
            fig.update_layout(height=max(320, 26 * len(piv)),
                              xaxis=dict(tickangle=-60, showgrid=False),
                              yaxis=dict(showgrid=False))
            st.plotly_chart(fig, width="stretch", config=CH)

        summ = (oms.groupby("operator_name")
                   .agg(looms=("machine_code", "nunique"),
                        shifts=("rows", "sum"),
                        net=("net", "sum"), target=("target", "sum"),
                        rejection=("rejection", "sum")).reset_index())
        summ["efficiency"] = summ.net / summ.target.replace(0, np.nan)
        summ = summ.sort_values("efficiency", ascending=False)
        summ.columns = ["Operator", "Looms", "Shifts", "Net yards", "Target",
                        "Rejection", "Efficiency"]
        st.dataframe(summ.style.format({
            "Net yards": "{:,.0f}", "Target": "{:,.0f}", "Rejection": "{:,.0f}",
            "Efficiency": lambda v: "—" if pd.isna(v) else f"{v*100:.1f}%"}),
            width="stretch", hide_index=True, height=340)


# --------------------------------------------------------------------------- #
#  5 · QUALITY
# --------------------------------------------------------------------------- #
with TABS[4]:
    reg = Q.rejection_register_total(F)
    sh("WHY RIBBON IS BEING REJECTED",
       f"{int(reg.get('events') or 0):,} inspection records in this period, "
       f"{fmt_y(reg.get('total'))} yards in total.")

    by = st.radio("Break it down by", ["Reason", "Group", "Loom", "Specification",
                                       "Inspector", "Shift"],
                  horizontal=True, key="rejby")
    key = {"Reason": "reason", "Group": "group", "Loom": "machine",
           "Specification": "spec", "Inspector": "qc", "Shift": "shift"}[by]
    r = Q.rejection_by(F, key)
    if r.empty:
        no_rows()
    else:
        cl, cr = st.columns([1.3, 1])
        with cl:
            top = r.head(14).iloc[::-1]
            fig = go.Figure(go.Bar(
                x=top.yards, y=top.k, orientation="h", marker_color=C["data"],
                text=[fmt_y(v) for v in top.yards], textposition="outside",
                hovertemplate="%{y}<br>%{x:,.0f} yd<extra></extra>"))
            fig.update_layout(height=max(320, 26 * len(top)),
                              xaxis_title="yards rejected",
                              xaxis_range=[0, float(top.yards.max()) * 1.18],
                              margin=dict(l=8, r=70))
            st.plotly_chart(fig, width="stretch", config=CH)
        with cr:
            rr = r.copy()
            rr["share"] = rr.yards / rr.yards.sum()
            rr["running"] = rr.share.cumsum()
            rr.columns = [by, "Events", "Yards", "Kgs", "Looms", "Share", "Running total"]
            st.dataframe(rr.style.format({
                "Yards": "{:,.0f}", "Kgs": "{:,.1f}",
                "Share": "{:.1%}", "Running total": "{:.1%}"}),
                width="stretch", hide_index=True, height=380)
            n80 = int((rr["Running total"] <= 0.8).sum()) + 1
            st.caption(f"**{n80}** of the {len(rr)} entries account for 80% of all "
                       f"rejected yards. Fixing those first is worth more than "
                       f"anything else on this page.")

        sh("REASON AGAINST LOOM", "Dark squares are where one fault keeps happening on one loom.")
        mx = Q.rejection_matrix(F, "reason", "machine")
        if len(mx):
            piv = mx.pivot_table(index="row_k", columns="col_k", values="yards",
                                 aggfunc="sum").fillna(0)
            piv = piv.loc[piv.sum(axis=1).sort_values(ascending=False).index[:14]]
            piv = piv[piv.sum(axis=0).sort_values(ascending=False).index[:40]]
            fig = go.Figure(go.Heatmap(
                z=piv.values, x=piv.columns, y=piv.index, xgap=1, ygap=1,
                colorscale=[[0, C["panel"]], [0.25, "#2E4E52"], [1, C["crit"]]],
                colorbar=dict(title="yd", thickness=11, len=.7),
                hovertemplate="<b>%{y}</b> on %{x}<br>%{z:,.0f} yd<extra></extra>"))
            fig.update_layout(height=max(320, 24 * len(piv)),
                              xaxis=dict(tickangle=-60, showgrid=False),
                              yaxis=dict(showgrid=False))
            st.plotly_chart(fig, width="stretch", config=CH)

        sh("SPECIFICATIONS", "Rejection rate against how much of each is being woven.")
        sp = Q.spec_performance(F)
        if len(sp):
            sp = sp[sp.gross > 0].copy()
            fig = go.Figure(go.Scatter(
                x=sp.gross, y=sp.rejection_rate * 100, mode="markers+text",
                text=np.where(sp.rejection_rate > sp.rejection_rate.quantile(.85),
                              sp.weaving_spec, ""),
                textposition="top center", textfont=dict(size=9, color=C["ink3"]),
                marker=dict(size=np.clip(sp.machines * 3.2, 7, 30),
                            color=sp.rejection_rate * 100,
                            colorscale=[[0, C["good"]], [.5, C["warn"]], [1, C["crit"]]],
                            line=dict(width=0)),
                customdata=np.stack([sp.weaving_spec, sp.machines, sp.net], -1),
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]} looms"
                              "<br>Net %{customdata[2]:,.0f} yd"
                              "<br>Rejection %{y:.2f}%<extra></extra>"))
            fig.update_layout(height=380, xaxis_title="yards woven",
                              yaxis_title="rejection rate %")
            st.plotly_chart(fig, width="stretch", config=CH)
            st.caption("Bubble size is the number of looms running that "
                       "specification. A large bubble high on the chart is a "
                       "specification the whole shed struggles with — that is a "
                       "setting or a yarn question, not an operator question.")


# --------------------------------------------------------------------------- #
#  6 · STOPPAGES
# --------------------------------------------------------------------------- #
with TABS[5]:
    sh("WHY LOOMS STOPPED", "From the stop and restart times on the paper form.")
    dn = Q.downtime(F)
    if dn.empty:
        st.warning(
            "**No stoppage has a time against it yet.**\n\n"
            "This is the one thing the eight months of history cannot tell us. "
            "The old sheets recorded the meter reading and nothing else, so a "
            "loom that stood idle for six hours and one that ran all day look "
            "identical in the data. The WhatsApp group reports stoppages but "
            "almost never a restart, so the length cannot be recovered from it "
            "either.\n\n"
            "Form FM-ZD-01 now has **Stop time**, **Restart time** and a "
            "**Reason code** on every row. From the first week those boxes are "
            "filled, this page fills itself: minutes lost by reason, by loom, "
            "by shift, and who owns the fix.", icon="⏱️")
        rc = Q.options()["stop_reasons"]
        if len(rc):
            st.markdown("**The codes now printed on the form**")
            st.dataframe(rc.rename(columns={"reason_code": "Code",
                                            "reason_text_en": "Reason"}),
                         width="stretch", hide_index=True, height=260)
    else:
        k = st.columns(4)
        with k[0]:
            kpi_card("Stoppages", f"{len(dn):,}", "")
        with k[1]:
            kpi_card("Time lost", f"{dn.down_minutes.sum()/60:,.0f}", "hours")
        with k[2]:
            kpi_card("Average stop", f"{dn.down_minutes.mean():,.0f}", "min")
        with k[3]:
            kpi_card("Looms affected", f"{dn.machine_code.nunique()}", "")
        agg = (dn.groupby(["reason_text_en", "owner_function"])
                 .agg(stops=("downtime_id", "size"),
                      minutes=("down_minutes", "sum")).reset_index()
                 .sort_values("minutes", ascending=False))
        fig = go.Figure(go.Bar(x=agg.minutes / 60, y=agg.reason_text_en,
                               orientation="h", marker_color=C["warn"]))
        fig.update_layout(height=max(300, 26*len(agg)), xaxis_title="hours lost")
        st.plotly_chart(fig, width="stretch", config=CH)
        st.dataframe(dn, width="stretch", hide_index=True, height=420)

    sh("CHANGEOVERS AND RESETS", "What each spec change cost in yards.")
    ch = Q.changeovers(F)
    if ch.empty:
        st.info("No changeover or reset in this period.", icon="ℹ️")
    else:
        cl, cr = st.columns([1.3, 1])
        with cl:
            fig = go.Figure(go.Scatter(
                x=pd.to_datetime(ch.event_date), y=ch.machine_code, mode="markers",
                marker=dict(size=np.clip(ch.cost_yards.fillna(0) / 900, 7, 32),
                            color=ch.cost_yards,
                            colorscale=[[0, C["good"]], [.5, C["warn"]], [1, C["crit"]]],
                            line=dict(width=0)),
                customdata=np.stack([ch.event_type, ch.cost_yards.fillna(0)], -1),
                hovertemplate="<b>%{y}</b> %{x|%d %b}<br>%{customdata[0]}"
                              "<br>Cost %{customdata[1]:,.0f} yd<extra></extra>"))
            fig.update_layout(height=max(330, 15*ch.machine_code.nunique()),
                              xaxis_title="", yaxis_title="")
            st.plotly_chart(fig, width="stretch", config=CH)
        with cr:
            tot = ch.cost_yards.sum()
            st.markdown(f"""
<div class='floor'>
<div class='en' style='font-size:12px'><b>{len(ch)}</b> changeovers and resets in
this period cost about <b>{fmt_y(tot)} yards</b> — {pct(tot/K['gross']) if K['gross'] else '—'}
of everything woven.</div>
<div class='en' style='margin-top:9px'>Cost is measured as the loom's own median
day, over the event day and the two working days before it, less what it
actually produced. It is an estimate of the wind-down, not an exact figure.</div>
</div>""", unsafe_allow_html=True)
            st.dataframe(
                ch[["machine_code", "event_date", "event_type", "cost_yards"]]
                  .rename(columns={"machine_code": "Loom", "event_date": "Date",
                                   "event_type": "Type", "cost_yards": "Cost (yd)"})
                  .style.format({"Cost (yd)": "{:,.0f}"}),
                width="stretch", hide_index=True, height=300)


# --------------------------------------------------------------------------- #
#  7 · DATA HEALTH
# --------------------------------------------------------------------------- #
with TABS[6]:
    sh("WHAT IS WRONG WITH THE DATA ITSELF",
       "Raised by the loader every time a sheet comes in. A figure on this page "
       "is a job for somebody on the floor, not a bug in the dashboard.")

    summ = Q.issue_summary(F)
    if summ.empty:
        st.success("No open data issues in this period.", icon="✅")
    else:
        blocks = summ[summ.severity == "BLOCK"]
        k = st.columns(4)
        with k[0]:
            kpi_card("Blocking problems", f"{int(blocks.n.sum()):,}", "rows",
                     "these rows cannot be trusted as production figures")
        with k[1]:
            kpi_card("Warnings", f"{int(summ[summ.severity=='WARN'].n.sum()):,}", "rows",
                     "the yards are usable, something was not written down")
        with k[2]:
            kpi_card("Data trust", pct(K["trust"]), "",
                     "share of rows read straight off the meter", bar=K["trust"])
        with k[3]:
            kpi_card("Looms affected", f"{int(summ.machines.max() or 0)}", "",
                     "worst single issue")

        show = summ.copy()
        show.columns = ["Issue", "Severity", "Rows", "Looms", "First seen", "Last seen"]
        st.dataframe(
            show.style.map(
                lambda v: (f"color:{C['crit']};font-weight:600" if v == "BLOCK"
                           else f"color:{C['warn']}" if v == "WARN" else ""),
                subset=["Severity"]),
            width="stretch", hide_index=True,
            height=min(460, 42 + 35 * len(show)))

        with st.expander("Every individual row"):
            st.dataframe(Q.issues(F), width="stretch", hide_index=True,
                         height=420)

    sh("HOW MUCH OF EACH MONTH WAS ACTUALLY MEASURED",
       "White is a meter reading. Anything darker was reconstructed during the "
       "forensic rebuild and is worth less in an argument.")
    cm = Q.confidence_matrix()
    if cm.empty:
        no_rows()
    else:
        piv = cm.pivot_table(index="machine_code", columns="month_key",
                             values="trust", aggfunc="mean")
        piv = piv.reindex(sorted(piv.index, reverse=True))
        fig = go.Figure(go.Heatmap(
            z=piv.values * 100, x=piv.columns, y=piv.index, xgap=2, ygap=1,
            colorscale=[[0, C["crit"]], [.7, C["warn"]], [1, C["good"]]],
            zmin=0, zmax=100, colorbar=dict(title="% measured", thickness=11, len=.7),
            hovertemplate="<b>%{y}</b> %{x}<br>%{z:.0f}% measured<extra></extra>"))
        fig.update_layout(height=max(420, 15*len(piv)),
                          xaxis=dict(showgrid=False), yaxis=dict(showgrid=False,
                          tickfont=dict(size=10)))
        st.plotly_chart(fig, width="stretch", config=CH)


# --------------------------------------------------------------------------- #
#  8 · FLOOR BOARD  (Telugu)
# --------------------------------------------------------------------------- #
with TABS[7]:
    st.markdown(f"<div class='sh'><h3>{T.FLOOR_TITLE_EN}</h3>"
                f"<p>{T.FLOOR_TITLE_TE}</p></div>", unsafe_allow_html=True)

    lastday = pd.to_datetime(META["d1"]).date()
    Fday = Q.Filters(d0=lastday, d1=lastday, **base)
    Kd = Q.kpis(Fday)
    Sd = Q.by_shift(Fday)

    c = st.columns(4)
    for col, (en, te, val, sub) in zip(c, [
        (T.K_PRODUCED_EN, T.K_PRODUCED_TE, fmt_y(Kd["net"]) + " yd",
         f"{lastday:%d-%m-%Y}"),
        (T.K_TARGET_EN, T.K_TARGET_TE, fmt_y(Kd["target"]) + " yd",
         pct(Kd["efficiency"]) + " " + T.K_ACHIEVED_TE),
        (T.K_RUNNING_EN, T.K_RUNNING_TE, f"{int(Kd['active'])} / {int(Kd['machines'])}",
         T.K_RUNNING_SUB_TE),
        (T.K_REJECT_EN, T.K_REJECT_TE, fmt_y(Kd["rejection"]) + " yd",
         pct(Kd["rejection_rate"], 2))]):
        with col:
            st.markdown(
                f"<div class='kpi'><div class='lab'>{en}</div>"
                f"<div style='font:600 13px/1.4 \"Noto Sans Telugu\",Inter;"
                f"color:{C['ink2']};margin:-3px 0 6px'>{te}</div>"
                f"<div class='val' style='font-size:25px'>{val}</div>"
                f"<div class='cmp'>{sub}</div></div>", unsafe_allow_html=True)

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    cl, cr = st.columns([1, 1])
    with cl:
        st.markdown(f"<div class='floor'><div class='te'>{T.SHIFT_BOARD_TE}</div>"
                    f"<div class='en'>{T.SHIFT_BOARD_EN}</div></div>",
                    unsafe_allow_html=True)
        Sr = Sd[Sd.shift_code.isin(["A", "B", "C"])]
        if len(Sr):
            rows = []
            for _, r in Sr.iterrows():
                rows.append({T.COL_SHIFT_TE: f"{r.shift_code}",
                             T.COL_PRODUCED_TE: f"{r.net:,.0f}",
                             T.COL_TARGET_TE: f"{r.target:,.0f}" if r.target else "—",
                             T.COL_PCT_TE: pct(r.efficiency) if r.efficiency else "—"})
            st.dataframe(pd.DataFrame(rows), width="stretch",
                         hide_index=True)
        else:
            st.info(T.NO_SHIFT_TE)
    with cr:
        st.markdown(f"<div class='floor'><div class='te'>{T.RULES_TE}</div>"
                    f"<div class='en'>{T.RULES_EN}</div></div>",
                    unsafe_allow_html=True)
        for te, en in T.RULES:
            st.markdown(
                f"<div style='margin:9px 0 0;padding-left:12px;"
                f"border-left:2px solid {C['data']}'>"
                f"<div style='font:600 14px/1.55 \"Noto Sans Telugu\",Inter;"
                f"color:{C['ink']}'>{te}</div>"
                f"<div style='font:400 11px/1.4 Inter;color:{C['ink3']}'>{en}</div>"
                f"</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='sh'><h3>{T.STOPPED_TITLE_EN}</h3>"
                f"<p>{T.STOPPED_TITLE_TE}</p></div>", unsafe_allow_html=True)
    Md = Q.by_machine(Fday)
    stopped = Md[Md.days_producing == 0] if len(Md) else Md
    if len(stopped):
        st.dataframe(
            stopped[["machine_code", "peer_group", "lines_fitted", "operators"]]
            .fillna("—")
            .rename(columns={"machine_code": T.COL_MACHINE_TE,
                             "peer_group": T.COL_PEER_TE,
                             "lines_fitted": T.COL_LINES_TE,
                             "operators": T.COL_OPERATOR_TE}),
            width="stretch", hide_index=True, height=260)
    else:
        st.success(T.ALL_RAN_TE)
