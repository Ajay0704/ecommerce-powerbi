"""Headline KPIs computed independently in pandas from data/model/*.csv.

Every DAX measure in powerbi/measures.dax is reconciled against these numbers
(see docs/reconciliation.md). Also prints the findings quoted in the README.

    python3 pipeline/reference_kpis.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
M = ROOT / "data" / "model"


def load() -> dict[str, pd.DataFrame]:
    return {p.stem: pd.read_csv(p) for p in M.glob("*.csv")}


def kpis(t: dict[str, pd.DataFrame]) -> dict:
    o, i, pay, cust, prod, sel, d = (t[k] for k in ["fct_orders", "fct_order_items", "fct_payments", "dim_customer",
                                                     "dim_product", "dim_seller", "dim_date"])
    valid = o[o.is_canceled == 0]
    dlv = o[o.is_delivered == 1]
    i = i.merge(o[["order_key", "date_key"]], on="order_key").merge(prod, on="product_key")
    i["year"] = i.date_key // 10000
    gmv = i.price.sum()
    r = {
        "GMV": gmv,
        "Freight Revenue": i.freight_value.sum(),
        "Orders": len(valid),
        "Orders (with items)": i.order_key.nunique(),
        "AOV": gmv / i.order_key.nunique(),
        "Items Sold": len(i),
        "Customers": valid.customer_key.nunique(),
        "Cancellation Rate": o.is_canceled.mean(),
        "Avg Review Score": o.review_score.mean(),
        "On-Time Delivery %": 1 - dlv.is_late.mean(),
        "Late Delivery %": dlv.is_late.mean(),
        "Avg Delivery Days": dlv.delivery_days.mean(),
        "Avg Promised Days": dlv.promised_days.mean(),
        "Avg Review (on time)": dlv.loc[dlv.is_late == 0, "review_score"].mean(),
        "Avg Review (late)": dlv.loc[dlv.is_late == 1, "review_score"].mean(),
        "Repeat Customer Rate": cust.is_repeat_customer.mean(),
        "Freight % of GMV": i.freight_value.sum() / gmv,
        "Active Sellers": i.seller_key.nunique(),
        "Payment Value": pay.payment_value.sum(),
    }
    # Jan-Aug 2018 vs Jan-Aug 2017 (the comparable YoY window)
    m = i.date_key % 10000 // 100
    r["GMV Jan-Aug 2018"] = i.loc[(i.year == 2018) & (m <= 8), "price"].sum()
    r["GMV Jan-Aug 2017"] = i.loc[(i.year == 2017) & (m <= 8), "price"].sum()
    r["GMV YoY % (Jan-Aug)"] = r["GMV Jan-Aug 2018"] / r["GMV Jan-Aug 2017"] - 1
    r["GMV 2017"] = i.loc[i.year == 2017, "price"].sum()
    # Black Friday 2017
    r["GMV 2017-11-24"] = i.loc[i.date_key == 20171124, "price"].sum()
    r["Orders 2017-11-24"] = (valid.date_key == 20171124).sum()
    # category concentration
    cat = i.groupby("category").price.sum().sort_values(ascending=False)
    r["Top category"] = cat.index[0]
    r["Top category share"] = cat.iloc[0] / gmv
    r["Categories for 80% GMV"] = int((cat.cumsum() / gmv < 0.8).sum() + 1)
    r["Categories"] = len(cat)
    grp = i.groupby("category_group").price.sum().sort_values(ascending=False)
    r["Category groups"] = (grp / gmv).round(4).to_dict()
    # sellers
    sg = i.merge(sel, on="seller_key").groupby("seller_tier").price.sum() / gmv
    r["GMV share by seller tier"] = sg.round(4).to_dict()
    # delivery by region of customer
    dc = dlv.merge(cust[["customer_key", "region"]], on="customer_key")
    r["Avg delivery days by region"] = dc.groupby("region").delivery_days.mean().round(1).to_dict()
    r["Late % by region"] = dc.groupby("region").is_late.mean().round(4).to_dict()
    r["Same-state avg delivery days"] = dlv.loc[dlv.is_same_state == 1, "delivery_days"].mean()
    r["Cross-state avg delivery days"] = dlv.loc[dlv.is_same_state == 0, "delivery_days"].mean()
    r["Review by delivery status"] = dlv.groupby("delivery_status").review_score.mean().round(2).to_dict()
    r["1-2 star % (late)"] = (dlv.loc[dlv.is_late == 1, "review_score"] <= 2).mean()
    r["1-2 star % (on time)"] = (dlv.loc[dlv.is_late == 0, "review_score"] <= 2).mean()
    # payments
    r["Payment share by type"] = (pay.groupby("payment_type").payment_value.sum() / pay.payment_value.sum()).round(4).to_dict()
    cc = pay[pay.payment_type == "Credit Card"]
    r["Avg installments (credit card)"] = cc.payment_installments.mean()
    r["% credit-card payments in 2+ installments"] = (cc.payment_installments >= 2).mean()
    # customers
    r["RFM segments"] = cust.rfm_segment.value_counts().to_dict()
    r["Repeat customers GMV share"] = cust.loc[cust.is_repeat_customer == 1, "lifetime_gmv"].sum() / cust.lifetime_gmv.sum()
    m1 = valid[valid.months_since_first_order.between(1, 3)].customer_key.nunique()
    r["Customers returning within 3 months"] = m1 / cust.customer_key.nunique()
    return r


def main() -> None:
    r = kpis(load())
    for k, v in r.items():
        print(f"{k:42s} {v:,.4f}" if isinstance(v, float) else f"{k:42s} {v}")
    (ROOT / "docs" / "reference_kpis.json").write_text(json.dumps(r, indent=2, default=float))


if __name__ == "__main__":
    main()
