"""Reading the clerk's workbook.

The entry workbook is the only thing the floor touches, and it will keep
changing shape as the paper form settles. So every column is found by its
heading, never by its position, and a heading that moves or gets renamed
raises a clear error naming the tab and the heading rather than silently
loading the wrong column.

Two facts about the source are handled here once, so nothing downstream has to
remember them:

  * The two specification columns are labelled the wrong way round on the entry
    tab. A code is classified by its leading digit - 1 is weaving, 2 is dyeing -
    exactly as the plant numbers them, and never by the heading it arrived
    under.
  * The meter on the loom counts a single line, so the multiplier back up to
    the whole machine is the number of lines actually running, falling back to
    the number fitted when the clerk left it blank.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

TAB_ENTRY = "Daily_Entry"
TAB_MACHINE = "Machine_Master"
TAB_SPEC = "Spec_Master"
TAB_PEOPLE = "People"
TAB_REASONS = "Stop_Reasons"
TAB_REJECT = "Rejection_Events"

# The entry tab carries dropdown source lists to the right of the data. They
# repeat headings such as SHIFT and OPERATOR, so only the data block is read.
ENTRY_DATA_COLUMNS = 44


class SourceError(Exception):
    """The workbook is not shaped the way the loader expects."""


def _num(v):
    """A number, whether Excel stored it as one or as text.

    A figure typed into a cell formatted as text is the commonest accident in a
    hand-kept workbook, and it is invisible on screen. Reading it as a number
    here means a line count or a reason code entered that way still counts,
    instead of being silently dropped and nobody noticing for a month.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if s:
            try:
                return float(s)
            except ValueError:
                return None
    return None


def _int(v):
    n = _num(v)
    return int(round(n)) if n is not None else None


def _text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _upper(v):
    s = _text(v)
    return s.upper() if s else None


def _date(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str) and v.strip():
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                return dt.datetime.strptime(v.strip()[:10], fmt).date()
            except ValueError:
                pass
    return None


class Tab:
    """A worksheet addressed by column heading."""

    def __init__(self, sheet, header_row: int = 1, max_columns: int | None = None):
        self.name = sheet.title
        self._rows = sheet.iter_rows(min_row=header_row, values_only=True)
        header = list(next(self._rows))
        if max_columns:
            header = header[:max_columns]
        self._width = len(header)
        self.columns: dict[str, int] = {}
        for i, h in enumerate(header):
            key = _upper(h)
            if key and key not in self.columns:   # first wins; lists repeat later
                self.columns[key] = i

    def index(self, heading: str) -> int:
        i = self.columns.get(heading.upper())
        if i is None:
            raise SourceError(
                f"Tab {self.name!r} has no column headed {heading!r}. "
                f"Headings found: {', '.join(sorted(self.columns))}")
        return i

    def require(self, *headings: str) -> None:
        missing = [h for h in headings if h.upper() not in self.columns]
        if missing:
            raise SourceError(
                f"Tab {self.name!r} is missing {len(missing)} expected "
                f"column(s): {', '.join(missing)}")

    def rows(self):
        for n, row in enumerate(self._rows, start=2):
            yield n, row[:self._width]


def classify_specs(a, b) -> tuple[str | None, str | None]:
    """Return (weaving 1xxxx, dyeing 2xxxx) from two codes in unknown order."""
    weaving = dyeing = None
    for code in (_upper(a), _upper(b)):
        if not code:
            continue
        if code.startswith("1"):
            weaving = weaving or code
        elif code.startswith("2"):
            dyeing = dyeing or code
        else:                      # an unexpected prefix: keep it, do not lose it
            weaving = weaving or code
    return weaving, dyeing


# ---------------------------------------------------------------------------
#  Record shapes handed to the loader
# ---------------------------------------------------------------------------
@dataclass
class MachineRow:
    machine_code: str
    line_group: str
    model: str
    peer_group: str
    is_commissioned: bool
    lines_fitted: int | None
    target_per_line_day: float | None
    target_source: str | None
    weaving_spec: str | None
    dyeing_spec: str | None
    opening_reading_m: float | None
    data_warning: str | None


@dataclass
class SpecRow:
    weaving_spec: str
    dyeing_spec: str | None
    per_yard_weight_g: float | None
    per_yard_price: float | None
    in_production: bool


@dataclass
class StaffRow:
    staff_name: str
    role: str
    emp_no: str | None
    is_current: bool
    machine_range: str | None


