# Automation script samples

Two small, finished examples of the fixed-price automation jobs I deliver to small businesses.
Each one comes with its own before and after files, a test run, and a one-page report, so you can see
exactly what a hand-over looks like.

| Sample | The problem | What you get |
|---|---|---|
| [`csv-cleanup/`](csv-cleanup) | Supplier price lists arrive as different files (CSV, semicolon CSV, Excel) with different headers, currencies and date styles, plus duplicates and bad rows. | One clean price table (CSV and Excel), a list of rejected rows with the reason for each, and a report with control totals. |
| [`api-to-csv/`](api-to-csv) | Product data sits behind a web API, many pages deep, and someone copies it by hand. | A CSV that opens correctly in Excel (accents and Hebrew included) and a report of what was fetched, retried and skipped. |

## What a client receives

For every job:

1. **The script**, which runs on your own computer with no subscription.
2. **A test run**: automated tests that prove each rule works, with the exact command and result.
3. **A one-page report** (`REPORT.md`) written for a business owner: rows in, rows out, what was rejected and why, control totals.
4. **Before and after files**: your real input next to the real output, so you can check the work yourself.

## Run the samples

You need Python 3.10 or newer for the first sample and Node.js 24 for the second.
Commands are shown for Windows (PowerShell); on macOS or Linux replace `.venv\Scripts\python` with `.venv/bin/python`.

### Sample 1: supplier price lists (`csv-cleanup`)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r csv-cleanup/requirements.txt
.venv\Scripts\python csv-cleanup/clean.py --dry-run     # preview only: nothing is written
```

Happy with the preview? Run `.venv\Scripts\python csv-cleanup/clean.py` to write the files into `csv-cleanup/after/`.
Run the tests with `.venv\Scripts\python -m pytest csv-cleanup`.
Read [`csv-cleanup/after/REPORT.md`](csv-cleanup/after/REPORT.md) for the sample report.

### Sample 2: products from an API (`api-to-csv`)

```powershell
cd api-to-csv
node export.mjs --dry-run                  # preview only: one request, nothing is written
node export.mjs                            # the full run: writes after/products.csv and after/REPORT.md
node --test "test/*.test.mjs"              # the tests run offline, no internet needed
```

There are no packages to install. The sample outputs in `api-to-csv/after/` come from a live run on
2026-11-08 against the free public test API at dummyjson.com. Running it again overwrites them with fresh data
(the run date and run time in the report will differ).
Choose columns with `--fields id,title,price`.

## How I work

- **Fixed price, agreed upfront.** We settle scope, inputs and the finished result in writing before I start. No hourly surprises.
- **A dry run or sample output comes first.** Before anything is changed or the full job is run, you see a preview of what would happen. Nothing is written until you approve it.
- **A written report at hand-over.** You get the report, the control totals, the list of anything rejected or skipped, the tests, and the exact commands to run it again.

## License

MIT, see [LICENSE](LICENSE).
