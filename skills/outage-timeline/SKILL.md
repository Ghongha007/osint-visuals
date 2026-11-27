---
name: outage-timeline
description: Draw a disruption timeline from your own table - state shutdowns, throttling, jamming, cable cuts and cyberattacks as bars over time, grouped by country or by area, with a monthly event-day strip, a country map, a mechanism and trigger breakdown and the sources on the graphic. Use when the user has dated disruption events and wants a timeline, a shutdown map or an outage trend, without naming people.
---

# Outage timeline

Makes one self-contained HTML page from a table of disruption events: a Gantt timeline by
country or by area, a monthly event-day strip, a country map, a mechanism, scope and trigger
breakdown, and a table, with filters and PNG/SVG export. Country outlines come from Natural
Earth, cached once.

The graphic is aggregate. It shows where and when disruptions were reported, not who was cut
off, and it names no person or individual subscriber.

## Before you start

1. **A table**, CSV or JSON, one row per event:

   ```
   start,end,country,region,scope,cause,trigger,impact,source,notes
   2026-02-03,2026-02-06,Germany,,national,shutdown,Protest,2,Incident review Q1,Regional fibre cut
   ```

   `start` and `country` are required. `end` defaults to the start day. `cause`, `trigger`,
   `scope`, `region`, `impact`, `source` and `notes` are optional. Country names, ISO alpha-2 and
   alpha-3 codes match the Natural Earth names, and common long forms ("Iran (Islamic Republic
   of)", "Viet Nam") are mapped.
2. **What a row means.** A state-ordered shutdown, a measured outage, a reported jamming
   episode: decide, and say it. One row is one event, not one subscriber.
3. **The dataset and its window**, for `--source`. A reported outage is not a measured one, and
   two datasets that both say "outage" may not count the same thing.
4. **No person data.** Do not pass subscriber, account or device columns. The script reads the
   event columns only; keep the file aggregate anyway.

## Dates

- Plain dates are ISO: `2026-02-03` or `2026/02/03`.
- Slash dates are ambiguous. `03/04/2026` is read with `--date-format us` (4 March) or
  `--date-format eu` (3 April); `auto` only accepts a slash date when one part is above 12.
- An `end` of `Ongoing` or `Unknown`, or a blank `end`, runs to `--snapshot` (default: today) and
  is drawn with a dashed bar. A numeric `duration` fills the end in; STOP counts both the
  first and last day, and so does this skill.
- Month-by-month strips and totals use inclusive event-days.

## Run

```
python3 scripts/outage.py events.csv --title "..." --subtitle "..." \
    --source "Dataset, version, downloaded 2026-06-01" --out events.html

python3 scripts/outage.py events.csv --from 2026-01-01 --to 2026-12-31 --cause shutdown --min-days 2
python3 scripts/outage.py events.csv --lane-by region --snapshot 2026-06-01 --date-format us
```

Filters: `--from`/`--to` (YYYY-MM-DD), `--cause` (repeatable), `--scope` (repeatable),
`--country` (repeatable), `--min-days`. `--lane-by country|region` groups the bars; `--snapshot`
sets the day open-ended events are treated as running to; `--date-format auto|us|eu` reads slash
dates. `--no-basemap` skips the outlines for a fully offline build. The script prints the row
count, the totals, the top countries and any country spellings that had no outline.

The known mechanisms get a label and a colour (`shutdown`, `throttle`, `jamming`, `cable`,
`cyber`, `power`); anything else is kept as written and drawn in the neutral colour. A
`shutdown_type_new` of "Shutdown, Throttle" is treated as a shutdown, because the page cannot
draw both at once; the table keeps the original text.

## A real example

`examples/outage/stop-2020.csv` is derived from the public Access Now #KeepItOn STOP dataset
(2020 file) and credited in the page. It holds 151 reported shutdowns in 2020 across 27
countries, with the mechanism in `cause` and the reported trigger in `trigger`. The adapter that
makes it from the original spreadsheet is `tools/stop_to_outage.py`:

```
python3 tools/stop_to_outage.py STOP-2020.csv --year 2020 --out examples/outage/stop-2020.csv
python3 skills/outage-timeline/scripts/outage.py examples/outage/stop-2020.csv \
    --date-format us --snapshot 2020-12-31 --title "Internet shutdowns in 2020" \
    --source "Access Now #KeepItOn STOP dataset (2020 file), retrieved 2026-11-27" \
    --out examples/outage/stop-2020-timeline.html
```

The India view groups the same rows by area, not country:

```
python3 tools/stop_to_outage.py STOP-2020.csv --year 2020 --country India --out examples/outage/stop-india-2020.csv
python3 skills/outage-timeline/scripts/outage.py examples/outage/stop-india-2020.csv \
    --date-format us --snapshot 2020-12-31 --lane-by region --title "India: reported shutdowns in 2020" \
    --source "Access Now #KeepItOn STOP dataset (2020 file), retrieved 2026-11-27" \
    --out examples/outage/stop-india-2020-timeline.html
```

Download the original file from accessnow.org/keepiton-data, check the terms and methodology
there, and credit Access Now and the #KeepItOn coalition. The derived copy here is a worked
example, not a redistribution endpoint.

## How a reported event is drawn

- One bar is one event. Two events in the same country on the same day draw two bars, and the
  event-day total counts both; the table shows the rows so an overlap is visible.
- A dashed bar means the source gave no end date, or an end of Ongoing or Unknown. Read it as
  "still running when the snapshot was taken", not as a measured duration.
- Mechanism and trigger are separate columns on purpose. A shutdown during an election has the
  mechanism "shutdown" and the trigger "Elections"; the two are counted apart.

## How to report

- Aggregate. "India, 1,319 event-days across 108 reported instances in 2020" is publishable
  when the dataset and window are stated; a named person is not this skill's business.
- Say whether the row is an order, a report or a measurement. A long bar is not a worse
  shutdown by itself.
- Country spellings that do not match the outline set still appear in the tables, not on the
  map. Mention them if the difference changes the picture.
- A gap in the timeline can mean a quiet period or a period nobody recorded. The page says so.

## Limits

- The unit is a reported event, grouped by country or by area. There is no subscriber, device
  or sub-national geometry below the area name.
- Natural Earth 110m outlines are coarse; small states may be missing.
- Event-days are the sum of each event's inclusive day count. Overlapping events on the same
  day are counted twice; the table shows the rows so the overlap is visible.
- The Gantt shows the top lanes by event-days; the table has every row.
- A duration counted from a `duration` field assumes the source counts inclusive days, as STOP
  does. Check other sources.

## Will not do

- Name individuals, subscribers, accounts or devices, or infer who was cut off.
- Present a reported disruption as a measured one, or rank countries for action.
- Produce a target list or a pattern-of-life timeline for a person.

## Data

Your table; its terms are yours to check. The STOP example is public data from Access Now and
the #KeepItOn coalition, credited on every export; check the terms on the file you download.
Natural Earth is public domain and is credited on every export. The page makes no requests.