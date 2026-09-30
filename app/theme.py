"""One palette, one set of type rules, defined once.

The screen is read in a weaving shed office and in the MD's room, often on an
old monitor. So: high contrast, no thin grey-on-grey, numbers in a monospaced
face so a column of yards lines up, and colour used only to mean something.

Colour carries exactly one meaning throughout:
    green  — at or above what was expected
    amber  — needs attention this week
    red    — needs a decision now
Nothing is coloured for decoration.
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# --------------------------------------------------------------------------- #
C = {
    "bg":        "#12141A",   # graphite, not black: less glare under tube light
    "panel":     "#1A1D26",
    "panel2":    "#222633",
    "line":      "#2E3342",
    "line_soft": "#252936",
    "ink":       "#EDEFF5",
    "ink2":      "#A8AEC0",
    "ink3":      "#6E7588",
    "data":      "#4FC3C7",   # textile teal — the default series colour
    "deep":      "#5B7CFA",   # indigo — comparison / previous period
    "good":      "#3FB98B",
    "warn":      "#E0A040",
    "crit":      "#E05A5A",
    "neutral":   "#7A8299",
    "accent":    "#C9A227",   # brass — used sparingly, for the masthead rule
}

BAND_C = {"good": C["good"], "warn": C["warn"], "crit": C["crit"], "flat": C["neutral"]}


def band(v: float | None) -> str:
    """Traffic light for a 0-1 ratio where higher is better."""
    if v is None or v != v:
        return "flat"
    if v >= 0.75:
        return "good"
    if v >= 0.60:
        return "warn"
    return "crit"


def band_colour(v):
    return BAND_C[band(v)]


def efficiency_scale(zmax: float = 125.0):
    """A three-band colour scale for an efficiency heat-map, in percent.

    Written as a function because the band edges have to be expressed as a
    fraction of zmax, and doing that by hand is how a 75% cell ends up painted
    red. Red below 60, amber 60 to 75, green at or above 75 - the same three
    bands as band() above, and they cannot drift apart.
    """
    lo, hi = 60.0 / zmax, 75.0 / zmax
    return [[0.0, C["crit"]], [lo, C["crit"]],
            [lo, C["warn"]], [hi, C["warn"]],
            [hi, C["good"]], [1.0, C["good"]]]


# --------------------------------------------------------------------------- #
#  Number formatting. Yards are large and are read aloud in meetings, so they
#  are grouped and never shown in scientific notation or with false precision.
# --------------------------------------------------------------------------- #
def fmt_y(v) -> str:
    if v is None or v != v:
        return "—"
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:,.2f}M"
    return f"{v:,.0f}"


def fmt_n(v, dp=0) -> str:
    if v is None or v != v:
        return "—"
    return f"{float(v):,.{dp}f}"


def pct(v, dp=1) -> str:
    if v is None or v != v:
        return "—"
    return f"{float(v)*100:,.{dp}f}%"


def pts(v, dp=1) -> str:
    if v is None or v != v:
        return "—"
    return f"{float(v)*100:+,.{dp}f}"


def signed(v, dp=0) -> str:
    if v is None or v != v:
        return "—"
    return f"{float(v):+,.{dp}f}"


# --------------------------------------------------------------------------- #
def plotly_template() -> None:
    t = go.layout.Template()
    t.layout = go.Layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif",
                  size=12, color=C["ink2"]),
        title=dict(font=dict(size=13, color=C["ink"])),
        margin=dict(l=10, r=10, t=32, b=10),
        xaxis=dict(gridcolor=C["line_soft"], zerolinecolor=C["line"],
                   linecolor=C["line"], tickfont=dict(size=11)),
        yaxis=dict(gridcolor=C["line_soft"], zerolinecolor=C["line"],
                   linecolor=C["line"], tickfont=dict(size=11)),
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11),
                    orientation="h", yanchor="bottom", y=1.02, x=0),
        colorway=[C["data"], C["deep"], C["warn"], C["good"], C["crit"], C["accent"]],
        hoverlabel=dict(bgcolor=C["panel2"], bordercolor=C["line"],
                        font=dict(color=C["ink"], size=12)),
    )
    pio.templates["weaving"] = t
    pio.templates.default = "weaving"


# --------------------------------------------------------------------------- #
def css() -> str:
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

html, body, [class*="css"] {{ font-family:Inter, "Segoe UI", system-ui, sans-serif; }}
.stApp {{ background:{C['bg']}; }}
#MainMenu, footer, header {{ visibility:hidden; }}
.block-container {{ padding-top:1.1rem; padding-bottom:3rem; max-width:1650px; }}

/* ---- masthead ---------------------------------------------------------- */
.mast {{ display:flex; align-items:center; justify-content:space-between;
        gap:20px; flex-wrap:wrap; padding:2px 0 10px; }}
.mast .bd b {{ font:800 21px/1 Inter; color:{C['ink']}; letter-spacing:.02em; }}
.mast .bd span {{ font:600 11px/1 Inter; color:{C['ink3']};
        letter-spacing:.20em; margin-left:12px; text-transform:uppercase; }}
.mast .sp {{ display:flex; gap:26px; flex-wrap:wrap; }}
.mast .sp div {{ display:flex; flex-direction:column; gap:3px; }}
.mast .sp u {{ font:600 9px/1 Inter; letter-spacing:.15em; color:{C['ink3']};
        text-decoration:none; text-transform:uppercase; }}
.mast .sp b {{ font:600 13px/1 "IBM Plex Mono"; color:{C['ink']}; }}
.dot {{ display:inline-block; width:7px; height:7px; border-radius:50%;
        background:{C['good']}; margin-right:6px; vertical-align:middle; }}

/* a single woven rule: two threads crossing. The only ornament on the page. */
.warp {{ height:3px; margin:0 0 18px;
        background:repeating-linear-gradient(90deg,
            {C['accent']} 0 12px, transparent 12px 20px),
            linear-gradient(90deg, {C['line']}, transparent 70%);
        opacity:.5; border-radius:2px; }}

/* ---- section heading ---------------------------------------------------- */
.sh {{ margin:26px 0 12px; }}
.sh h3 {{ font:700 13px/1.2 Inter; letter-spacing:.13em; color:{C['ink']};
        text-transform:uppercase; margin:0 0 3px; }}
.sh p {{ font:400 12px/1.5 Inter; color:{C['ink3']}; margin:0; }}

/* ---- KPI card ----------------------------------------------------------- */
.kpi {{ background:{C['panel']}; border:1px solid {C['line']}; border-radius:9px;
        padding:14px 15px 13px; height:100%; position:relative; overflow:hidden; }}
.kpi .lab {{ font:600 9.5px/1.3 Inter; letter-spacing:.14em; color:{C['ink3']};
        text-transform:uppercase; margin-bottom:7px; min-height:24px; }}
.kpi .val {{ font:700 30px/1 "IBM Plex Mono"; color:{C['ink']}; letter-spacing:-.02em; }}
.kpi .val small {{ font:500 12px/1 Inter; color:{C['ink3']}; margin-left:5px; }}
.kpi .cmp {{ font:400 11px/1.45 Inter; color:{C['ink3']}; margin-top:7px; min-height:16px; }}
.kpi .foot {{ font:400 10.5px/1.45 Inter; color:{C['ink3']}; margin-top:5px;
        padding-top:6px; border-top:1px solid {C['line_soft']}; }}
.kpi b.up   {{ color:{C['good']}; font-weight:600; }}
.kpi b.down {{ color:{C['crit']}; font-weight:600; }}
.kpi b.flat, .kpi .flat {{ color:{C['neutral']}; font-weight:500; }}
.thread {{ height:4px; background:{C['line_soft']}; border-radius:2px; margin-top:10px; }}
.thread i {{ display:block; height:100%; border-radius:2px; }}

/* ---- attention card ----------------------------------------------------- */
.acard {{ display:flex; background:{C['panel']}; border:1px solid {C['line']};
        border-radius:9px; overflow:hidden; height:100%; }}
.acard .stripe {{ width:4px; flex:0 0 4px; }}
.acard .in {{ padding:13px 14px; flex:1; min-width:0; }}
.acard .rank {{ font:700 8.5px/1 Inter; letter-spacing:.16em; color:{C['ink3']};
        text-transform:uppercase; }}
.acard h4 {{ font:700 17px/1.2 Inter; color:{C['ink']}; margin:7px 0 3px; }}
.acard .sub {{ font:400 11px/1.45 Inter; color:{C['ink2']}; }}
.acard .big {{ font:700 19px/1 "IBM Plex Mono"; margin:8px 0 4px; }}
.pill {{ display:inline-block; font:600 9px/1 Inter; letter-spacing:.09em;
        padding:4px 7px; border-radius:4px; margin-top:6px; text-transform:uppercase; }}
.p-crit {{ background:rgba(224,90,90,.14); color:{C['crit']}; }}
.p-warn {{ background:rgba(224,160,64,.14); color:{C['warn']}; }}
.p-good {{ background:rgba(63,185,139,.14); color:{C['good']}; }}
.p-neut {{ background:rgba(122,130,153,.14); color:{C['neutral']}; }}

/* ---- floor (Telugu) panel ----------------------------------------------- */
.floor {{ background:{C['panel']}; border:1px solid {C['line']};
        border-left:4px solid {C['data']}; border-radius:9px; padding:15px 17px; }}
.floor .te {{ font:600 16px/1.6 "Noto Sans Telugu","Nirmala UI","Gautami",Inter,sans-serif; color:{C['ink']}; }}
.floor .en {{ font:400 11.5px/1.5 Inter; color:{C['ink3']}; margin-top:2px; }}
.big-te {{ font:700 21px/1.5 "Noto Sans Telugu","Nirmala UI","Gautami",Inter,sans-serif; color:{C['ink']}; }}

/* ---- widgets ------------------------------------------------------------ */
section[data-testid="stSidebar"] {{ background:{C['panel']};
        border-right:1px solid {C['line']}; }}
.stTabs [data-baseweb="tab-list"] {{ gap:2px; border-bottom:1px solid {C['line']}; }}
.stTabs [data-baseweb="tab"] {{ height:38px; padding:0 15px; background:transparent;
        font:600 10.5px/1 Inter; letter-spacing:.1em; color:{C['ink3']}; }}
.stTabs [aria-selected="true"] {{ color:{C['ink']} !important;
        border-bottom:2px solid {C['accent']}; }}
div[data-testid="stMetricValue"] {{ font-family:"IBM Plex Mono"; }}
.stDataFrame {{ border:1px solid {C['line']}; border-radius:8px; }}
hr {{ border-color:{C['line_soft']}; }}
</style>"""
