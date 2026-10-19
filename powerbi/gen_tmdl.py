"""measures.dax + star-schema relationships -> TMDL scripts for Power BI's TMDL view (web or Desktop).

    python3 powerbi/gen_tmdl.py                      -> powerbi/model.tmdl   (relationships + measures)
    python3 powerbi/gen_tmdl.py --full   -> powerbi/model_full.tmdl (whole model as code)

--full defines every table except the seed table (created through Power Query Online) with explicit
column types and an M partition reading the published CSV from GitHub; one data source
(raw.githubusercontent.com, anonymous) via RelativePath, so the service needs a single credential.
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
SORT_BY = {("dim_date", "month_name"): "month_num", ("dim_date", "weekday"): "weekday_num",
           ("fct_orders", "delivery_status"): "delivery_status_sort", ("dim_seller", "seller_tier"): "seller_tier_sort",
           ("dim_customer", "rfm_segment"): "rfm_segment_sort", ("dim_customer", "value_band"): "value_band_sort",
           ("dim_product", "size_band"): "size_band_sort"}
SORT_COLS = {v for v in SORT_BY.values()}
ADDITIVE = {"price", "freight_value", "payment_value", "merchandise_value", "seller_gmv", "lifetime_gmv"}
DATE_COLS = {"date", "month_start", "week_start", "first_order_date", "last_order_date", "cohort_month",
             "first_sale_date"}
SOURCE_BASE = "https://raw.githubusercontent.com"
SOURCE_PATH = "Ajay0704/ecommerce-powerbi/main/data/model"
SEED_TABLE = "fct_payments"  # created through Power Query Online; every other table is defined here


def csv_types(table: str) -> list[tuple[str, str, str]]:
    """-> [(column, TMDL dataType, Power Query type)] read from the published CSV's pandas dtypes."""
    import pandas as pd
    df = pd.read_csv(HERE.parent / "data" / "model" / f"{table}.csv", nrows=5000)
    out = []
    for c, dt in df.dtypes.items():
        if c in DATE_COLS:
            out.append((c, "dateTime", "type date"))
        elif str(dt).startswith("int") or (str(dt).startswith("float") and c in KEYS | {
                "items_count", "sellers_count", "installments", "is_late", "is_same_state", "review_score",
                "customer_order_seq", "months_since_first_order", "promised_days", "days_vs_estimate",
                "weight_g", "volume_cm3", "photos_qty", "description_length"}):
            out.append((c, "int64", "Int64.Type"))
        elif str(dt).startswith("float"):
            out.append((c, "double", "type number"))
        else:
            out.append((c, "string", "type text"))
    return out


def table_tmdl(table: str, measures: list) -> list[str]:
    cols = csv_types(table)
    lines = [f"\ttable {table}"] + (["\t\tdataCategory: Time"] if table == "dim_date" else []) + [""]
    for m in measures:
        lines += measure_tmdl(*m)
    for c, dt, _ in cols:
        lines += [f"\t\tcolumn {c}", f"\t\t\tdataType: {dt}"]
        if table == "dim_date" and c == "date":
            lines.append("\t\t\tisKey")
        fmt = COLUMN_PROPS.get(table, {}).get(c) or ("yyyy-mm-dd" if dt == "dateTime" else None)
        if fmt:
            lines.append(f"\t\t\tformatString: {fmt}")
        if c in KEYS or c in SORT_COLS:
            lines.append("\t\t\tisHidden")
        lines.append(f"\t\t\tsummarizeBy: {'sum' if c in ADDITIVE else 'none'}")
        lines.append(f"\t\t\tsourceColumn: {c}")
        if (table, c) in SORT_BY:
            lines.append(f"\t\t\tsortByColumn: {SORT_BY[(table, c)]}")
        lines.append("")
    pairs = ", ".join(f'{{"{c}", {pq}}}' for c, _, pq in cols)
    lines += [
        f"\t\tpartition {table} = m",
        "\t\t\tmode: import",
        "\t\t\tsource =",
        "\t\t\t\t\tlet",
        f'\t\t\t\t\t\tSource = Csv.Document(Web.Contents("{SOURCE_BASE}", [RelativePath = "{SOURCE_PATH}/{table}.csv"]), '
        '[Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
        "\t\t\t\t\t\tHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
        f'\t\t\t\t\t\tTyped = Table.TransformColumnTypes(Headers, {{{pairs}}}, "en-US")',
        "\t\t\t\t\tin",
        "\t\t\t\t\t\tTyped",
        "",
    ]
    return lines


def main_full() -> None:
    """New tables in full + relationships + measures; the seed table only gets its measures (`ref table`)."""
    measures = parse_measures((HERE / "measures.dax").read_text())
    by_table: dict[str, list] = {}
    for m in measures:
        by_table.setdefault(HOME[m[0]], []).append(m)
    tables = ["dim_date", "dim_customer", "dim_product", "dim_seller", "fct_orders", "fct_order_items"]
    lines = ["createOrReplace", ""]
    for t in tables:
        lines += table_tmdl(t, by_table.get(t, []))
    lines += [f"\tref table {SEED_TABLE}", ""]
    for m in by_table.get(SEED_TABLE, []):
        lines += measure_tmdl(*m)
    for ft, fc, tt, tc in RELATIONSHIPS:
        lines += [f"\trelationship {ft}_{fc}__{tt}", f"\t\tfromColumn: {ft}.{fc}", f"\t\ttoColumn: {tt}.{tc}", ""]
    (HERE / "model_full.tmdl").write_text("\n".join(lines) + "\n")
    print(f"{len(tables)} tables, {len(measures)} measures, {len(RELATIONSHIPS)} relationships -> powerbi/model_full.tmdl")


def main_sort() -> None:
    """Add the *_sort columns to the live model without replacing whole tables: `ref table` + the new column,
    the text column it sorts, and a fresh partition. Full table replaces fail on tables with date columns
    because the service's hidden auto date/time tables hang off them."""
    lines = ["createOrReplace", ""]
    for table in ["fct_orders", "dim_seller", "dim_customer", "dim_product"]:
        block = table_tmdl(table, [])
        wanted = {c for (t_, c), s_ in SORT_BY.items() if t_ == table} | {s_ for (t_, _), s_ in SORT_BY.items() if t_ == table}
        out, keep = [f"\tref table {table}", ""], False
        for line in block[1:]:
            if line.startswith("\t\tcolumn "):
                keep = line.split("column ", 1)[1] in wanted
            elif line.startswith("\t\tpartition "):
                keep = True
            if keep:
                out.append(line)
        lines += out
    (HERE / "model_sort.tmdl").write_text("\n".join(lines) + "\n")
    print("sort columns -> powerbi/model_sort.tmdl")


if __name__ == "__main__":
    main_sort() if "--sort" in sys.argv else main_full() if "--full" in sys.argv else main_model()
