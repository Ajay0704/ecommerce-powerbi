# E-commerce Performance Dashboard (Power BI)

A Power BI dashboard for a marketplace e-commerce business, built the way an in-house data analyst would:
clean the raw order data into a star schema, define every KPI once in a DAX semantic model, check every
number against an independent pandas calculation, then answer a different stakeholder's questions on each page.

**Data:** [Olist Brazilian E-Commerce Public Dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
(real, anonymised marketplace orders; CC BY-NC-SA 4.0). Window: Jan 2017 to Aug 2018, the 20 full months.
That's 97.9k orders, 111.8k items, 94.7k customers and 3,029 sellers.

## Use cases (one report page each)

| Page | Stakeholder | Questions it answers |
|---|---|---|
| 1. Executive overview | Leadership | How big is the business and is it growing? GMV, orders, AOV, customers, review score, on-time rate, monthly trend, YoY |
| 2. Sales & product | Category / merchandising | Which categories drive GMV (Pareto)? Price points, freight burden, how customers pay (installments) |
| 3. Customers & retention | Marketing / CRM | Do customers come back? New vs returning, cohort retention, RFM segments to target |
| 4. Delivery & operations | Ops / logistics | How fast do we deliver, where are we late, and what does lateness cost in review scores? |
| 5. Seller performance | Marketplace / partner team | How concentrated is GMV across sellers, and which sellers drag down delivery and reviews? |

## Key findings (Jan 2017 to Aug 2018)

| | |
|---|---|
| **R$13.45M GMV**, 97.9k orders, **R$137 AOV** | GMV Jan-Aug 2018 is **+138% YoY** (R$7.34M vs R$3.08M) |
| Black Friday 2017 (Nov 24) | 1,166 orders in one day, about 5x a normal day |
| **Late deliveries wreck reviews** | 6.8% of orders arrive after the promised date. They average **2.27 stars vs 4.29** on time, and 61% of late orders get 1-2 stars (vs 9% on time) |
| Promise is padded | Delivery takes 12.5 days on average against a 24.3-day promise. The north and northeast wait 20-23 days, and the northeast has the highest late rate (12.8%) |
| Distance matters | Same-state orders arrive in 7.9 days vs 15.1 days cross-state |
| **Almost no repeat buyers** | Only 3.0% of customers ever order twice, and repeat buyers bring 5.6% of GMV. Growth is pure acquisition |
| Sellers are concentrated | The top 10% of sellers make 67% of GMV; the bottom half make 3% |
| Payment | Credit cards are 78% of payment value, and 67% of card payments are split into 2+ installments (avg 3.5) |
| Category breadth | 18 of 74 categories make 80% of GMV. Home & Furniture is the largest group (21%) |

All figures come from `pipeline/reference_kpis.py` (pandas) and are reconciled against the DAX measures.

## Architecture

```
Olist raw CSVs (9 tables)
  └─ pipeline/build_model.py  ── clean, conform, surrogate keys, FK checks
       └─ data/model/*.csv    ── star schema (published here, read by Power BI over HTTPS)
            └─ Power BI semantic model (Import)
                 ├─ powerbi/model.tmdl     ── 6 relationships + 61 DAX measures (generated from measures.dax)
                 └─ 5-page report
pipeline/reference_kpis.py   ── independent pandas numbers used to reconcile the DAX
```

### Star schema

| Table | Grain | Notes |
|---|---|---|
| `fct_orders` | order | status, delivery timings, late flag, review score, payment summary, customer order sequence |
| `fct_order_items` | order line | price, freight; non-cancelled orders only (this is where GMV lives) |
| `fct_payments` | payment record | type, installments, value (an order can mix card + voucher) |
| `dim_customer` | person (`customer_unique_id`) | state, region, cohort month, lifetime GMV, RFM segment |
| `dim_product` | product | English category, category group (10), size band |
| `dim_seller` | seller | state, region, GMV tier (Top 1% / 2-10% / 11-50% / Bottom 50%) |
| `dim_date` | day | calendar attributes; time intelligence uses `dim_date[date]` |

Relationships are single-direction many-to-one. `fct_order_items` reaches dates and customers through `fct_orders`,
which avoids ambiguous filter paths. Seller- and category-level delivery and review measures use `CROSSFILTER` in
the measure instead of a bidirectional relationship.

### Definitions

- **GMV** = sum of item price on non-cancelled orders (cancelled + unavailable excluded). Freight is reported separately.
- **Late** = delivered on a later calendar day than the estimated delivery date (delivered orders only).
- **Repeat customer** = 2+ non-cancelled orders in the window, keyed on `customer_unique_id` (Olist issues a new `customer_id` per order).
- **RFM segment** (as of 2018-09-01): Loyal repeat, Lapsed repeat, New (last 90 days), High-value one-timer, One-timer cooling, Dormant (1 yr+).

## Reproduce

```bash
# put the Kaggle CSVs in data/raw/
python3 pipeline/build_model.py      # -> data/model/*.csv
python3 pipeline/reference_kpis.py   # -> docs/reference_kpis.json
python3 powerbi/gen_tmdl.py          # -> powerbi/model.tmdl (paste into Power BI TMDL view)
```

## Repository layout

```
pipeline/   build_model.py, reference_kpis.py
data/model/ star-schema CSVs (the Power BI source)
powerbi/    measures.dax (source of truth), gen_tmdl.py, model.tmdl
docs/       reference_kpis.json, screenshots
```
