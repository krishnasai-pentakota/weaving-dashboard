# Case study — one page

**The plant:** a narrow-fabric weaving department, 70 looms, three shifts. **My role:** the only engineer on the project.

## The problem
Management could not answer *how much was made, against what target, by which loom and shift.* Production lived in hand-kept monthly Excel workbooks, and they disagreed:
- units changed from **metres to yards** in April, unconverted;
- the basis changed from **gross to net** on 17 April;
- editing habits **destroyed evidence** — line counts overwritten, rows copied and cleared;
- a formula fault **silently zeroed real production**;
- the QC register and the production sheet disagreed on **3,401 rejection events**.

## What I did
1. **Started on the floor** — visited every production floor, read the logs and SOPs, talked to the HODs and managers — before opening a spreadsheet.
2. **Audited forensically** — rebuilt each month by back-solving line counts from the sheets' own arithmetic, recovered production the formulas had zeroed, and logged every correction with its yards effect.
3. **Re-modelled** the data to one grain (*loom × day × shift*) with a confidence label on every row.
4. **Built V1** to learn what an MD-level analysis must answer, then **V2** — PostgreSQL, validating ETL, 16 views, 66 tests, an 8-screen dashboard — because V1's analysis couldn't be operated daily.

## What it showed
- The rebuilt record reproduces **43,645,373 yd** (Jan–Aug) exactly; February matches the plant's own summary on **all 24 days**.
- I suspected the targets were unreachable. **They weren't** — **18 %** of the shortfall is target, **82 %** is availability. That finding redirected the project.
- The biggest single loss is looms that **ran, but below the rate asked** — and nothing the plant records explains it.

## What I learned
- **Audit before you build.** The audit cost several times the architecture it enabled — and made that architecture cheap.
- **Correct is not the same as useful.** V2 passed every test and still answered only 2 of the MD's 12 questions.
- **A balance check proves consistency, not completeness.** My first loss ladder balanced to zero while dropping 9,144 yards.
- **Say what the data can't say.** Downtime isn't measurable from a daily meter; the dashboard says so instead of guessing.

*Status: working prototype. The plant, people and customers are anonymised.*
