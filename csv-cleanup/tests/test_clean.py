import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

import clean

BEFORE = Path(__file__).resolve().parents[1] / "before"


# ------------------------------------------------------------ normalization rules
@pytest.mark.parametrize("raw,expected", [
    ("SKU", "sku"), ("sku ", "sku"), ("Item Code", "sku"), ("ITEM_CODE", "sku"),
    ("Unit Price", "price"), ("Last Updated", "date"), ("Description", "name"), ("Colour", None),
])
def test_header_aliases(raw, expected):
    assert clean.normalize_header(raw) == expected


def test_sku_trim_case_and_inner_spaces():
    assert clean.normalize_sku("  ab-100 ") == "AB-100"
    assert clean.normalize_sku("ab   100") == "AB 100"
    assert clean.normalize_sku(None) == ""


@pytest.mark.parametrize("raw,price,cur", [
    ("₪1,299.00", "1299.00", "ILS"),
    ("$45", "45", "USD"),
    ("12,5", "12.5", "ILS"),          # bare number -> default currency
    ("1.299,00", "1299.00", "ILS"),   # European style
    ("€ 1.050,50", "1050.50", "EUR"),
    ("1,299", "1299", "ILS"),         # thousands separator
    ("₪ 850", "850", "ILS"),
    ("-$5.00", "-5.00", "USD"),
    ("(12.00)", "-12.00", "ILS"),
    (59.9, "59.9", "ILS"),
    (79, "79", "ILS"),
])
def test_price_formats(raw, price, cur):
    value, currency = clean.parse_price(raw)
    assert value == Decimal(price) and currency == cur


@pytest.mark.parametrize("raw", ["abc", "", None, "N/A", "1,2,3"])
def test_price_unreadable(raw):
    assert clean.parse_price(raw)[0] is None


def test_default_currency_override():
    assert clean.parse_price("10", "USD") == (Decimal("10"), "USD")


@pytest.mark.parametrize("raw", [
    "2024-03-05", "2024/03/05", "05/03/2024", "05.03.2024", "05-03-2024",
    "5 March 2024", "5 Mar 2024", "March 5, 2024", "2024-03-05 10:30:00",
    pd.Timestamp(2024, 3, 5),
])
def test_date_formats(raw):
    assert clean.parse_date(raw) == (date(2024, 3, 5), True)


def test_date_blank_and_bad():
    assert clean.parse_date("") == (None, True)
    assert clean.parse_date(None) == (None, True)
    assert clean.parse_date("31/02/2024") == (None, False)
    assert clean.parse_date("soon") == (None, False)


# ------------------------------------------------------------ reading files
def test_reads_bom_comma_semicolon_cp1255_and_xlsx():
    res = clean.process(BEFORE)
    names = {f["name"] for f in res.files}
    assert names == {"supplier_a.csv", "supplier_b.csv", "supplier_c.xlsx"}
    hebrew = [r for r in res.clean if r["sku"] == "AB-101"][0]
    assert hebrew["name"] == "כבל USB-C 1 מטר"        # cp1255 decoded correctly
    assert hebrew["price"] == Decimal("44.90") and hebrew["currency"] == "ILS"


