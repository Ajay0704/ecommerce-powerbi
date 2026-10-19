"""The 5-page report as code: writes a PBIR report definition to powerbi/report/.

    python3 powerbi/gen_report.py

The definition is published with the Fabric REST API (Items - Create Report), bound to the semantic
model "Olist E-commerce Performance" by id. Every number in a title is checked in docs/reconciliation.md.
Palette: the dataviz reference categorical palette (validated for CVD); slot 1 carries single-series charts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "report"
MODEL_NAME = "Olist E-commerce Performance"
MODEL_ID = "1ffadd21-df69-4e1b-88a9-b5823c7a7525"
W, H, G = 1280, 720, 16  # canvas and gutter

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
THEME_NAME = "OlistAnalyst.json"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#8a8984"
THEME = {
    "name": "Olist Analyst",
    "dataColors": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
    "background": "#FFFFFF", "foreground": INK, "tableAccent": "#2a78d6",
    "textClasses": {
        "title": {"fontFace": "Segoe UI Semibold", "fontSize": 11, "color": INK},
        "label": {"fontFace": "Segoe UI", "fontSize": 9, "color": INK2},
        "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 20, "color": INK},
    },
    "visualStyles": {
        "page": {"*": {"background": [{"color": {"solid": {"color": "#F4F5F7"}}, "transparency": 0}]}},
        "*": {"*": {
            "background": [{"show": True, "color": {"solid": {"color": "#FFFFFF"}}, "transparency": 0}],
            "border": [{"show": True, "color": {"solid": {"color": "#E3E4E6"}}, "radius": 8}],
            "valueAxis": [{"gridlineColor": {"solid": {"color": "#ECECEC"}}}],
        }},
    },
}


def lit(v) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def q(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def M(entity: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def C(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj(field, active: bool = True) -> dict:
    """field, or (field, display name) for a friendly header."""
    field, name = field if isinstance(field, tuple) else (field, None)
    kind = "Measure" if "Measure" in field else "Column"
    e = field[kind]["Expression"]["SourceRef"]["Entity"]
    p = field[kind]["Property"]
    out = {"field": field, "queryRef": f"{e}.{p}", "nativeQueryRef": p}
    if kind == "Column" and active:  # tables don't take the flag (only the first column renders with it)
        out["active"] = True
    if name:
        out["displayName"] = name
    return out


def titled(title: str) -> dict:
    return {"title": [{"properties": {"show": lit("true"), "text": lit(q(title))}}],
            "subTitle": [{"properties": {"show": lit("false")}}]}


# measure -> home table (mirrors gen_tmdl.HOME via measures.dax folders)
def _homes() -> dict[str, str]:
    import sys
    sys.path.insert(0, str(HERE))
    from gen_tmdl import HOME, parse_measures
    return {n: HOME[f] for f, n, _ in parse_measures((HERE / "measures.dax").read_text())}


HOMES = _homes()


def m(name: str) -> dict:
    return M(HOMES[name], name)


class Page:
    def __init__(self, name: str, title: str, question: str):
        self.id = hashlib.sha1(name.encode()).hexdigest()[:20]
        self.name, self.visuals, self.z = name, [], 0
        self.text(title, question)
        self.slicer(C("dim_date", "year"), "Year", (W - 2 * 180 - G - 12, 6, 180, 68))
        self.slicer(C("dim_customer", "region"), "Customer region", (W - 180 - G, 6, 180, 68))

    def add(self, box, visual: dict):
        x, y, w, h = box
        vid = hashlib.sha1(f"{self.name}{len(self.visuals)}".encode()).hexdigest()[:20]
        visual.setdefault("drillFilterOtherVisuals", True)
        self.visuals.append({"$schema": f"{SCHEMA}/visualContainer/2.13.0/schema.json", "name": vid,
                             "position": {"x": x, "y": y, "z": self.z, "height": h, "width": w, "tabOrder": self.z},
                             "visual": visual})
        self.z += 1

    def text(self, title: str, sub: str):
        runs = [{"textRuns": [{"value": title, "textStyle": {"fontWeight": "bold", "fontSize": "18pt", "color": INK}}]},
                {"textRuns": [{"value": sub, "textStyle": {"fontSize": "10pt", "color": INK2}}]}]
        self.add((G, 12, W - 2 * 180 - 3 * G - 12, 56), {
            "visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": runs}}]},
            "visualContainerObjects": {"background": [{"properties": {"show": lit("false")}}],
                                       "border": [{"properties": {"show": lit("false")}}]}})

    def slicer(self, col: dict, title: str, box):
        self.add(box, {"visualType": "slicer", "query": {"queryState": {"Values": {"projections": [proj(col)]}}},
                       "objects": {"data": [{"properties": {"mode": lit("'Dropdown'")}}]},
                       "visualContainerObjects": {"title": [{"properties": {"show": lit("true"), "text": lit(q(title))}}]}})

    def cards(self, measures: list[str], box=(G, 80, W - 2 * G, 104)):
        self.add(box, {"visualType": "cardVisual",
                       "query": {"queryState": {"Data": {"projections": [proj(m(x)) for x in measures]}}},
                       "visualContainerObjects": {"title": [{"properties": {"show": lit("false")}}]}})

    def chart(self, vtype: str, box, title: str, category: dict | None, values: list[dict], sort=None,
              labels=True, roles=("Category", "Y")):
        qs = {}
        if category:
            qs[roles[0]] = {"projections": [proj(category)]}
        qs[roles[1]] = {"projections": [proj(v) for v in values]}
        visual = {"visualType": vtype, "query": {"queryState": qs},
                  "visualContainerObjects": titled(title)}
        if sort:
            field, direction = sort
            visual["query"]["sortDefinition"] = {"sort": [{"field": field, "direction": direction}], "isDefaultSort": True}
        if labels:
            visual["objects"] = {"labels": [{"properties": {"show": lit("true")}}]}
        self.add(box, visual)

    def table(self, vtype: str, box, title: str, roles: dict[str, list[dict]], sort=None):
        visual = {"visualType": vtype,
                  "query": {"queryState": {r: {"projections": [proj(f, active=vtype != "tableEx") for f in fs]}
                                           for r, fs in roles.items()}},
                  "visualContainerObjects": titled(title)}
        if sort:
            visual["query"]["sortDefinition"] = {"sort": [{"field": sort[0], "direction": sort[1]}], "isDefaultSort": True}
        if vtype == "pivotTable":  # a "Total" for retention % is meaningless
            visual["objects"] = {"subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}]}
        self.add(box, visual)


# grid: KPI row at y=80; two chart rows below
HALF = (W - 3 * G) // 2
R1 = 196
RH = (H - R1 - 2 * G) // 2
R2 = R1 + RH + G
L1, R1B = (G, R1, HALF, RH), (2 * G + HALF, R1, HALF, RH)
L2, R2B = (G, R2, HALF, RH), (2 * G + HALF, R2, HALF, RH)
FULL2 = (G, R2, W - 2 * G, RH)


def pages() -> list[Page]:
    month = C("dim_date", "month_start")

    p1 = Page("Executive overview", "Executive overview",
              "How big is the business and is it growing?  Olist marketplace, Jan 2017 - Aug 2018, GMV in R$")
    p1.cards(["GMV", "GMV YoY % (latest year)", "Orders", "AOV", "Customers", "Avg Review Score", "On-Time Delivery %"])
    p1.chart("lineChart", L1, "GMV by month: Jan-Aug 2018 up 138% YoY; Black Friday spike in Nov 2017",
             month, [m("GMV")], sort=(month, "Ascending"), labels=False)
    p1.chart("clusteredBarChart", R1B, "GMV by category group: Home & Furniture leads with 21%",
             C("dim_product", "category_group"), [m("GMV")], sort=(m("GMV"), "Descending"))
    p1.chart("clusteredBarChart", L2, "GMV by customer region", C("dim_customer", "region"), [m("GMV")],
             sort=(m("GMV"), "Descending"))
    hour = C("fct_orders", "purchase_hour")
    p1.chart("clusteredColumnChart", R2B, "Orders by hour of day (customer time)", hour, [m("Orders")],
             sort=(hour, "Ascending"), labels=False)

    p2 = Page("Sales & product", "Sales & product",
              "Which categories drive GMV, at what price points, and how do customers pay?")
    p2.cards(["GMV", "Items Sold", "Avg Item Price", "Items per Order", "Freight % of GMV", "Avg Installments (Credit Card)"])
    cat = C("dim_product", "category")
    p2.chart("clusteredBarChart", L1, "GMV by category: 18 of 74 categories make 80% of GMV", cat, [m("GMV")],
             sort=(m("GMV"), "Descending"))
    p2.table("tableEx", R1B, "Category scorecard (Pareto, price, delivery and review by category)",
             {"Values": [(cat, "Category"), m("GMV"), m("Category Share %"), m("Category Cumulative %"), m("Avg Item Price"),
                         m("Late Delivery % (items view)"), m("Avg Review (items view)")]},
             sort=(m("GMV"), "Descending"))
    size = C("dim_product", "size_band")
    p2.chart("clusteredColumnChart", L2, "Freight as % of item value by weight: small items carry the heaviest burden (19.7%)",
             size, [m("Freight % of GMV")], sort=(size, "Ascending"))
    p2.chart("clusteredBarChart", R2B, "Payment mix: credit card is 78% of payment value",
             C("fct_payments", "payment_type"), [m("Payment Share %")], sort=(m("Payment Share %"), "Descending"))

    p3 = Page("Customers & retention", "Customers & retention",
              "Do customers come back?  Retention by first-purchase cohort and RFM segments to target")
    p3.cards(["Customers", "New Customers", "Returning Customers", "Repeat Customer Rate", "Avg Lifetime GMV"])
    p3.chart("lineChart", L1, "New customers by month", month, [m("New Customers")], sort=(month, "Ascending"),
             labels=False)
    seg = C("dim_customer", "rfm_segment")
    p3.chart("clusteredBarChart", R1B, "Customers by RFM segment (as of 2018-09-01): only 3% ever buy twice",
             seg, [m("Customer Count")], sort=(seg, "Ascending"))
    p3.table("pivotTable", FULL2, "Cohort retention: % of each first-purchase cohort ordering again N months later",
             {"Rows": [(C("dim_customer", "cohort_month"), "Cohort (first purchase)")],
              "Columns": [(C("fct_orders", "months_since_first_order"), "Months since first order")],
              "Values": [m("Retention %")]})

    p4 = Page("Delivery & operations", "Delivery & operations",
              "How fast do we deliver, where are we late, and what does lateness cost in reviews?")
    p4.cards(["Avg Delivery Days", "Avg Promised Days", "On-Time Delivery %", "Avg Days Late (late orders)",
              "Same-State Delivery Days", "Cross-State Delivery Days"])
    status = C("fct_orders", "delivery_status")
    p4.chart("clusteredColumnChart", L1, "Avg review by delivery outcome: 4.3 stars on time, 1.7 at 8+ days late",
             status, [m("Avg Review Score")], sort=(status, "Ascending"))
    p4.chart("lineChart", R1B, "Late delivery rate by month: 12% after Black Friday 2017, peak 19% in Mar 2018", month, [m("Late Delivery %")],
             sort=(month, "Ascending"), labels=False)
    state = C("dim_customer", "state_name")
    p4.chart("clusteredBarChart", L2, "Avg delivery days by customer state", state, [m("Avg Delivery Days")],
             sort=(m("Avg Delivery Days"), "Descending"))
    p4.chart("clusteredBarChart", R2B, "Late delivery rate by customer state", state, [m("Late Delivery %")],
             sort=(m("Late Delivery %"), "Descending"))

    p5 = Page("Seller performance", "Seller performance",
              "How concentrated is GMV across sellers, and which sellers drag down delivery and reviews?")
    p5.cards(["Active Sellers", "GMV per Seller", "Top 10% Seller GMV Share", "Avg Handling Days (items view)",
              "Late Delivery % (items view)", "Avg Review (items view)"])
    tier = C("dim_seller", "seller_tier")
    p5.chart("clusteredColumnChart", L1, "GMV by seller tier: the top 10% of sellers make 67% of GMV", tier,
             [m("GMV")], sort=(tier, "Ascending"))
    p5.chart("clusteredBarChart", R1B, "Active sellers by seller state", C("dim_seller", "state_name"),
             [m("Active Sellers")], sort=(m("Active Sellers"), "Descending"))
    p5.table("tableEx", FULL2, "Seller scorecard (sorted by GMV): spot high-volume sellers with late deliveries or low reviews",
             {"Values": [(C("dim_seller", "seller_label"), "Seller"), (C("dim_seller", "seller_state"), "State"),
                         (tier, "Tier"), m("GMV"),
                         m("Ordered Baskets"), m("Avg Review (items view)"), m("Late Delivery % (items view)"),
                         m("Avg Handling Days (items view)")]},
             sort=(m("GMV"), "Descending"))
    return [p1, p2, p3, p4, p5]


def build() -> dict[str, str]:
    ps = pages()
    files = {
        "definition.pbir": {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                            "version": "4.0",
                            "datasetReference": {"byConnection": {"connectionString":
                                f'Data Source="powerbi://api.powerbi.com/v1.0/myorg/My workspace";initial catalog="{MODEL_NAME}";'
                                f"integrated security=ClaimsToken;semanticmodelid={MODEL_ID}"}}},
        "definition/version.json": {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"},
        "definition/report.json": {
            "$schema": f"{SCHEMA}/report/3.3.0/schema.json",
            "themeCollection": {
                "baseTheme": {"name": "Fluent2-CY26SU10", "reportVersionAtImport": {"visual": "2.14.0", "report": "3.4.0", "page": "2.3.1"},
                              "type": "SharedResources"},
                "customTheme": {"name": THEME_NAME, "reportVersionAtImport": {"visual": "2.14.0", "report": "3.4.0", "page": "2.3.1"},
                                "type": "RegisteredResources"}},
            "resourcePackages": [
                {"name": "SharedResources", "type": "SharedResources",
                 "items": [{"name": "Fluent2-CY26SU10", "path": "BaseThemes/Fluent2-CY26SU10.json", "type": "BaseTheme"}]},
                {"name": "RegisteredResources", "type": "RegisteredResources",
                 "items": [{"name": THEME_NAME, "path": THEME_NAME, "type": "CustomTheme"}]}],
            "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized",
                         "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                         "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True}},
        "definition/pages/pages.json": {"$schema": f"{SCHEMA}/pagesMetadata/1.1.0/schema.json",
                                        "pageOrder": [p.id for p in ps], "activePageName": ps[0].id},
        f"StaticResources/RegisteredResources/{THEME_NAME}": THEME,
    }
    for p in ps:
        files[f"definition/pages/{p.id}/page.json"] = {"$schema": f"{SCHEMA}/page/2.1.0/schema.json", "name": p.id,
                                                      "displayName": p.name, "displayOption": "FitToPage",
                                                      "height": H, "width": W}
        for v in p.visuals:
            files[f"definition/pages/{p.id}/visuals/{v['name']}/visual.json"] = v
    return {k: json.dumps(v, indent=2, ensure_ascii=False) for k, v in files.items()}


def main() -> None:
    files = build()
    for path, text in files.items():
        f = OUT / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text + "\n")
    n = sum(1 for p in files if p.endswith("visual.json"))
    print(f"{n} visuals on {sum(1 for p in files if p.endswith('page.json'))} pages -> {OUT.relative_to(HERE.parent)}/")


if __name__ == "__main__":
    main()
