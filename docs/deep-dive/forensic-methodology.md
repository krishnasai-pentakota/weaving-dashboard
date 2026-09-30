# Forensic methodology

Each test as actually performed. Where a test failed, that is recorded in [experiments.md](experiments.md) rather than dressed up.

## FT-01 Line-count back-solve
**Objective** Establish how many lines a loom ran on a date without trusting the header cell.
**Method** For each candidate count *n* in {2, 4, …, 24}: `rejection_implied = n × line_reading_yards − line_total_yards`. Keep the count that leaves a non-negative whole number of rejected yards (the smallest such). Equivalently `lines = (line total yards + rejection) ÷ line reading yards`.
**Rule** Where it disagrees with the header, the back-solve wins.
**Limits** A day with no meter movement cannot be solved. From June two conventions must both be tried. 105 odd loom counts remain flagged, not altered.

## FT-02 Yellow-row run ownership
**Objective** Recover production the clerk moved out of a loom's normal row on a changeover or reset.
**Method** Walk the dates; a run owns a date when it has a positive reading. Treat `0.0` as **absent**, not as a reading — the regular row holds zero placeholders before the reset, and treating them as real silently inverts the fault.
**Output** Restored machine-days and the old specification (which survives only on the yellow row).
**Limits** Only recoverable where the yellow row survives.

## FT-03 Empty-row formula fault detection
**Objective** Find machine-days the daily tab reports as zero because its formula points at an emptied row.
**Method** Compare the daily tab's computed line value with the cumulative tab's own movement; where the cumulative moved and the daily reads zero, the formula is subtracting blank from blank.
**Output** Every restored machine-day written to the audit log with its yards.

## FT-04 Boundary validation
**Objective** Prove a month's rebuild against the months either side, independently of any total.
**Method** The first day's previous readings must equal the previous month's closing readings, loom by loom; the last day's readings must equal the next month's anchor column.
**Result** April: 51 of 51 against March's close, 55 of 55 against May's anchor (written independently). December → January: 23 of 23.
**Limits** Does not detect an error that cancels out inside the month.

## FT-05 Summary-tab reconciliation
**Objective** Compare the rebuild with the plant's own monthly Summary.
**Method** Day-by-day and month-level comparison, after converting metres to yards (÷ 0.9144) and matching the basis (gross until 17 April, net after).
**Result** February matches on all 24 days; March on 25 of 26; June on 26 of 30; August on 23 of 24 (21 yards on 6.6 M). July's Summary is not reproducible from its own daily tab — it matches on 2 of 30 days.

## FT-06 Unit and basis normalisation
Metres × (1 ÷ 0.9144) → yards for December–March; identify the 17 April switch from gross to net; keep gross and net as separate columns thereafter. Without it the metre months understate production by 8.6 % and every efficiency printed for them is 6–7 points too low.

## FT-07 Rejection tie test
**Objective** Separate rejection that belongs to a production day from rejection that does not.
**Method** An event is *tied* when the same loom has a production row on the same date. Recomputed on every load, not read from the register.
**Result** 225 events / 9,311 yards untied; 214 of them (8,764 yards) fall on three August holidays with no production at all.

## FT-08 Shift-walk reset detection
**Objective** Convert cumulative meter readings into production when counters restart mid-day.
**Method** Walk shift by shift, never day to day. If a shift's closing reading is lower than the shift before it, the counter restarted in that shift and the movement is the new reading itself.
**Why** A day-level subtraction returns −59,000 metres for a loom whose counter restarted inside the day.
**Result** Cross-checked against the daily tab — 987 of 988 machine-days agree to ±1 metre.

## FT-09 Confidence classification
**Objective** Say, on every row, how much of the figure was measured.
**Method** MEASURED = read from the meter in that month's own workbook; DERIVED = produced by a rule; UNVERIFIED = a real gap, with the reason written beside it; NOT APPLICABLE = no reading.
**Result** 26,802 / 1,274 / 939 / 516 rows; 98.2 % of yards measured.

## FT-10 Stopped-loom target rule
**Objective** Stop idle looms booking a target they could never meet.
**Method** A loom whose meter has not moved for 7+ consecutive working days is STOPPED and books no target; idles of 1–6 days stay in the target as real lost availability.
**Result** 1,380 machine-days STOPPED; 5,760,195 yards of target removed; efficiency 62.70 % on that basis (61.99 % after also filling 463 missing targets). **No production figure changes.**
**Sensitivity** 5 days → 63.1 %; 7 → 62.7 %; 10 → 62.0 %; 15 → 61.1 %. Not knife-edge.

## FT-11 Target reachability test
**Method** For every specification × loom-count combination, compare the target with the best day its looms have achieved and with the typical running day.
**Result** 22 specifications REALISTIC, 16 STRETCHED, **0 UNSUPPORTED** — the 18 % target / 82 % availability split.

## FT-12 Loss ladder with a balance check
**Method** Capacity → looms never recorded → loom did not run → lines not deployed → changeover/reset → ran below the rate asked → gross → rejection → net. Each step computed from the fact table; the ladder must balance to 0.00.
**Limit** *A balance check proves internal consistency, not completeness.* The first version balanced to zero while dropping 9,144 yards of rejection on rows with no target. The test that catches this compares the model's gross and rejection with the raw fact table, and is now in the suite.

## FT-13 Multiplier representativeness test
**Method** Compare booked efficiency with the supervisors' own messaging-group reports of how many lines went bad, 8–31 August.
**Result** Median booked efficiency 75 % on days with nothing reported, 70 % with one line bad, 66 % with two, 60 % with three or more — the multiplier is representative on average; it is the individual day it cannot describe.

## FT-14 Metered-line-stopped contradiction
**Method** Find days where the loom is booked at zero but QC rejected cloth from it.
**Result** 289 shift rows / 217 machine-days, 13,237 yards — flagged, never added back.

## FT-15 Data-quality sweep
Across 29,531 rows: 0 duplicate keys, 0 gaps inside a loom's active period, 0 negative yards, 0 absurd readings, 0 specification conflicts within a day, 0 missing QC names, 1 missing supervisor.

## FT-16 Reconciliation against the department
**Method** Three accounting bases held explicitly: target *as recorded* vs *full working calendar*; rejection *tied to a production day* vs *full QC register*; measured-only on or off.
**Result (August)** Dashboard net 6,643,210 · tied rejection 72,248 · holiday rejection 8,764 · register 81,012 · department 90,529 · **residual 9,517 yards, shown on screen and labelled as unexplained.**
