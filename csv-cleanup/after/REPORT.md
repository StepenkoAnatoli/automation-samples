# Supplier price lists: cleanup report

## Result

- Files read: 3 from `before/`
- Rows in (excluding blank rows): 20
- Rows rejected: 4 (listed with reasons in `rejects.csv`)
- Duplicates merged: 5
- **Rows out: 11** (one row per SKU) in `clean.csv` and `clean.xlsx`

## Rows in, per file

| File | Rows | Blank rows skipped |
|---|---:|---:|
| supplier_a.csv | 7 | 2 |
| supplier_b.csv | 7 | 1 |
| supplier_c.xlsx | 6 | 1 |

## Rows rejected, by reason

| Reason | Rows |
|---|---:|
| missing SKU | 1 |
| missing or unreadable price | 1 |
| negative price | 1 |
| unreadable date | 1 |

## Control totals (valid rows only)

Prices are not converted between currencies, so totals are given per currency.

| Currency | Count before | Sum before | Count after | Sum after |
|---|---:|---:|---:|---:|
| ILS | 9 | 2,859.29 | 6 | 1,468.29 |
| USD | 7 | 1,475.70 | 5 | 1,418.20 |
| **All** | 16 | n/a | 11 | n/a |

Check: valid rows before (16) - duplicates merged (5) = rows out (11).

## Duplicates merged

| SKU | Kept (source, date, price) | Dropped (source, date, price) |
|---|---|---|
| AB-100 | supplier_a.csv, 2024-04-10, USD 47.00 | supplier_a.csv, 2024-03-01, USD 45.00 |
| AB-101 | supplier_b.csv, 2024-03-05, ILS 44.90 | supplier_a.csv, 2024-02-15, USD 12.50 |
| AB-106 | supplier_b.csv, 2024-04-02, ILS 12.50 | supplier_b.csv, 2024-04-01, ILS 13.00 |
| AB-105 | supplier_c.xlsx, 2024-04-12, ILS 1,249.00 | supplier_b.csv, 2024-04-02, ILS 1,299.00 |
| AB-111 | supplier_c.xlsx, 2024-02-02, ILS 82.00 | supplier_c.xlsx, 2024-01-20, ILS 79.00 |

## Rules applied

1. Every CSV and Excel file in the folder is read; delimiter and text encoding are detected.
2. Column names are matched however they are written (SKU, `sku `, Item Code, Unit Price ...).
3. SKU is trimmed and upper-cased, so `ab-100 ` and `AB-100` are the same product.
4. Prices accept currency signs and both decimal styles (`$45`, `₪1,299.00`, `12,5`). A price with no sign is assumed to be ILS.
5. Dates in any common layout become `YYYY-MM-DD`; `dd/mm/yyyy` is read day-first.
6. One row per SKU: the row with the most recent date is kept. A row without a date loses to a dated one; on equal dates the row read later wins.
7. Rows are rejected, never guessed, when the SKU is missing, the price is missing, unreadable or negative, or the date is unreadable.