def write_csv(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_missing_required_column_is_a_clear_error(tmp_path):
    write_csv(tmp_path, "x.csv", "foo,bar\n1,2\n")
    with pytest.raises(ValueError, match="could not find column"):
        clean.process(tmp_path)


# ------------------------------------------------------------ dedup
def test_dedup_keeps_most_recent_regardless_of_order(tmp_path):
    write_csv(tmp_path, "a.csv", "sku,price,date\nX1,10,2024-05-01\nx1 ,20,2024-01-01\n")
    res = clean.process(tmp_path)
    assert [(r["sku"], r["price"]) for r in res.clean] == [("X1", Decimal("10.00"))]
    assert len(res.merged) == 1


def test_dedup_dated_beats_undated_and_ties_go_to_later_row(tmp_path):
    write_csv(tmp_path, "a.csv",
              "sku,price,date\nD,1,2024-01-01\nD,2,\nT,5,2024-02-02\nT,6,2024-02-02\n")
    res = {r["sku"]: r["price"] for r in clean.process(tmp_path).clean}
    assert res == {"D": Decimal("1.00"), "T": Decimal("6.00")}


def test_dedup_across_files_later_date_wins(tmp_path):
    write_csv(tmp_path, "a.csv", "sku,price,date\nK,1,2024-03-01\n")
    write_csv(tmp_path, "b.csv", "sku;price;date\nk;2;2024-02-01\n")
    res = clean.process(tmp_path)
    assert res.clean[0]["source"] == "a.csv"


# ------------------------------------------------------------ rejects
def test_reject_reasons_and_blank_rows(tmp_path):
    write_csv(tmp_path, "a.csv",
              "sku,price,date\n"
              "A,10,2024-01-01\n"
              ",10,2024-01-01\n"
              "B,-1,2024-01-01\n"
              "C,xyz,2024-01-01\n"
              "D,5,not a date\n"
              ",,\n"
              "\n")
    res = clean.process(tmp_path)
    reasons = {r["sku"]: r["reason"] for r in res.rejects}
    assert reasons == {"": clean.REASON_SKU, "B": clean.REASON_NEG, "C": clean.REASON_PRICE, "D": clean.REASON_DATE}
    assert [r["sku"] for r in res.clean] == ["A"]
    assert res.files[0]["blank"] == 2 and res.files[0]["rows_in"] == 5


def test_reject_row_numbers_point_at_the_source_line(tmp_path):
    write_csv(tmp_path, "a.csv", "sku,price\nA,1\n\nB,-4\n")
    assert clean.process(tmp_path).rejects[0]["row"] == 4


def test_committed_sample_rejects():
    res = clean.process(BEFORE)
    assert sorted(r["reason"] for r in res.rejects) == sorted(
        [clean.REASON_SKU, clean.REASON_NEG, clean.REASON_PRICE, clean.REASON_DATE])


# ------------------------------------------------------------ dry run and outputs
def test_dry_run_writes_nothing(tmp_path, capsys):
    out = tmp_path / "out"
    assert clean.main(["--input", str(BEFORE), "--output", str(out), "--dry-run"]) == 0
    assert not out.exists()
    printed = capsys.readouterr().out
    assert "DRY RUN" in printed and "Rows out" in printed


def test_dry_run_summary_equals_report(tmp_path, capsys):
    out = tmp_path / "out"
    clean.main(["--input", str(BEFORE), "--output", str(out), "--dry-run"])
    dry = capsys.readouterr().out
    clean.main(["--input", str(BEFORE), "--output", str(out)])
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    assert report.strip() in dry


def test_real_run_writes_all_four_files(tmp_path):
    out = tmp_path / "out"
    assert clean.main(["--input", str(BEFORE), "--output", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["REPORT.md", "clean.csv", "clean.xlsx", "rejects.csv"]
    assert (out / "clean.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_report_numbers_match_the_data(tmp_path):
    out = tmp_path / "out"
    clean.main(["--input", str(BEFORE), "--output", str(out)])
    report = (out / "REPORT.md").read_text(encoding="utf-8")
    df = pd.read_csv(out / "clean.csv", dtype=str, encoding="utf-8-sig")
    rej = pd.read_csv(out / "rejects.csv", dtype=str, encoding="utf-8-sig")
    xl = pd.read_excel(out / "clean.xlsx")

    assert df.columns.tolist() == clean.OUT_COLUMNS
    assert df["sku"].is_unique and len(df) == len(xl)
    assert f"**Rows out: {len(df)}**" in report
    assert f"- Rows rejected: {len(rej)}" in report
    for reason, n in rej["reason"].value_counts().items():
        assert f"| {reason} | {n} |" in report

    res = clean.process(BEFORE)
    assert f"- Rows in (excluding blank rows): {res.rows_in}" in report
    assert res.rows_in == len(rej) + len(res.valid)
    assert len(res.valid) - len(res.merged) == len(df)
    assert f"- Duplicates merged: {len(res.merged)}" in report

    # control totals after = sums straight from clean.csv, per currency
    for cur, grp in df.groupby("currency"):
        total = sum(Decimal(p) for p in grp["price"])
        assert f"| {cur} | " in report
        assert f"| {len(grp)} | {total:,.2f} |" in report
    # control totals before = valid rows (rows in minus rejects), recomputed independently
    for cur, (n, s) in clean.totals_by_currency(res.valid).items():
        assert re.search(rf"\| {cur} \| {n} \| {re.escape(f'{s:,.2f}')} \|", report)
