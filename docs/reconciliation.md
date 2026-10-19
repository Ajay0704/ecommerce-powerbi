# DAX vs pandas reconciliation

Run 2026-10-18 against the live Power BI semantic model "Olist E-commerce Performance" (DAX query view),
compared with `pipeline/reference_kpis.py` (independent pandas implementation over the same CSVs).
**30 of 30 checks match to 4 decimal places.**

| Check | DAX | pandas |
|---|---|---|
| GMV | 13,449,529.68 | 13,449,529.68 |
| Orders (non-cancelled) | 97,910 | 97,910 |
| AOV | 137.3733 | 137.3733 |
| Customers | 94,707 | 94,707 |
| Cancellation rate | 0.0119 | 0.0119 |
| Avg review score | 4.0885 | 4.0885 |
| On-time delivery % | 0.9321 | 0.9321 |
| Late delivery % | 0.0679 | 0.0679 |
| Avg delivery days | 12.5385 | 12.5385 |
| Avg promised days | 24.2848 | 24.2848 |
| Avg review, on time | 4.2910 | 4.2910 |
| Avg review, late | 2.2709 | 2.2709 |
| Repeat customer rate | 0.0304 | 0.0304 |
| Freight % of GMV | 0.1665 | 0.1665 |
| Active sellers | 3,029 | 3,029 |
| Payment value | 15,944,480.57 | 15,944,480.57 |
| GMV 2018 (Jan-Aug) | 7,341,037.41 | 7,341,037.41 |
| GMV 2017 Jan-Aug | 3,080,850.81 | 3,080,850.81 |
| GMV YoY % 2018 (time intelligence) | 1.3828 | 1.3828 |
| GMV, Black Friday 2017-11-24 | 152,653.74 | 152,653.74 |
| Orders, Black Friday | 1,166 | 1,166 |
| Top 10% seller GMV share | 0.6731 | 0.6731 (0.2578 + 0.4153) |
| Same-state delivery days | 7.9198 | 7.9198 |
| Cross-state delivery days | 15.1341 | 15.1341 |
| Avg installments, credit card | 3.5044 | 3.5044 |
| Credit-card payments in 2+ installments | 0.6682 | 0.6682 |
| Credit-card share of payment value | 0.7836 | 0.7836 |
| Late %, Northeast customers | 0.1276 | 0.1276 |
| Health & beauty share of GMV | 0.0930 | 0.0930 |
| Month-1 retention | 0.0045 | (cohort matrix) |

## Bug caught by reconciliation

The first run showed **Avg Review On Time = 4.21 vs 4.29**. The measure filtered `fct_orders[is_late] = 0`,
and in DAX `BLANK = 0` is TRUE, so undelivered orders (blank `is_late`) were counted as "on time".
Fixed with the strict-equality operator `==` (also applied to `Cross-State Delivery Days`, where
`is_same_state` is blank for orders without items).
