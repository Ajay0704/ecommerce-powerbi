# Build notes: Power BI web as code (macOS, free license)

How this dashboard was built without Power BI Desktop, and the gotchas hit along the way.

## Data source
- Power Query Online → Text/CSV → "Link to file" with a `raw.githubusercontent.com` URL creates the semantic model
  with one seed table (`fct_payments`, no date columns, so type sniffing can't go wrong).
- The other six tables are defined in TMDL (`powerbi/model_full.tmdl`) with explicit column types and M partitions
  `Web.Contents("https://raw.githubusercontent.com", [RelativePath = ...])`. One base URL means the service needs a
  single anonymous credential (semantic model settings → Data source credentials, privacy level Public).

## Model (TMDL view in the browser)
- Paste scripts into the Monaco editor with `editor.trigger('keyboard', 'paste', {text})`; click **Apply** by
  coordinates (a scripted `.click()` often does nothing), then Refresh.
- The service creates hidden auto date/time tables for date columns. After that, change those tables with
  `ref table` + only the changed columns + a new partition (`gen_tmdl.py --sort`), never a full table replace.
- DAX: `column = 0` also matches BLANK. Use `==` on nullable flags (caught by the reconciliation).
- YoY with a partial first year: return blank unless `EDATE(MIN(date), -12)` is inside the calendar.

## Report (PBIR via the Fabric REST API)
- From a signed-in app.powerbi.com tab, the page's own access token works against
  `api.fabric.microsoft.com/v1/workspaces/{ws}/reports` (create, `getDefinition`, `updateDefinition`; long-running
  operations return 202 + Location to poll). This worked on a free license in My workspace.
- The definition must include the base theme file (`StaticResources/SharedResources/BaseThemes/...`); copy it from
  `getDefinition` of any existing report. A custom theme goes in `StaticResources/RegisteredResources/`.
- `tableEx` column projections must not carry `"active": true` (only the first column renders). Hide auto
  subtitles with `subTitle.show = false`; turn matrix totals off with `subTotals`; `displayName` sets headers.
