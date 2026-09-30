# V1 vs V2 — the comparison that found the silent redefinitions

Method: every metric V1 defines was traced into V2's SQL and checked for three outcomes — **missing**, **present and identical**, or **present but redefined**. The third is the dangerous category: nothing looks absent, so nobody checks. Sources read in full: V1's query layer and app, V2's schema, 16 views, analytics functions, loader and app, and the three workbooks.

## The short version

**V1 is an analytical model; V2 is an operational data and decision model.** V2 is not simply a cleaner V1 — it changes the underlying model. V1's tables are shaped around *questions* (where is the problem, how large, compared with what, is it machine, shift, staff, quality or target, is it persistent). V2's are shaped around *records* (what happened, what was measured, what was reconstructed, can I trust this number).

| Capability | V1 (SQLite + Streamlit) | V2 (PostgreSQL + Streamlit) |
|---|---|---|
| Data architecture, ETL, constraints, audit trail | Partial | **Strong** |
| Raw fact richness | Strong | **Stronger** — stop and restart time, downtime minutes, stop reason, lines actually running, measured share, confidence and *why*, source, validation check, operator and supervisor separately |
| Reconciliation against the department sheet | **Excellent** | Added in the analytics layer |
| Accounting basis (target / rejection / measured-only / un-split) | **Excellent** | Present in the data; exposed in the analytics layer |
| Loss attribution (waterfall that balances to the gap) | **Very detailed** | Simplified, then rebuilt in the analytics layer |
| Machine diagnosis with peer comparison | **Strong** | Added in the analytics layer |
| Persistent underperformers | **Strong** | Added in the analytics layer |
| Shift and people diagnosis | Strong | Strong; adds a capacity what-if |
| Quality, stoppages, data health | Strong / limited / good | **Stronger** in all three |
| Floor usability, bilingual operation | Weak / none | **Excellent** / yes |
| Filter and control model | **Excellent** | Less explicit |

## What V1 got right — the analytical model

V1 carried explicit analytical tables between the raw facts and the management question:

```text
Facts       F_Shift (one row per loom × date × shift, 29 columns)   F_Rejection (one row per QC event)
Dimensions  D_Machine   D_People   D_Reason   D_Spec   D_Calendar
Aggregates  A_Machine   A_Month    A_Shift    A_Staff
```

`F_Shift` puts production, target, organisation, machine, shift, specification, data basis and change events into one analytical grain — which is why cross-sectional analysis is cheap. The aggregate tables *answer* rather than describe. For example, a single `A_Machine` row gives a diagnostic profile rather than a verdict:

| Field | Example loom (June–August window) |
|---|---|
| Net yards | 557,294 |
| Efficiency | 26.6 % |
| Peer-group efficiency | 70.9 % |
| **Versus peer** | **−44.3 points** |
| Zero-production shifts | 33 |
| Unread shifts | 40 |
| Reset shifts / line-change days | 1 / 8 |

That decomposes "this loom is bad" into: how large, relative to what, whether it was simply not running, whether data quality contributes, and whether setup or line changes are involved. V1 also ranked **persistent** underperformers — for instance one loom in the bottom group in 12 of 14 weeks and another in 10 of 14 — which separates an isolated bad week from a systemic problem.

**V1's reconciliation worked as an explanation, not a display.** For August it compared the dashboard with the department's own sheet and decomposed each difference:

| | Dashboard | Department | Explained by |
|---|---:|---:|---|
| Actual yards | 6,670,254 | 6,622,050 | +48,204 (+0.73 %) shown as a difference to be traced |
| Rejection | 72,248 tied + 8,764 on non-production days = 81,012 | 90,529 | residual **9,517** left visible |
| Target | 9,812,692 as recorded + 1,390,508 on machine-days with no target = 11,203,200 | 10,310,775 | the choice of basis |
| Operating machines | 68 of 70 distinct looms; 57.42 daily average | 64.25 | two honest definitions, both shown |

**V1's control model** treated a KPI as *a number produced under a stated accounting rule*: granularity and period; filters for shift, line group, peer group, machine, specification and staff; an accounting basis (production target *as recorded* vs *full working calendar*; rejection *tied to the production day* vs *full QC register*); and data options (*measured readings only*; *exclude un-split machine-days*).

## What V2 got right — the operational model

V2 captures what V1 never did, and turns "what was the number?" into "can I trust it?": a per-row confidence with a plain-language reason, a validation check on every row, a data-health register (for example, one week showed 17 blocking problems, 948 warnings and 89.2 % data trust across 64 looms), stop and restart capture, target review, specification roll-ups, an audit log with the yards effect of each correction, and a bilingual floor board. V2's ladder is also *more complete* than V1's: it carries the untargeted production and rejection that V1 silently drops.

