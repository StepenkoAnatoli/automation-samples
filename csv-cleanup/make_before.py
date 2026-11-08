"""Regenerates the three messy supplier files in before/.

The files are committed, so you only need this to see how the mess was built.
Run: python make_before.py
"""
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

BEFORE = Path(__file__).resolve().parent / "before"
BEFORE.mkdir(exist_ok=True)

# Supplier A: UTF-8 with BOM, comma-delimited, "SKU" header, USD prices.
a = (
    "SKU,Product,Price,Updated\n"
    "AB-100,Wireless Mouse,$45,2024-03-01\n"
    "AB-101,USB-C Cable 1m,$12.50,2024-02-15\n"
    " ab-100 ,Wireless Mouse,$47,2024-04-10\n"
    'AB-102,Espresso Machine,"$1,299.00",15/03/2024\n'
    ",,,\n"
    "AB-103,Desk Lamp,-$5.00,2024-03-20\n"
    ",Mystery item,$10,2024-03-01\n"
    "AB-104,Notebook A5,$3.20,5 March 2024\n"
    "\n"
)
(BEFORE / "supplier_a.csv").write_bytes(b"\xef\xbb\xbf" + a.encode("utf-8"))

# Supplier B: Windows-1255 (Hebrew), semicolon-delimited, "sku " header with a
# trailing space, comma decimals, shekel prices.
b = (
    "sku ;Name;Unit Price;Last Updated\n"
    "AB-101 ;כבל USB-C 1 מטר;₪44.90;05.03.2024\n"
    'ab-105;מסך 27 אינץ\';"₪1,299.00";2024-04-02\n'
    'AB-106;מארז סוללות;"12,5";2024/04/02\n'
    "AB-107;כיסוי לטלפון;$45;2 Apr 2024\n"
    ";;;\n"
    "ab-106  ;מארז סוללות;13,0;2024-04-01\n"
    "AB-108;שעון קיר;abc;2024-04-03\n"
    "AB-109;מדפסת;₪ 850;31/02/2024\n"
)
(BEFORE / "supplier_b.csv").write_bytes(b.encode("cp1255"))

# Supplier C: Excel workbook, "Item Code" header, mixed real dates and text dates.
wb = Workbook()
ws = wb.active
ws.title = "Prices"
ws.append(["Item Code", "Description", "Price", "Date"])
ws.append(["AB-110", "Webcam HD", 59.9, datetime(2024, 4, 12)])
ws.append(["ab-105 ", "מסך 27 אינץ'", "₪1,249.00", "12/04/2024"])
ws.append([None, None, None, None])
ws.append(["AB-111", "Headset", 79, datetime(2024, 1, 20)])
ws.append(["ab-111 ", "Headset", 82, "2024-02-02"])
ws.append(["AB-112", "USB Hub", 19.99, None])
ws.append(["AB-103", "Desk Lamp", "$24", "25-03-2024"])
wb.save(BEFORE / "supplier_c.xlsx")
print("written to", BEFORE)