@dataclass
class ReasonRow:
    reason_code: int
    reason_text_en: str
    owner_function: str


@dataclass
class EntryRow:
    source_row: int
    date_key: dt.date
    shift_code: str
    machine_code: str
    weaving_spec: str | None
    dyeing_spec: str | None
    lines_fitted: int | None
    lines_running: int | None
    single_line_share: float | None
    machine_status: str
    event: str | None
    remarks: str | None
    previous_reading_m: float | None
    current_reading_m: float | None
    rebase_override_m: float | None
    stop_time: dt.time | None
    restart_time: dt.time | None
    stop_reason: str | None
    rejection_yards: float
    target_yards: float | None
    operator: str | None
    supervisor: str | None
    qc_name: str | None
    confidence: str
    confidence_why: str | None
    source_note: str | None
    line_count_change: str | None
    spec_change: str | None
    # what the source sheet itself computed, kept only to verify the database
    sheet_gross_yards: float | None
    sheet_net_yards: float | None


@dataclass
class RejectionRow:
    source_row: int
    date_key: dt.date
    shift_code: str
    machine_code: str
    weaving_spec: str | None
    rejection_yards: float
    weight_per_yard_g: float | None
    rejection_kgs: float | None
    primary_reason: str | None
    addon_reason: str | None
    qc_name: str | None
    supervisor: str | None
    tied_to_production: bool


@dataclass
class Workbook:
    path: Path
    machines: list[MachineRow] = field(default_factory=list)
    specs: list[SpecRow] = field(default_factory=list)
    staff: list[StaffRow] = field(default_factory=list)
    reasons: list[ReasonRow] = field(default_factory=list)
    entries: list[EntryRow] = field(default_factory=list)
    rejections: list[RejectionRow] = field(default_factory=list)


def read(path: str | Path, *, entries: bool = True) -> Workbook:
    path = Path(path)
    if not path.is_file():
        raise SourceError(f"No such workbook: {path}")
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = Workbook(path=path)

    missing = [t for t in (TAB_ENTRY, TAB_MACHINE, TAB_SPEC, TAB_PEOPLE)
               if t not in wb.sheetnames]
    if missing:
        raise SourceError(
            f"{path.name} is missing the tab(s): {', '.join(missing)}. "
            f"Tabs present: {', '.join(wb.sheetnames)}")

    out.machines = _read_machines(wb[TAB_MACHINE])
    out.specs = _read_specs(wb[TAB_SPEC])
    out.staff = _read_people(wb[TAB_PEOPLE])
    if TAB_REASONS in wb.sheetnames:
        out.reasons = _read_reasons(wb[TAB_REASONS])
    if TAB_REJECT in wb.sheetnames:
        out.rejections = _read_rejections(wb[TAB_REJECT])
    if entries:
        out.entries = _read_entries(wb[TAB_ENTRY])
    wb.close()
    return out


def _read_machines(sheet) -> list[MachineRow]:
    t = Tab(sheet)
    t.require("MACHINE", "LINE GROUP", "MODEL (S/D)", "PEER GROUP", "COMMISSIONED",
              "LINES FITTED")
    c = t.columns
    i_target = next((c[h] for h in c if h.startswith("TARGET PER LINE")), None)
    out = []
    for n, r in t.rows():
        code = _upper(r[t.index("MACHINE")])
        # The tab carries an explanatory note under the heading; a real machine
        # code is always two letters, a dash and two digits.
        if not code or len(code) != 5 or code[2] != "-" or not code[3:].isdigit():
            continue
        w, d = classify_specs(r[c.get("SPECIFICATION (WEAVING)", 0)],
                              r[c.get("SPECIFICATION (DYEING)", 0)])
        opening = next((c[h] for h in c if h.startswith("OPENING READING")), None)
        out.append(MachineRow(
            machine_code=code,
            line_group=_upper(r[t.index("LINE GROUP")]) or ("L-A" if code.startswith("MA") else "L-B"),
            model=(_upper(r[t.index("MODEL (S/D)")]) or "S")[:1],
            peer_group=_text(r[t.index("PEER GROUP")]) or "UNGROUPED",
            is_commissioned=_upper(r[t.index("COMMISSIONED")]) != "NO",
            lines_fitted=_int(r[t.index("LINES FITTED")]) or None,
            target_per_line_day=_num(r[i_target]) if i_target is not None else None,
            target_source=_text(r[c["TARGET SOURCE"]]) if "TARGET SOURCE" in c else None,
            weaving_spec=w, dyeing_spec=d,
            opening_reading_m=_num(r[opening]) if opening is not None else None,
            data_warning=_text(r[c["CHECK"]]) if "CHECK" in c else None,
        ))
    if not out:
        raise SourceError(f"Tab {sheet.title!r} produced no machines.")
    return out