## The two are complementary

V2 had the ingredients for reconciliation and diagnosis — production, target, rejection, source, confidence, the QC register and an audit log — but not yet the analytical application layer on top. The analytics layer was built to supply it, in a deliberate order: the canonical production and loss model first, reconciled against V1's numbers, and only then screens.

## Two corrections to my own first pass
A first comparison at the level of tab and column *names* was too shallow. Reading the code changed two conclusions: V2 **does** carry the accounting basis (calendar vs recorded target, tied vs register rejection, measured-only) and **does** carry peer comparison — both restored in the analytics layer.

## The five silent redefinitions

| # | Metric | V1 | V2 | Why it matters |
|---|---|---|---|---|
| 1 | `yards_per_line` | net ÷ lines **fitted** | net ÷ lines **running** | Same name, different denominator. Where the clerk had not filled "lines running", the loader fell back to lines fitted — one column, two definitions, decided by whether a clerk typed something. Fix: carry an explicit basis column |
| 2 | Peer efficiency | whole filtered period; includes changeover and non-producing shifts; target as recorded; numerator net | partitioned by month; excludes changeover and non-producing shifts; achievable target; numerator gross | Five differences; a number quoted from one will not reproduce in the other. V2 also mixes gross and net (≈ one point of systematic bias) |
| 3 | Loss attribution | Seven exclusive causes incl. "machine below its peer group" vs "peer group below target" and "reading not captured"; residual forced to balance | Ladder incl. "loom-days never recorded", "lines not deployed", "woven with no target set"; merges both peer buckets into "ran below the rate asked" | The V1 split separates two management actions (send a fitter to a loom vs the target for a machine class is wrong). V2's ladder is more complete: it carries 9,144 yards of untargeted rejection that V1 silently drops |
| 4 | Machines operating | Both a daily average and a distinct count | Distinct count only | The department's figure is a daily average; showing both settles a recurring reconciliation dispute |
| 5 | Unread readings | Own loss step — a recording failure is a *data* loss, not a *production* loss | Counted but charged to the loom | With 588 no-reading rows, a recording failure is booked as a machine failure |

**Verdict.** V1 had the stronger analysis in early September when it was the only thing built. After the analytics layer, V2 is ahead on most axes — it has everything V1 had except four loss-attribution refinements, plus a great deal V1 never had. The remaining risk was never *missing* capability; it was the silent redefinitions, where two dashboards answer the same question with different arithmetic and nothing announces it.

**V2-only capabilities:** downtime detail, stop reasons, confidence matrix, data-health issue register, changeover cost, span of control, availability/rate/both diagnosis, target-review verdicts, recovery scenarios, quarter grain, the bilingual floor board, and department-sheet reconciliation by month.

## Defects the audit found in V1

- **V1 printed 133.70 % efficiency.** Eight months of production over four months of target: targets do not exist before June (January–April have no target at all; May 17 % coverage and prints 263.2 %). A coverage guard existed and was wired into only one tab; the `ANALYSIS_WINDOW` flag marked Jan–May "trend only" on every row and no query filtered on it. *Two safety mechanisms were built and neither was connected.*
- **Two confidence systems that disagree.** The workbook's confidence asks "can this loom count be confirmed from another month?" (January 100 %). V1's database trust asks "was this shift split A/B/C?" (January 56.5 %, with 452 lumped rows carrying 1,753,066 yards). They share a word and both reach a screen.
- **Operator ranking on almost nothing** — staff names are missing on 100 % of January–March rows and 83 % of May.
- **408 rows with rejection above production** (22,053 yards, 56 looms) and **316 rows** with zero production but rejection logged.

## Defects the audit found in V2 (reproduced live)

- **The loader crashed on the real workbook.** The machine master already carried validity periods (84 rows, 76 distinct looms) while the schema said one row per loom — a cardinality violation on every changeover. The workbook was right and the schema was wrong; fixed by loading the period in force today, since every production row carries its own lines, specification and target.
- **Zero rejection events loaded** from the September workbook, which had lost the rejection-events tab; one machine-shift can have several events with different reasons and inspectors, and collapsing them to one number lost the reason breakdown and the inspector attribution. Restored as a separate events sheet feeding the daily sheet.

## What was done well (recorded on purpose)
The department-sheet check detected that its December–March rejection figures are off by roughly 400× (a unit or scale error) and correctly excluded them. Reasoning that existed only in V1's code comments — why the target argument exists (an idle loom costs nothing in the recorded basis but is charged every day in the department's), why gross must follow the rejection basis, why the default period must have a minimum length — was identified as worth preserving.
