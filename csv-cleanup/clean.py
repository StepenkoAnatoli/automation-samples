#!/usr/bin/env python3
"""Merge messy supplier price lists into one clean table.

Usage:
    python clean.py --dry-run          # show the summary, write nothing
    python clean.py                    # write after/clean.csv, clean.xlsx, rejects.csv, REPORT.md

Rules (also printed in REPORT.md):
  * Files read: every .csv / .xlsx in the input folder, in alphabetical order.
  * CSV encoding: UTF-8 (with or without BOM), otherwise Windows-1255. Delimiter is detected.
  * Headers are matched ignoring case, spaces and punctuation (SKU, "sku ", Item Code ...).
  * SKU: trimmed, inner spaces collapsed, upper-cased.
  * Price: currency symbols/words removed, "1,299.00", "1.299,00" and "12,5" understood.
  * Date: day-first for dd/mm/yyyy; ISO, "5 March 2024" and similar also accepted. Output ISO.
  * Duplicates: one row per SKU. The row with the most recent date wins; a row with no date
    loses to a dated row; on equal dates the row read later wins (later file, then lower in file).
  * Rejected (not in the output, listed in rejects.csv): missing SKU, missing/unreadable price,
    negative price, unreadable date. Blank rows are skipped and counted separately.
  * No currency conversion: each price keeps its currency.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT_COLUMNS = ["sku", "name", "price", "currency", "date", "source"]

HEADER_ALIASES = {
    "sku": {"sku", "itemcode", "item", "code", "productcode", "partnumber"},
    "name": {"name", "product", "productname", "description", "itemname", "title"},
    "price": {"price", "unitprice", "cost", "amount"},
    "date": {"date", "updated", "lastupdated", "pricedate", "updatedat"},
    "currency": {"currency", "curr"},
}

CURRENCY_MARKERS = [  # (marker found in raw text, ISO code)
    ("₪", "ILS"), ("NIS", "ILS"), ("ILS", "ILS"),
    ("$", "USD"), ("USD", "USD"),
    ("€", "EUR"), ("EUR", "EUR"),
]

DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y",
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
]

REASON_SKU = "missing SKU"
REASON_PRICE = "missing or unreadable price"
REASON_NEG = "negative price"
REASON_DATE = "unreadable date"
REASONS = [REASON_SKU, REASON_PRICE, REASON_NEG, REASON_DATE]


# ----------------------------------------------------------------- normalization rules
def normalize_header(h: object) -> str | None:
    key = re.sub(r"[^a-z0-9]", "", str(h).lower())
    for field_name, aliases in HEADER_ALIASES.items():
        if key in aliases:
            return field_name
    return None


def normalize_sku(raw: object) -> str:
    return re.sub(r"\s+", " ", str(raw or "")).strip().upper()


def parse_price(raw: object, default_currency: str = "ILS") -> tuple[Decimal | None, str]:
    """Return (price, currency). price is None when empty or unreadable."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None, default_currency
    if isinstance(raw, (int, float, Decimal)) and not isinstance(raw, bool):
        return Decimal(str(raw)), default_currency
    text = str(raw).strip()
    if not text:
        return None, default_currency
    currency = default_currency
    upper = text.upper()
    for marker, code in CURRENCY_MARKERS:
        if marker in upper:
            currency = code
            break
    negative = text.startswith("(") and text.endswith(")") or "-" in text
    digits = re.sub(r"[^0-9.,]", "", text)
    if not re.search(r"\d", digits):
        return None, currency
    digits = digits.strip(".,")
    if "," in digits and "." in digits:
        if digits.rfind(",") > digits.rfind("."):          # 1.299,00
            digits = digits.replace(".", "").replace(",", ".")
        else:                                              # 1,299.00
            digits = digits.replace(",", "")
    elif "," in digits:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", digits):      # 1,299  -> thousands
            digits = digits.replace(",", "")
        elif digits.count(",") == 1:                       # 12,5   -> decimal
            digits = digits.replace(",", ".")
        else:
            return None, currency
    elif digits.count(".") > 1:
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", digits):     # 1.299.000
            digits = digits.replace(".", "")
        else:
            return None, currency
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None, currency
    return (-value if negative else value), currency


