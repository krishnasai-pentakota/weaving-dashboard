# Experiments — including the ones that failed

Several of these are the most useful things in the project, because they closed a line of enquiry that would otherwise have been repeated.

| # | Experiment | Result | Lesson |
|---|---|---|---|
| E-01 | Derive downtime from odometer gaps | **Failed.** 89 of 90 stoppages reported in a supervisors' messaging group fell on days the loom still produced; of 244 fully idle machine-days only 3 appear in the chat | A daily counter cannot produce downtime. Only a stop time and a start time can. Downtime is marked *not measurable* |
| E-02 | Attribute reported stoppages to shifts | **Failed.** Best case 60 % landed in a below-average shift vs 50 % for a coin flip | Hand-written timestamps, minutes or hours late, cannot be attributed to an 8-hour bucket |
| E-03 | Use messaging-group photos as a paper-log archive | **Failed.** Only 38 of 321 media messages (12 %) name a loom within ten minutes | Test the assumption before building the parser |
| E-04 | Suspect the targets | **Disproved — and that was the finding.** Not one target is unreachable | The 18 % / 82 % split came out of an experiment meant to prove the opposite; it redirected the project toward availability |
| E-05 | A loss ladder that balances to zero | **Succeeded, then failed a deeper test** — it balanced while dropping 9,144 yards of rejection | A balance check proves internal consistency, not completeness; the test now compares against the raw fact table |
| E-06 | Is the one-meter multiplier systematically wrong? | **No.** Median booked efficiency 75 % → 70 % → 66 % → 60 % as reported bad lines go 0 → 1 → 2 → 3+ | Representative on average; it is the individual day it cannot describe |
| E-07 | Shift-reading integrity | **Passed.** 8,495 of 8,731 machine-days have the C-shift reading equal to the day's close | The shift readings were not a flaw |
| E-08 | Stopped-loom threshold sensitivity | **Passed.** 63.1 / 62.7 / 62.0 / 61.1 % at 5 / 7 / 10 / 15 days | Not knife-edge, so the plain-language rule (a week) was chosen |
| E-09 | V2 without drill-downs | **Failed in use.** Eight screens, 66 passing tests, every figure correct — and it answered 2–3 of the MD's 12 questions vs V1's 12 | Correctness is not usefulness. The feature list must come from the questions, not from the data model |
| E-10 | Load a date-effective master into a one-row-per-loom table | **Failed, then fixed.** Cardinality violation on seven looms | Collapse to the period in force today; every production row already carries its own lines, specification and target, so no history was lost |
| E-11 | Blank template rows loading as real production | **Caught before it did harm.** All 17,890 laid-out empty rows would have read as looms that "did not run" | A row loads only if somebody typed something on it. Test the loader against the file *after* the spreadsheet has calculated |
| E-12 | Whole-sheet lookup formulas | **Failed on the factory PC, then fixed.** ~600 million evaluations per recalculation; LibreOffice stopped computing near row 31,000 | Narrowed to a 600-row window; the workbook now recalculates 445,358 formulas with zero errors |
| E-13 | Back-solve April line counts from the shift-wise readings sheet | **Withdrawn.** That sheet's production column is `(reading − previous) × header lines`, so the back-solve simply returned the header and proved nothing; every conclusion drawn from it was void | A derived column cannot verify the value it was derived from. Redone from the clerk's daily tab and cross-checked against her Summary |
| E-14 | "April 1–9 exist in no source" | **Withdrawn.** The date search required two-digit days and missed `1-04-2026`…`9-04-2026`; both April tabs run 1–30 | Test the detector before trusting a null result |
| E-15 | Why is April's confidence 91.5 %? | **Answered: it is exactly eight looms** (loom count changed inside April, or started in April with no earlier month to confirm against) and the arithmetic is correct. The audit also showed January, not April, is the worst month for data quality | The number is doing its job; it drew attention to the wrong month |

## Decisions that came out of them

- **D-01** Line count is back-solved per date from the sheet's own arithmetic — headers are never trusted.
- **D-02** Scope is human error and calculation mistakes, ≥ 95 % accuracy — not every overwrite (some are unrecoverable).
- **D-04** PostgreSQL, not SQLite — constraints, one definition per figure, an audit trail.
- **D-05** A loom idle 7+ working days is STOPPED and books no target (sensitivity tested).
- **D-06** Keep only the calculated target — the Summary's own target row reproduces on 0 of 24 February days.
- **D-07** Downtime is *not measurable*; record an idle day as an idle day.
- **D-10** Fix the paper form first, then the workbook, then the database — four of the five missing fields were a habit problem.
- **D-12** Build the canonical loss model first, reconcile it, then build screens — "that sequence prevents us building beautiful screens on top of ambiguous calculations."
- **D-13** Show the unexplained residual rather than force reconciliation to zero — a reconciliation that always balances proves nothing.
- **D-16** Tied rejection is recomputed on every load.
- **D-18** Rejection is entered once, on the rejection-events sheet, and flows to the daily sheet.