def _read_specs(sheet) -> list[SpecRow]:
    t = Tab(sheet)
    # Both specification columns carry the same heading in the source, so they
    # are taken by position within the tab and then classified by prefix.
    out, seen = [], set()
    for n, r in t.rows():
        w, d = classify_specs(r[0], r[1] if len(r) > 1 else None)
        if not w or w in seen:
            continue
        seen.add(w)
        out.append(SpecRow(
            weaving_spec=w, dyeing_spec=d,
            per_yard_weight_g=_num(r[2]) if len(r) > 2 else None,
            per_yard_price=_num(r[3]) if len(r) > 3 else None,
            in_production=(_upper(r[4]) if len(r) > 4 else None) != "NO",
        ))
    return out


# A person's name is short. The reference tabs carry explanatory notes written
# into the same columns as the data, and one of them was loaded as an operator
# before this guard existed. Anything sentence-shaped is a note, not a person.
MAX_NAME_LEN = 60
MAX_NAME_WORDS = 5


def looks_like_a_note(value: str) -> bool:
    """True for an explanatory sentence typed into a name column.

    Judged on length and word count only. An initial with a full stop after it
    is an ordinary Indian name — L. APPALA NAIDU is a person, not a sentence —
    so punctuation is deliberately not part of the test.
    """
    return len(value) > MAX_NAME_LEN or len(value.split()) > MAX_NAME_WORDS


def _read_people(sheet) -> list[StaffRow]:
    t = Tab(sheet)
    t.require("ROLE", "NAME")
    c = t.columns
    out, seen = [], set()
    for n, r in t.rows():
        name = _upper(r[t.index("NAME")])
        role = _upper(r[t.index("ROLE")])
        if not name or not role or looks_like_a_note(name):
            continue
        if role not in ("OPERATOR", "SUPERVISOR", "QC", "HOD"):
            role = "OPERATOR"
        if (name, role) in seen:
            continue
        seen.add((name, role))
        cur = _upper(r[c["CURRENTLY WORKING"]]) if "CURRENTLY WORKING" in c else "YES"
        out.append(StaffRow(
            staff_name=name, role=role,
            emp_no=_text(r[c["EMP NO"]]) if "EMP NO" in c else None,
            is_current=(cur != "NO"),
            machine_range=_text(r[c["MACHINE RANGE"]]) if "MACHINE RANGE" in c else None,
        ))
    return out


def _read_reasons(sheet) -> list[ReasonRow]:
    t = Tab(sheet)
    if "CODE" not in t.columns:
        return []
    c = t.columns
    out = []
    for n, r in t.rows():
        code = _int(r[t.index("CODE")])
        text = _upper(r[c.get("STOP REASON", 1)])
        if code is None or code <= 0 or not text:
            continue
        out.append(ReasonRow(
            reason_code=code, reason_text_en=text,
            owner_function=_text(r[c["WHO FIXES IT"]]) if "WHO FIXES IT" in c else "UNASSIGNED",
        ))
    return out


def _read_rejections(sheet) -> list[RejectionRow]:
    t = Tab(sheet)
    t.require("DATE", "MACHINE", "SHIFT", "REJ YARDS")
    c = t.columns
    i_spec = next((c[h] for h in c if h.startswith("SPECIFICATION")), None)
    i_w = next((c[h] for h in c if h.startswith("WEIGHT PER YARD")), None)
    out = []
    for n, r in t.rows():
        d = _date(r[t.index("DATE")])
        yards = _num(r[t.index("REJ YARDS")])
        machine = _upper(r[t.index("MACHINE")])
        if not d or not machine or not yards or yards <= 0:
            continue
        w, _dye = classify_specs(r[i_spec] if i_spec is not None else None, None)
        tied = _upper(r[c["TIED TO A PRODUCTION DAY"]]) if "TIED TO A PRODUCTION DAY" in c else "YES"
        out.append(RejectionRow(
            source_row=n, date_key=d,
            shift_code=(_upper(r[t.index("SHIFT")]) or "DAY"),
            machine_code=machine, weaving_spec=w,
            rejection_yards=float(yards),
            weight_per_yard_g=_num(r[i_w]) if i_w is not None else None,
            rejection_kgs=_num(r[c["REJ KGS"]]) if "REJ KGS" in c else None,
            primary_reason=_upper(r[c["PRIMARY REASON"]]) if "PRIMARY REASON" in c else None,
            addon_reason=_upper(r[c["ADD-ON REASON"]]) if "ADD-ON REASON" in c else None,
            qc_name=_upper(r[c["QC NAME"]]) if "QC NAME" in c else None,
            supervisor=_upper(r[c["SUPERVISOR"]]) if "SUPERVISOR" in c else None,
            tied_to_production=(tied != "NO"),
        ))
    return out


