# Product export: run report

- Run date: 2026-11-08
- Source: https://dummyjson.com/products
- Records fetched: 194 (the API reports 194 in total)
- Pages requested: 7 (30 per page, using limit and skip)
- Retries: 0
- Extra request: 1 (the raw first page, saved unfiltered in `before/first-page.json`)
- Fields exported (9): id, title, brand, category, price, rating, stock, sku, tags
- Rows written to `products.csv`: 194
- Rows skipped: 0
  - none
- Run time: 2.0 seconds

## How it works

1. Pages are requested one after another until every record the API reports has been received.
2. Each request has a timeout. Rate-limit (429), server (5xx) and network failures are retried with
   growing waits; other errors stop the run with a clear message.
3. Only the chosen fields are requested and written. List fields (such as tags) are joined with `|`.
4. The file is UTF-8 with a byte-order mark so Excel shows accents and Hebrew correctly. Values with
   commas, quotes or line breaks are quoted.
5. A record without an id or title, or a repeated id, is skipped and counted above.
