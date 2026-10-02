# Open OST2PST v0.1.6

Pre-alpha Windows release adding an interactive, read-only PST report mode.

## New PST workflow

The GUI now switches behavior from the selected source extension:

- selecting an `.ost` keeps the existing OST → PST conversion workflow;
- selecting a `.pst` disables PST conversion and opens the report-template menu.

The PST source is opened read-only through pypff. Report mode never invokes the PST writer and never rewrites the selected PST.

## First report template: RH — Activité hors horaires

The interactive template lets the user configure:

- theoretical workday start/end time (default 09:00–18:00);
- working weekdays (default Monday–Friday);
- optional start/end analysis dates;
- output directory.

Activity is intentionally limited to messages found under Sent Items / recognized localized sent folders. The scanner prefers the pypff `client_submit_time` timestamp, then falls back to `delivery_time`, then `creation_time` when necessary.

The scanner is lightweight: it reads folder/message metadata and timestamps only. It does not load message bodies or attachment payloads.

## Eight MVP KPI

1. percentage of scheduled workdays with activity outside theoretical hours;
2. number of days with more than one hour after theoretical end;
3. number of days with more than two hours after theoretical end;
4. median last-activity time;
5. latest last-activity time;
6. maximum consecutive days with an observed overrun;
7. activity on configured rest days/weekends;
8. minimum apparent rest between the last activity of one active day and the first of the next.

The output is an HTML report plus an auditable JSON sidecar. The GUI also shows the eight KPI directly and offers a button to open the generated HTML report.

## Interpretation

The report describes messaging traces observed in the PST. It does not measure effective working time, productivity, performance or intent, and it should not be used alone as an individual employment evaluation.

## Validation

- Python 3.10–3.13 unit suite;
- KPI calculation tests;
- localized Sent Items and lightweight PST scan tests;
- GUI parameter/parser tests;
- libpff interoperability suite;
- Windows harness;
- frozen Windows executable self-test and build.

## Status

This remains a **pre-alpha** release. The executables are not Authenticode-signed, so Windows SmartScreen may display a warning on first launch.
