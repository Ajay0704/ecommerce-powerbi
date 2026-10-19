"""Olist raw CSVs -> Power BI star schema (CSV per table + one xlsx for Power BI web).

    python3 pipeline/build_model.py

Analysis window: purchases 2017-01-01 .. 2018-08-31 (20 full months). 2016 has ~330 test-era
orders and Sep/Oct 2018 has 20, almost all cancelled, so both ends would distort every trend.

Tables
    fct_orders        one row per order (order header: status, delivery, review, payment, customer)
    fct_order_items   one row per order line, non-cancelled orders only (GMV lives here)
    fct_payments      one row per payment record (an order can be split across vouchers/cards)
    dim_customer      one row per real person (customer_unique_id), with cohort + RFM segment
    dim_product       category (English) + category group + size band
    dim_seller        location + GMV tier
    dim_date          calendar, marked as the date table in the model
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "model"
START, END = pd.Timestamp("2017-01-01"), pd.Timestamp("2018-08-31 23:59:59")
SNAPSHOT = pd.Timestamp("2018-09-01")  # RFM "as of" date: the day after the window closes

STATE = {  # code -> (name, region)
    "AC": ("Acre", "North"), "AL": ("Alagoas", "Northeast"), "AM": ("Amazonas", "North"), "AP": ("Amapá", "North"),
    "BA": ("Bahia", "Northeast"), "CE": ("Ceará", "Northeast"), "DF": ("Distrito Federal", "Central-West"),
    "ES": ("Espírito Santo", "Southeast"), "GO": ("Goiás", "Central-West"), "MA": ("Maranhão", "Northeast"),
    "MG": ("Minas Gerais", "Southeast"), "MS": ("Mato Grosso do Sul", "Central-West"),
    "MT": ("Mato Grosso", "Central-West"), "PA": ("Pará", "North"), "PB": ("Paraíba", "Northeast"),
    "PE": ("Pernambuco", "Northeast"), "PI": ("Piauí", "Northeast"), "PR": ("Paraná", "South"),
    "RJ": ("Rio de Janeiro", "Southeast"), "RN": ("Rio Grande do Norte", "Northeast"),
    "RO": ("Rondônia", "North"), "RR": ("Roraima", "North"), "RS": ("Rio Grande do Sul", "South"),
    "SC": ("Santa Catarina", "South"), "SE": ("Sergipe", "Northeast"), "SP": ("São Paulo", "Southeast"),
    "TO": ("Tocantins", "North"),
}

# English category -> merchandising group (my own grouping, for a 2-level category drill)
GROUPS = {
    "Home & Furniture": ["bed_bath_table", "furniture_decor", "housewares", "furniture_living_room", "furniture_bedroom",
                         "furniture_mattress_and_upholstery", "office_furniture", "home_confort", "home_comfort_2",
                         "kitchen_dining_laundry_garden_furniture", "la_cuisine", "christmas_supplies", "flowers",
                         "party_supplies"],
    "Appliances": ["home_appliances", "home_appliances_2", "small_appliances", "small_appliances_home_oven_and_coffee",
                   "air_conditioning", "portable_kitchen_food_preparers"],
    "Electronics & Tech": ["computers_accessories", "computers", "electronics", "telephony", "fixed_telephony",
                           "tablets_printing_image", "consoles_games", "audio", "cine_photo", "pc_gamer"],
    "Health & Beauty": ["health_beauty", "perfumery", "diapers_and_hygiene"],
    "Fashion & Accessories": ["watches_gifts", "fashion_bags_accessories", "fashion_shoes", "fashion_male_clothing",
                              "fashio_female_clothing", "fashion_underwear_beach", "fashion_sport",
                              "fashion_childrens_clothes", "luggage_accessories"],
    "Sports & Leisure": ["sports_leisure", "cool_stuff", "musical_instruments", "art", "arts_and_craftmanship"],
    "Baby, Kids & Toys": ["toys", "baby"],
    "Tools, Garden & Auto": ["auto", "garden_tools", "costruction_tools_garden", "costruction_tools_tools",
                             "construction_tools_construction", "construction_tools_lights",
                             "construction_tools_safety", "home_construction", "signaling_and_security",
                             "security_and_services", "agro_industry_and_commerce", "industry_commerce_and_business"],
    "Books, Media & Office": ["books_general_interest", "books_technical", "books_imported", "cds_dvds_musicals",
                              "dvds_blu_ray", "music", "stationery"],
    "Food, Drink & Pets": ["food", "food_drink", "drinks", "pet_shop", "market_place"],
}
GROUP_OF = {c: g for g, cats in GROUPS.items() for c in cats}
# the two Portuguese categories missing from Olist's translation file
EXTRA_TRANSLATION = {"portateis_cozinha_e_preparadores_de_alimentos": "portable_kitchen_food_preparers",
                     "pc_gamer": "pc_gamer"}


def read(name: str, **kw) -> pd.DataFrame:
    return pd.read_csv(RAW / f"olist_{name}_dataset.csv", **kw)


def nice(cat: str) -> str:
    fixes = {"fashio": "fashion", "costruction": "construction", "confort": "comfort", "craftmanship": "craftsmanship"}
    words = [fixes.get(w, w) for w in cat.split("_")]
    return " ".join(words).capitalize().replace(" 2", " (2)")


def date_key(s: pd.Series) -> pd.Series:
    return (s.dt.year * 10000 + s.dt.month * 100 + s.dt.day).astype("Int64")


def build() -> dict[str, pd.DataFrame]:
    ts = ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
          "order_delivered_customer_date", "order_estimated_delivery_date"]
    orders = read("orders", parse_dates=ts)
    orders = orders[orders.order_purchase_timestamp.between(START, END)].copy()
    customers = read("customers")
    items = read("order_items")
    payments = read("order_payments")
    reviews = read("order_reviews", parse_dates=["review_creation_date"])
    products = read("products")
    sellers = read("sellers")
    trans = pd.read_csv(RAW / "product_category_name_translation.csv", encoding="utf-8-sig")
    trans = dict(zip(trans.product_category_name, trans.product_category_name_english)) | EXTRA_TRANSLATION

    # ---------- order header ----------
    o = orders.merge(customers, on="customer_id", how="left")
    o["is_canceled"] = o.order_status.isin(["canceled", "unavailable"]).astype(int)
    o["is_delivered"] = ((o.order_status == "delivered") & o.order_delivered_customer_date.notna()).astype(int)
    day = 86400.0
    o["delivery_days"] = (o.order_delivered_customer_date - o.order_purchase_timestamp).dt.total_seconds() / day
    o["promised_days"] = (o.order_estimated_delivery_date - o.order_purchase_timestamp.dt.normalize()).dt.days
    # estimated date carries no time, so compare calendar dates: late = delivered on a later day than promised
    o["days_vs_estimate"] = (o.order_delivered_customer_date.dt.normalize() - o.order_estimated_delivery_date).dt.days
    o.loc[o.is_delivered == 0, ["delivery_days", "days_vs_estimate"]] = np.nan
    o["is_late"] = np.where(o.is_delivered == 1, (o.days_vs_estimate > 0).astype(int), np.nan)
    o["delivery_status"] = np.select(
        [o.is_delivered == 0, o.days_vs_estimate <= 0, o.days_vs_estimate <= 3, o.days_vs_estimate <= 7],
        ["Not delivered", "On time", "1-3 days late", "4-7 days late"], "8+ days late")
    o["delivery_status_sort"] = o.delivery_status.map(
        {"On time": 1, "1-3 days late": 2, "4-7 days late": 3, "8+ days late": 4, "Not delivered": 5})
    o["approval_hours"] = (o.order_approved_at - o.order_purchase_timestamp).dt.total_seconds() / 3600
    o["seller_to_carrier_days"] = (o.order_delivered_carrier_date - o.order_approved_at).dt.total_seconds() / day
    o["carrier_to_customer_days"] = (o.order_delivered_customer_date - o.order_delivered_carrier_date).dt.total_seconds() / day
    for c in ["approval_hours", "seller_to_carrier_days", "carrier_to_customer_days"]:
        o.loc[o[c] < 0, c] = np.nan  # rows where the carrier scan precedes approval: data errors

    # items roll-up (all orders, for the header); seller state = the seller with the most item value
    it = items[items.order_id.isin(o.order_id)].merge(sellers[["seller_id", "seller_state"]], on="seller_id", how="left")
    roll = it.groupby("order_id").agg(items_count=("order_item_id", "size"), sellers_count=("seller_id", "nunique"),
                                      merchandise_value=("price", "sum"), freight_value=("freight_value", "sum"))
    main_seller = (it.groupby(["order_id", "seller_state"]).price.sum().reset_index()
                   .sort_values("price", ascending=False).drop_duplicates("order_id").set_index("order_id").seller_state)
    o = o.join(roll, on="order_id").join(main_seller.rename("seller_state"), on="order_id")
    o["is_same_state"] = np.where(o.seller_state.notna(), (o.seller_state == o.customer_state).astype(int), np.nan)

    # payments roll-up: primary method = largest payment value
    pay = payments[payments.order_id.isin(o.order_id)]
    proll = pay.groupby("order_id").agg(payment_value=("payment_value", "sum"),
                                        installments=("payment_installments", "max"))
    ptype = pay.sort_values("payment_value", ascending=False).drop_duplicates("order_id").set_index("order_id").payment_type
    o = o.join(proll, on="order_id").join(ptype.rename("payment_type"), on="order_id")

    # reviews: some orders were reviewed more than once; keep the latest review
    rv = reviews.sort_values("review_creation_date").drop_duplicates("order_id", keep="last").set_index("order_id")
    o = o.join(rv.review_score, on="order_id")
    o["has_review_comment"] = o.order_id.isin(rv.index[rv.review_comment_message.notna()]).astype(int)

    # customer sequence (non-cancelled orders define first purchase / cohort)
    o = o.sort_values("order_purchase_timestamp")
    valid = o[o.is_canceled == 0]
    seq = valid.groupby("customer_unique_id").cumcount() + 1
    o["customer_order_seq"] = seq.reindex(o.index).astype("Int64")
    first = valid.groupby("customer_unique_id").order_purchase_timestamp.min()
    o["is_first_order"] = (o.customer_order_seq == 1).fillna(False).astype(int)
    fm = o.customer_unique_id.map(first)
    o["months_since_first_order"] = ((o.order_purchase_timestamp.dt.year - fm.dt.year) * 12
                                     + o.order_purchase_timestamp.dt.month - fm.dt.month).astype("Int64")
    o.loc[o.is_canceled == 1, "months_since_first_order"] = pd.NA
    o["date_key"] = date_key(o.order_purchase_timestamp)
    o["purchase_hour"] = o.order_purchase_timestamp.dt.hour
    o["payment_type"] = o.payment_type.fillna("unknown").str.replace("_", " ").str.title()

    fct_orders = o[["order_id", "customer_unique_id", "date_key", "order_status", "is_canceled", "is_delivered",
                    "items_count", "sellers_count", "merchandise_value", "freight_value", "payment_value",
                    "payment_type", "installments", "purchase_hour", "approval_hours", "seller_to_carrier_days",
                    "carrier_to_customer_days", "delivery_days", "promised_days", "days_vs_estimate", "is_late",
                    "delivery_status", "delivery_status_sort", "customer_state", "seller_state", "is_same_state", "review_score",
                    "has_review_comment", "customer_order_seq", "is_first_order", "months_since_first_order"]].copy()
    fct_orders["order_status"] = fct_orders.order_status.str.title()

    # ---------- order lines (non-cancelled orders only) ----------
    keep = o.loc[o.is_canceled == 0, ["order_id"]]
    fct_items = items.merge(keep, on="order_id")[["order_id", "order_item_id", "product_id", "seller_id",
                                                  "price", "freight_value"]]
    fct_items.insert(0, "order_line_id", fct_items.order_id + "-" + fct_items.order_item_id.astype(str))

    # ---------- payments ----------
    fct_payments = pay[["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"]].copy()
    fct_payments = fct_payments[fct_payments.payment_type != "not_defined"]
    fct_payments["payment_type"] = fct_payments.payment_type.str.replace("_", " ").str.title()
    fct_payments.insert(0, "payment_id", fct_payments.order_id + "-" + fct_payments.payment_sequential.astype(str))

    # ---------- dim_customer ----------
    gmv_by_order = fct_items.groupby("order_id").price.sum()
    v = valid.assign(gmv=valid.order_id.map(gmv_by_order).fillna(0))
    c = v.groupby("customer_unique_id").agg(customer_state=("customer_state", "last"),
                                            customer_city=("customer_city", "last"),
                                            first_order_date=("order_purchase_timestamp", "min"),
                                            last_order_date=("order_purchase_timestamp", "max"),
                                            total_orders=("order_id", "size"), lifetime_gmv=("gmv", "sum"))
    c["state_name"] = c.customer_state.map(lambda s: STATE[s][0])
    c["region"] = c.customer_state.map(lambda s: STATE[s][1])
    c["customer_city"] = c.customer_city.str.title()
    c["cohort_month"] = c.first_order_date.dt.to_period("M").dt.to_timestamp()
    c["first_order_date"] = c.first_order_date.dt.normalize()
    c["last_order_date"] = c.last_order_date.dt.normalize()
    c["is_repeat_customer"] = (c.total_orders >= 2).astype(int)
    c["recency_days"] = (SNAPSHOT - c.last_order_date).dt.days
    hi_value = c.lifetime_gmv.quantile(0.75)
    c["rfm_segment"] = np.select(
        [(c.total_orders >= 2) & (c.recency_days <= 180), c.total_orders >= 2,
         c.recency_days <= 90, (c.recency_days <= 365) & (c.lifetime_gmv >= hi_value), c.recency_days <= 365],
        ["Loyal repeat", "Lapsed repeat", "New (last 90 days)", "High-value one-timer", "One-timer, cooling"],
        "Dormant (1 yr+)")
    c["rfm_segment_sort"] = c.rfm_segment.map({s: i for i, s in enumerate(
        ["Loyal repeat", "Lapsed repeat", "New (last 90 days)", "High-value one-timer", "One-timer, cooling",
         "Dormant (1 yr+)"], 1)})
    bands = ["< R$50", "R$50-100", "R$100-200", "R$200-500", "R$500+"]
    c["value_band"] = pd.cut(c.lifetime_gmv, [-1, 50, 100, 200, 500, np.inf], labels=bands).astype(str)
    c["value_band_sort"] = c.value_band.map({b: i for i, b in enumerate(bands, 1)})
    dim_customer = c.reset_index()

    # ---------- dim_product ----------
    p = products.rename(columns={"product_description_lenght": "description_length",
                                 "product_photos_qty": "photos_qty", "product_weight_g": "weight_g"})
    en = p.product_category_name.map(trans)
    p["category"] = en.map(lambda x: nice(x) if isinstance(x, str) else None).fillna("Uncategorized")
    p["category_group"] = en.map(GROUP_OF).fillna("Other / Uncategorized")
    unmapped = set(en[en.notna() & ~en.isin(GROUP_OF)])
    assert not unmapped, f"unmapped categories: {unmapped}"
    p["volume_cm3"] = p.product_length_cm * p.product_height_cm * p.product_width_cm
    p["size_band"] = pd.cut(p.weight_g, [-1, 500, 2000, 10000, np.inf],
                            labels=["Small (<0.5 kg)", "Medium (0.5-2 kg)", "Large (2-10 kg)", "Bulky (10 kg+)"]).astype(str)
    p.loc[p.weight_g.isna(), "size_band"] = "Unknown"
    p["size_band_sort"] = p.size_band.map({"Small (<0.5 kg)": 1, "Medium (0.5-2 kg)": 2, "Large (2-10 kg)": 3,
                                           "Bulky (10 kg+)": 4, "Unknown": 5})
    sold = fct_items.product_id.unique()
    dim_product = p[p.product_id.isin(sold)][["product_id", "category", "category_group", "size_band", "size_band_sort", "weight_g",
                                              "volume_cm3", "photos_qty", "description_length"]]

    # ---------- dim_seller ----------
    s = sellers[sellers.seller_id.isin(fct_items.seller_id)].copy()
    g = fct_items.groupby("seller_id").price.sum()
    s["seller_gmv"] = s.seller_id.map(g)
    rank = s.seller_gmv.rank(ascending=False, pct=True)
    s["seller_tier"] = np.select([rank <= 0.01, rank <= 0.10, rank <= 0.50], ["Top 1%", "Top 2-10%", "Top 11-50%"],
                                 "Bottom 50%")
    s["seller_tier_sort"] = s.seller_tier.map({"Top 1%": 1, "Top 2-10%": 2, "Top 11-50%": 3, "Bottom 50%": 4})
    s["state_name"] = s.seller_state.map(lambda x: STATE[x][0])
    s["region"] = s.seller_state.map(lambda x: STATE[x][1])
    s["seller_city"] = s.seller_city.str.title()
    first_sale = fct_items.merge(o[["order_id", "order_purchase_timestamp"]], on="order_id").groupby("seller_id") \
        .order_purchase_timestamp.min().dt.normalize()
    s["first_sale_date"] = s.seller_id.map(first_sale)
    s["seller_label"] = "Seller " + s.seller_id.str[:6]  # short, readable id for tables
    dim_seller = s[["seller_id", "seller_label", "seller_city", "seller_state", "state_name", "region",
                    "first_sale_date", "seller_tier", "seller_tier_sort", "seller_gmv"]]

    # ---------- dim_date ----------
    d = pd.DataFrame({"date": pd.date_range(START.normalize(), END.normalize(), freq="D")})
    d["date_key"] = date_key(d.date)
    d["year"] = d.date.dt.year
    d["quarter"] = "Q" + d.date.dt.quarter.astype(str)
    d["month_num"] = d.date.dt.month
    d["month_name"] = d.date.dt.strftime("%b")
    d["year_month"] = d.date.dt.strftime("%Y-%m")
    d["month_start"] = d.date.dt.to_period("M").dt.to_timestamp()
    d["week_start"] = d.date - pd.to_timedelta(d.date.dt.weekday, unit="D")
    d["weekday_num"] = d.date.dt.weekday + 1
    d["weekday"] = d.date.dt.strftime("%a")
    d["is_weekend"] = (d.weekday_num >= 6).astype(int)
    dim_date = d[["date_key", "date", "year", "quarter", "month_num", "month_name", "year_month", "month_start",
                  "week_start", "weekday_num", "weekday", "is_weekend"]]

    return {"fct_orders": fct_orders, "fct_order_items": fct_items, "fct_payments": fct_payments,
            "dim_customer": dim_customer, "dim_product": dim_product, "dim_seller": dim_seller, "dim_date": dim_date}


def surrogate_keys(t: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Swap Olist's 32-char hash ids for integer keys (3x smaller workbook, faster joins in VertiPaq).
    Hashes are dropped; seller_label keeps a short readable id for tables."""
    maps = {
        "order_key": ("order_id", t["fct_orders"].order_id),
        "customer_key": ("customer_unique_id", t["dim_customer"].customer_unique_id),
        "product_key": ("product_id", t["dim_product"].product_id),
        "seller_key": ("seller_id", t["dim_seller"].seller_id),
    }
    out = {}
    for name, df in t.items():
        df = df.copy()
        for key, (col, ids) in maps.items():
            if col in df:
                df.insert(0 if df.columns[0] == col else df.columns.get_loc(col), key,
                          df[col].map(pd.Series(range(1, len(ids) + 1), index=ids.values)).astype("Int64"))
                df = df.drop(columns=col)
        out[name] = df
    out["fct_order_items"] = out["fct_order_items"].drop(columns=["order_line_id"])
    out["fct_order_items"].insert(0, "order_line_key", range(1, len(out["fct_order_items"]) + 1))
    out["fct_payments"] = out["fct_payments"].drop(columns=["payment_id"])
    return out


