# Evidence matrix

Confidence: **CONFIRMED** (reproduced from the files by at least two independent routes) · **STRONGLY SUPPORTED** (reproduced once, cross-checked) · **INFERRED** (reasoning from evidence) · **CONFLICTING** (two defensible answers, both kept).

| Claim | Evidence | Confidence |
|---|---|---|
| Jan–Aug gross 43,645,372.91 yd, net 43,166,579.91, target 69,637,909.50, efficiency 61.99 % | Spreadsheet recalculation **and** a PostgreSQL load with 66 checks; both agree | CONFIRMED |
| 29,531 machine-shift rows, 12,655 machine-days, 70 commissioned looms, 215 working days | Row counts in workbook and database | CONFIRMED |
| February's rebuild equals the plant's Summary on all 24 days | Day-by-day comparison; the clerk's daily tab is short by exactly 19,628 m | CONFIRMED |
| April valid at both boundaries (51/51 and 55/55) | Reading-by-reading match; the May anchor written independently | CONFIRMED |
| The file labelled January is December | Its TOTAL tab dates | CONFIRMED |
| 8,764 yd of rejection fall on three August holidays with no production | Tie test | CONFIRMED |
| 9.6 % of Jan–Aug yards measured; 90.4 % multiplied | Metered line movement vs booked yards | CONFIRMED |
| 18 % target / 82 % availability split | Machine-day split across 10,549 available days carrying a target | STRONGLY SUPPORTED |
| August loss ladder: capacity 11,023,392 → net 6,643,210, balancing to 0.00 | Loss model under all 8 basis combinations, plus a test comparing gross and rejection with the raw fact table | CONFIRMED |
| August availability 86.8 %, rate 70.2 %, quality 98.92 %, effectiveness 60.3 % | Derived from the ladder; product equals net ÷ capacity | CONFIRMED |
| 65 % of August's and 73 % of September's lost yards are "ran below rate" | Loss ladder for both periods | CONFIRMED |
| Shifts are level — 1.2 points apart in August | Machine-shift spread; supersedes an earlier "C shift is weak" reading | CONFIRMED |
| Four of six persistent underperformers are S-2 looms | Persistence over 30 weeks | STRONGLY SUPPORTED |
| No target is unreachable | Target review against best and typical achieved days | STRONGLY SUPPORTED |
| 289 shift rows book zero production while QC rejected cloth from that loom | Join of the register to production rows | CONFIRMED |
| QC and production disagree on specification for 3,401 events (167,870 yd) | Row-level comparison | CONFIRMED |
| The messaging group does not explain the lost days | 89 of 90 stoppages on days the loom still produced | CONFIRMED (negative result) |
| Supervisor missing on 73 % of August yards | Issue-impact view | CONFIRMED |
| V1 and V2 differ by 27,044 yd in August, entirely from six looms' line counts; 64 of 70 agree to the yard | Loom-by-loom comparison | CONFIRMED |
| V2 is closer to the department's August figure than V1 (+21,160 vs +48,204 yd) | Both compared with the Summary | CONFIRMED |
| Entry workbook recalculates 445,358 formulas with zero errors and reproduces Sept 1–17 net at 4,024,011 | Spreadsheet recalculation, then a database load | CONFIRMED |
| 96 automated checks pass (66 + 30) | Test runs on a freshly rebuilt database | CONFIRMED |
| Two more operators per shift projects roughly +2.4 points | Regression of efficiency on looms-per-operator; **R² ≈ 0.04** | INFERRED — size of the prize, not a promise |
| Jan–Aug plant efficiency | 56.9–57.9 % in earlier builds (before the stopped-loom rule and target fixes) · 62.70 % after the rule · 61.99 % after filling missing targets — the final workbook's figure | CONFLICTING by basis — always state which |
| August calendar target | 11,023,392 (analytics) vs 10,444,994 (audit) vs 10,310,775 (department) | CONFLICTING — all three printed, residual shown |
| Cost of a changeover | 681,597 yd (gap against target on the event day) vs 476,916 yd (against the loom's own normal, over two days) | Different definitions, not different data |
