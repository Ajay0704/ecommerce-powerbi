"""measures.dax + star-schema relationships -> TMDL scripts for Power BI's TMDL view (web or Desktop).

    python3 powerbi/gen_tmdl.py                      -> powerbi/model.tmdl   (relationships + measures)
    python3 powerbi/gen_tmdl.py --polish types.txt   -> powerbi/polish.tmdl  (column formats, hidden keys, sort-by)

`ref table` leaves each table as Power Query loaded it; only what is listed is added or replaced.
--polish takes the model's CURRENT column types (`table.column=Type;...`, from INFO.VIEW.COLUMNS) and
keeps them, because redefining a column with a different dataType converts stored data and can fail.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).parent

# (from table, column) -> (to table, column); all many-to-one, single direction
RELATIONSHIPS = [
    ("fct_orders", "date_key", "dim_date", "date_key"),
    ("fct_orders", "customer_key", "dim_customer", "customer_key"),
    ("fct_order_items", "order_key", "fct_orders", "order_key"),
    ("fct_order_items", "product_key", "dim_product", "product_key"),
    ("fct_order_items", "seller_key", "dim_seller", "seller_key"),
    ("fct_payments", "order_key", "fct_orders", "order_key"),
]

HOME = {"Sales": "fct_order_items", "Orders": "fct_orders", "Delivery": "fct_orders",
        "Customer Experience": "fct_orders", "Customers": "dim_customer", "Sellers": "dim_seller",
        "Payments": "fct_payments"}

MONEY = r"\R\$ #,0"
MONEY2 = r"\R\$ #,0.00"


def format_string(name: str) -> str | None:
    n = name.lower()
    if "insight" in n:
        return None
    if "%" in n or "rate" in n or "share" in n:
        return "0.0%"
    if n == "reviews":
        return "#,0"
    if "days" in n or "review" in n or "installments" in n or "per order" in n or "penalty" in n:
        return "0.00"
    if "rank" in n:
        return "0"
    if any(k in n for k in ["aov", "avg item price", "avg lifetime", "per seller"]):
        return MONEY2
    if any(k in n for k in ["gmv", "revenue", "value"]):
        return MONEY
    return "#,0"


def parse_measures(text: str) -> list[tuple[str, str, str]]:
    """-> [(folder, name, expression)]; a measure starts after a blank/comment line with `Name =`."""
    out, folder, cur, prev_sep = [], None, None, True
    for raw in text.splitlines() + [""]:
        header = re.match(r"^// -+ (.+?) -+\s*$", raw)
        if header:
            folder = header.group(1)
        starts = re.match(r"^([A-Za-z0-9][^=/]*?) =(.*)$", raw)
        is_start = bool(starts) and prev_sep and not re.match(r"^(VAR|RETURN)\b", raw)
        prev_sep = raw.strip() == "" or raw.startswith("//")
        if is_start:
            if cur:
                out.append(cur)
            cur = (folder, starts.group(1).strip(), [starts.group(2).strip()] if starts.group(2).strip() else [])
            continue
        if cur and (raw.strip() == "" or raw.startswith("//")):
            out.append(cur)
            cur = None
            continue
        if cur:
            cur[2].append(raw.rstrip())
    return [(f, n, "\n".join(e).strip()) for f, n, e in out]


def measure_tmdl(folder: str, name: str, expr: str) -> list[str]:
    lines = expr.splitlines()
    if len(lines) == 1:
        out = [f"\t\tmeasure '{name}' = {lines[0]}"]
    else:  # ``` fences mark exactly where a multi-line expression ends
        out = [f"\t\tmeasure '{name}' = ```"] + [f"\t\t\t\t{l}" for l in lines if l.strip()] + ["\t\t\t\t```"]
    fmt = format_string(name)
    return out + ([f"\t\t\tformatString: {fmt}"] if fmt else []) + [f"\t\t\tdisplayFolder: {folder}", ""]


def main_model() -> None:
    measures = parse_measures((HERE / "measures.dax").read_text())
    lines = ["createOrReplace", ""]
    for ft, fc, tt, tc in RELATIONSHIPS:
        lines += [f"\trelationship {ft}_{fc}__{tt}", f"\t\tfromColumn: {ft}.{fc}", f"\t\ttoColumn: {tt}.{tc}", ""]
    by_table: dict[str, list] = {}
    for m in measures:
        by_table.setdefault(HOME[m[0]], []).append(m)
    for table, items in by_table.items():
        lines += [f"\tref table {table}", ""]
        for m in items:
            lines += measure_tmdl(*m)
    (HERE / "model.tmdl").write_text("\n".join(lines) + "\n")
    print(f"{len(RELATIONSHIPS)} relationships, {len(measures)} measures -> powerbi/model.tmdl")


# report-facing column properties: (format, summarizeBy, sortByColumn, hidden)
KEYS = {"order_key", "customer_key", "product_key", "seller_key", "date_key", "order_line_key", "order_item_id",
        "payment_sequential"}
COLUMN_PROPS = {
    "fct_order_items": {"price": MONEY2, "freight_value": MONEY2},
    "fct_orders": {"merchandise_value": MONEY2, "freight_value": MONEY2, "payment_value": MONEY2,
                   "delivery_days": "0.0", "approval_hours": "0.0", "seller_to_carrier_days": "0.0",
                   "carrier_to_customer_days": "0.0"},
    "fct_payments": {"payment_value": MONEY2},
    "dim_customer": {"lifetime_gmv": MONEY2, "cohort_month": "yyyy-mm", "first_order_date": "yyyy-mm-dd",
                     "last_order_date": "yyyy-mm-dd"},
    "dim_seller": {"seller_gmv": MONEY, "first_sale_date": "yyyy-mm-dd"},
    "dim_date": {"date": "yyyy-mm-dd", "month_start": "mmm yyyy", "week_start": "yyyy-mm-dd"},
}
SORT_BY = {("dim_date", "month_name"): "month_num", ("dim_date", "weekday"): "weekday_num"}
ADDITIVE = {"price", "freight_value", "payment_value", "merchandise_value", "seller_gmv", "lifetime_gmv"}
MODEL_TYPE = {"Text": "string", "Integer": "int64", "Number": "double", "Decimal": "decimal",
              "Date": "dateTime", "DateTime": "dateTime", "True/False": "boolean"}


def main_polish(types_file: str) -> None:
    current: dict[str, dict[str, str]] = {}
    for item in Path(types_file).read_text().strip().split(";"):
        k, v = item.split("=")
        t, c = k.split(".", 1)
        current.setdefault(t, {})[c] = MODEL_TYPE[v]
    lines = ["createOrReplace", ""]
    n = 0
    for table, cols in current.items():
        block = []
        for c, dt in cols.items():
            fmt = COLUMN_PROPS.get(table, {}).get(c)
            hidden = c in KEYS
            sort = SORT_BY.get((table, c))
            numeric = dt in ("int64", "double", "decimal")
            if not (fmt or hidden or sort or numeric):
                continue
            # dates stay untouched: redefining them orphans the hidden auto date/time tables
            if dt == "dateTime" and table != "dim_date":
                continue
            block += [f"\t\tcolumn {c}", f"\t\t\tdataType: {dt}"]
            if fmt:
                block.append(f"\t\t\tformatString: {fmt}")
            if hidden:
                block.append("\t\t\tisHidden")
            block.append(f"\t\t\tsummarizeBy: {'sum' if c in ADDITIVE else 'none'}")
            block.append(f"\t\t\tsourceColumn: {c}")
            if sort:
                block.append(f"\t\t\tsortByColumn: {sort}")
            block.append("")
            n += 1
        if block:
            lines += [f"\tref table {table}", ""] + block
    (HERE / "polish.tmdl").write_text("\n".join(lines) + "\n")
    print(f"{n} columns -> powerbi/polish.tmdl")


if __name__ == "__main__":
    if "--polish" in sys.argv:
        main_polish(sys.argv[sys.argv.index("--polish") + 1])
    else:
        main_model()