def check(t: dict[str, pd.DataFrame]) -> None:
    """Keys unique, every foreign key resolves (the model's relationships must be clean many-to-one)."""
    pk = {"fct_orders": "order_id", "fct_order_items": "order_line_id", "fct_payments": "payment_id",
          "dim_customer": "customer_unique_id", "dim_product": "product_id", "dim_seller": "seller_id",
          "dim_date": "date_key"}
    for table, col in pk.items():
        assert t[table][col].is_unique, f"{table}.{col} not unique"
    fk = [("fct_orders", "date_key", "dim_date"), ("fct_orders", "customer_unique_id", "dim_customer"),
          ("fct_order_items", "order_id", "fct_orders"), ("fct_order_items", "product_id", "dim_product"),
          ("fct_order_items", "seller_id", "dim_seller"), ("fct_payments", "order_id", "fct_orders")]
    for table, col, dim in fk:
        target = "order_id" if dim == "fct_orders" else pk[dim]
        orphans = ~t[table][col].isin(t[dim][target])
        if table == "fct_orders" and col == "customer_unique_id":
            # customers whose only orders were cancelled have no dim row; they never carry GMV
            assert t[table].loc[orphans, "is_canceled"].eq(1).all(), "valid order without a customer row"
            continue
        assert not orphans.any(), f"{orphans.sum()} orphan {table}.{col}"


def tidy(df: pd.DataFrame) -> pd.DataFrame:
    """Whole-number floats (NaN-padded counts/flags) -> Int64; other floats rounded to 3 dp for compact CSVs."""
    df = df.copy()
    for c in df.select_dtypes("float").columns:
        s = df[c].dropna()
        df[c] = df[c].astype("Int64") if (s == s.round()).all() else df[c].round(3)
    return df


def main() -> None:
    t = build()
    check(t)
    t = {name: tidy(df) for name, df in surrogate_keys(t).items()}
    OUT.mkdir(parents=True, exist_ok=True)
    for name, df in t.items():
        df.to_csv(OUT / f"{name}.csv", index=False, date_format="%Y-%m-%d")
        print(f"{name:16s} {len(df):>7,} rows  {df.shape[1]:>2} cols")
    print(f"-> {OUT.relative_to(ROOT)}/*.csv")


if __name__ == "__main__":
    main()