def parse_date(raw: object) -> tuple[date | None, bool]:
    """Return (date, ok). Blank gives (None, True); unreadable gives (None, False)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None, True
    if isinstance(raw, (datetime, pd.Timestamp)):
        return raw.date(), True
    if isinstance(raw, date):
        return raw, True
    text = str(raw).strip()
    if not text:
        return None, True
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date(), True
        except ValueError:
            continue
    return None, False


# ----------------------------------------------------------------- reading
def read_csv_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp1255"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("cp1255", errors="replace")


def read_table(path: Path) -> list[dict[str, str]]:
    """Return rows as dicts keyed by canonical field name, plus '_row' (1-based sheet row)."""
    if path.suffix.lower() == ".xlsx":
        df = pd.read_excel(path, dtype=object, header=0, engine="openpyxl")
        headers = list(df.columns)
        raw_rows = df.values.tolist()
    else:
        text = read_csv_text(path)
        sample = text[:4096]
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delim = ","
        parsed = list(csv.reader(text.splitlines(), delimiter=delim))
        if not parsed:
            return []
        headers, raw_rows = parsed[0], parsed[1:]
    mapping = {i: normalize_header(h) for i, h in enumerate(headers)}
    missing = {"sku", "price"} - set(mapping.values())
    if missing:
        raise ValueError(f"{path.name}: could not find column(s) {sorted(missing)} in headers {list(headers)}")
    rows = []
    for n, raw in enumerate(raw_rows, start=2):
        row: dict = {"_row": n}
        for i, value in enumerate(raw):
            name = mapping.get(i)
            if name and name not in row:
                row[name] = value
        rows.append(row)
    return rows


def is_blank(row: dict) -> bool:
    for k, v in row.items():
        if k == "_row":
            continue
        if v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip():
            return False
    return True


# ----------------------------------------------------------------- pipeline
@dataclass
class Result:
    files: list[dict] = field(default_factory=list)       # name, rows_in, blank
    valid: list[dict] = field(default_factory=list)       # before dedup
    clean: list[dict] = field(default_factory=list)       # after dedup
    rejects: list[dict] = field(default_factory=list)
    merged: list[dict] = field(default_factory=list)      # one entry per dropped duplicate
    default_currency: str = "ILS"

    @property
    def rows_in(self) -> int:
        return sum(f["rows_in"] for f in self.files)


def process(input_dir: Path, default_currency: str = "ILS") -> Result:
    res = Result(default_currency=default_currency)
    paths = sorted(p for p in input_dir.iterdir()
                   if p.suffix.lower() in (".csv", ".xlsx") and not p.name.startswith(("~", ".")))
    order = 0
    for path in paths:
        rows = read_table(path)
        info = {"name": path.name, "rows_in": 0, "blank": 0}
        for row in rows:
            if is_blank(row):
                info["blank"] += 1
                continue
            info["rows_in"] += 1
            order += 1
            sku = normalize_sku(row.get("sku"))
            raw_price = row.get("price")
            raw_date = row.get("date")
            price, currency = parse_price(raw_price, default_currency)
            if row.get("currency") and str(row["currency"]).strip():
                currency = str(row["currency"]).strip().upper()
            d, date_ok = parse_date(raw_date)
            reason = None
            if not sku:
                reason = REASON_SKU
            elif price is None:
                reason = REASON_PRICE
            elif price < 0:
                reason = REASON_NEG
            elif not date_ok:
                reason = REASON_DATE
            if reason:
                res.rejects.append({
                    "source": path.name, "row": row["_row"], "sku": str(row.get("sku") or "").strip(),
                    "raw_price": "" if raw_price is None or (isinstance(raw_price, float) and pd.isna(raw_price)) else raw_price,
                    "raw_date": "" if raw_date is None or (isinstance(raw_date, float) and pd.isna(raw_date)) else raw_date,
                    "reason": reason,
                })
                continue
            name = row.get("name")
            name = "" if name is None or (isinstance(name, float) and pd.isna(name)) else re.sub(r"\s+", " ", str(name)).strip()
            res.valid.append({
                "sku": sku, "name": name, "price": price.quantize(Decimal("0.01")), "currency": currency,
                "date": d, "source": path.name, "_row": row["_row"], "_order": order,
            })
        res.files.append(info)

    best: dict[str, dict] = {}
    for r in res.valid:
        key = (r["date"] or date.min, r["_order"])
        cur = best.get(r["sku"])
        if cur is None:
            best[r["sku"]] = r
            continue
        cur_key = (cur["date"] or date.min, cur["_order"])
        winner, loser = (r, cur) if key > cur_key else (cur, r)
        best[r["sku"]] = winner
        res.merged.append({"sku": r["sku"], "kept": winner, "dropped": loser})
    res.clean = sorted(best.values(), key=lambda r: r["sku"])
    return res


# ----------------------------------------------------------------- report
def totals_by_currency(rows: list[dict]) -> dict[str, tuple[int, Decimal]]:
    out: dict[str, tuple[int, Decimal]] = {}
    for r in rows:
        n, s = out.get(r["currency"], (0, Decimal("0")))
        out[r["currency"]] = (n + 1, s + r["price"])
    return out


def fmt_money(x: Decimal) -> str:
    return f"{x:,.2f}"


def render_report(res: Result, input_label: str = "before/") -> str:
    before, after = totals_by_currency(res.valid), totals_by_currency(res.clean)
    reason_counts = {r: sum(1 for x in res.rejects if x["reason"] == r) for r in REASONS}
    L = ["# Supplier price lists: cleanup report", ""]
    L += ["## Result", "",
          f"- Files read: {len(res.files)} from `{input_label}`",
          f"- Rows in (excluding blank rows): {res.rows_in}",
          f"- Rows rejected: {len(res.rejects)} (listed with reasons in `rejects.csv`)",
          f"- Duplicates merged: {len(res.merged)}",
          f"- **Rows out: {len(res.clean)}** (one row per SKU) in `clean.csv` and `clean.xlsx`",
          "", "## Rows in, per file", "", "| File | Rows | Blank rows skipped |", "|---|---:|---:|"]
    for f in res.files:
        L.append(f"| {f['name']} | {f['rows_in']} | {f['blank']} |")
    L += ["", "## Rows rejected, by reason", "", "| Reason | Rows |", "|---|---:|"]
    for r in REASONS:
        L.append(f"| {r} | {reason_counts[r]} |")
    L += ["", "## Control totals (valid rows only)", "",
          "Prices are not converted between currencies, so totals are given per currency.", "",
          "| Currency | Count before | Sum before | Count after | Sum after |", "|---|---:|---:|---:|---:|"]
    for cur in sorted(set(before) | set(after)):
        bn, bs = before.get(cur, (0, Decimal("0")))
        an, a_s = after.get(cur, (0, Decimal("0")))
        L.append(f"| {cur} | {bn} | {fmt_money(bs)} | {an} | {fmt_money(a_s)} |")
    L.append(f"| **All** | {len(res.valid)} | n/a | {len(res.clean)} | n/a |")
    L += ["", "Check: valid rows before "
          f"({len(res.valid)}) - duplicates merged ({len(res.merged)}) = rows out ({len(res.clean)}).", ""]
    if res.merged:
        L += ["## Duplicates merged", "", "| SKU | Kept (source, date, price) | Dropped (source, date, price) |", "|---|---|---|"]
        for m in res.merged:
            k, d = m["kept"], m["dropped"]
            L.append(f"| {m['sku']} | {k['source']}, {k['date'] or 'no date'}, {k['currency']} {fmt_money(k['price'])} "
                     f"| {d['source']}, {d['date'] or 'no date'}, {d['currency']} {fmt_money(d['price'])} |")
        L.append("")
    L += ["## Rules applied", "",
          "1. Every CSV and Excel file in the folder is read; delimiter and text encoding are detected.",
          "2. Column names are matched however they are written (SKU, `sku `, Item Code, Unit Price ...).",
          "3. SKU is trimmed and upper-cased, so `ab-100 ` and `AB-100` are the same product.",
          "4. Prices accept currency signs and both decimal styles (`$45`, `₪1,299.00`, `12,5`). "
          f"A price with no sign is assumed to be {res.default_currency}.",
          "5. Dates in any common layout become `YYYY-MM-DD`; `dd/mm/yyyy` is read day-first.",
          "6. One row per SKU: the row with the most recent date is kept. A row without a date loses to a dated one; "
          "on equal dates the row read later wins.",
          "7. Rows are rejected, never guessed, when the SKU is missing, the price is missing, unreadable or negative, "
          "or the date is unreadable.",
          ""]
    return "\n".join(L)


# ----------------------------------------------------------------- output
def clean_records(res: Result) -> list[dict]:
    return [{"sku": r["sku"], "name": r["name"], "price": f"{r['price']:.2f}", "currency": r["currency"],
             "date": r["date"].isoformat() if r["date"] else "", "source": r["source"]} for r in res.clean]


def write_outputs(res: Result, out_dir: Path, report: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(clean_records(res), columns=OUT_COLUMNS)
    df.to_csv(out_dir / "clean.csv", index=False, encoding="utf-8-sig", lineterminator="\n")   # BOM so Excel reads Hebrew
    xl = df.copy()
    xl["price"] = xl["price"].astype(float)
    xl.to_excel(out_dir / "clean.xlsx", index=False, sheet_name="Clean", engine="openpyxl")
    rej = pd.DataFrame(res.rejects, columns=["source", "row", "sku", "raw_price", "raw_date", "reason"])
    rej.to_csv(out_dir / "rejects.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    (out_dir / "REPORT.md").write_text(report, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Merge and clean supplier price lists.")
    ap.add_argument("--input", type=Path, default=HERE / "before", help="folder with the supplier files")
    ap.add_argument("--output", type=Path, default=HERE / "after", help="folder for the results")
    ap.add_argument("--dry-run", action="store_true", help="print the summary and write nothing")
    ap.add_argument("--default-currency", default="ILS", help="currency for prices written without a sign (default ILS)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        res = process(args.input, args.default_currency)
    except (ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    report = render_report(res, f"{args.input.name}/")
    print(report)
    if args.dry_run:
        print("DRY RUN: nothing was written. Run again without --dry-run to create the files.")
        return 0
    write_outputs(res, args.output, report)
    print(f"Written to {args.output}: clean.csv, clean.xlsx, rejects.csv, REPORT.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