def _read_entries(sheet) -> list[EntryRow]:
    t = Tab(sheet, max_columns=ENTRY_DATA_COLUMNS)
    t.require("DATE", "MACHINES", "SHIFT", "LINES FITTED",
              "PREVIOUS READING (M)", "CURRENT READING (M)")
    c = t.columns

    def col(name, default=None):
        return c.get(name.upper(), default)

    i_share = next((c[h] for h in c if h.startswith("MEASURED SHARE")), None)
    i_over = next((c[h] for h in c if h.startswith("RESET / RE-BASE")), None)
    out = []
    for n, r in t.rows():
        d = _date(r[t.index("DATE")])
        machine = _upper(r[t.index("MACHINES")])
        if not d or not machine:
            continue
        # A future entry row is a template: dates and formulas, nothing typed.
        # CONFIDENCE is written only where a real reading exists.
        confidence = _upper(r[col("CONFIDENCE")]) if col("CONFIDENCE") is not None else None
        if not confidence:
            continue
        w, dy = classify_specs(r[col("SPECIFICATION (WEAVING)")],
                               r[col("SPECIFICATION (DYEING)")])
        fitted = _int(r[t.index("LINES FITTED")])
        running = _int(r[col("LINES ACTUALLY RUNNING")]) if col("LINES ACTUALLY RUNNING") is not None else None
        out.append(EntryRow(
            source_row=n, date_key=d,
            shift_code=_upper(r[t.index("SHIFT")]) or "DAY",
            machine_code=machine, weaving_spec=w, dyeing_spec=dy,
            lines_fitted=fitted or None,
            lines_running=running or None,
            single_line_share=_num(r[i_share]) if i_share is not None else None,
            machine_status=_upper(r[col("MACHINE STATUS")]) or "RUNNING",
            event=_upper(r[col("EVENT")]) if col("EVENT") is not None else None,
            remarks=_text(r[col("REMARKS")]) if col("REMARKS") is not None else None,
            previous_reading_m=_num(r[t.index("PREVIOUS READING (M)")]),
            current_reading_m=_num(r[t.index("CURRENT READING (M)")]),
            rebase_override_m=_num(r[i_over]) if i_over is not None else None,
            stop_time=r[col("STOP TIME")] if col("STOP TIME") is not None else None,
            restart_time=r[col("RESTART TIME")] if col("RESTART TIME") is not None else None,
            stop_reason=_upper(r[col("STOP REASON")]) if col("STOP REASON") is not None else None,
            rejection_yards=float(_num(r[col("REJECTION YARDS")]) or 0),
            target_yards=_num(r[col("TARGET YARDS")]),
            operator=_upper(r[col("OPERATOR")]) if col("OPERATOR") is not None else None,
            supervisor=_upper(r[col("SUPERVISOR")]) if col("SUPERVISOR") is not None else None,
            qc_name=_upper(r[col("QC NAME")]) if col("QC NAME") is not None else None,
            confidence=confidence,
            confidence_why=_text(r[col("WHY")]) if col("WHY") is not None else None,
            source_note=_text(r[col("SOURCE")]) if col("SOURCE") is not None else None,
            line_count_change=_text(r[col("LINE COUNT CHANGE")]) if col("LINE COUNT CHANGE") is not None else None,
            spec_change=_text(r[col("SPEC CHANGE")]) if col("SPEC CHANGE") is not None else None,
            sheet_gross_yards=_num(r[col("TOTAL YARDS")]),
            sheet_net_yards=_num(r[col("NET YARDS")]),
        ))
    if not out:
        raise SourceError(
            f"Tab {sheet.title!r} produced no completed rows. A row counts as "
            f"completed when its CONFIDENCE column has been filled in.")
    return out
