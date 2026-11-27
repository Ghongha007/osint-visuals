#!/usr/bin/env python3
"""Draw a disruption timeline from your own table: state shutdowns, throttling, jamming, cable
cuts and cyberattacks as bars over time, grouped by country or by area, with a monthly event-day
strip, a country map, a cause and trigger breakdown and the sources on the graphic.

Standard library only. One row per event:

  start,end,country,region,scope,cause,trigger,impact,source,notes
  2020-01-05,2020-01-20,India,Kashmir Valley,regional,shutdown,Political instability,,Access Now STOP 2020,

`start` and `country` are required. `end` defaults to the start day; a missing `end` with an
`Ongoing` or `Unknown` value runs to `--snapshot`, and a `duration` fills it in. Slash dates
carry an explicit `--date-format us|eu` because `03/04/2026` is not readable on its own.

The graphic is aggregate. It shows where and when disruptions were reported, not who was cut
off, and it names no person or individual subscriber.
"""
import argparse
import csv
import html
import json
import math
import os
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "assets", "timeline.html")
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "osint-visuals")
UA = "osint-visuals/0.4 (open-source evidence graphics; https://github.com/Ghongha007/osint-visuals)"
NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"

NAMES = {
    "start": ["start", "start_date", "from", "date", "began", "date_start"],
    "end": ["end", "end_date", "to", "until", "ended", "date_end"],
    "duration": ["duration", "days", "length"],
    "country": ["country", "country_name", "iso", "iso2", "iso3", "code", "nation"],
    "region": ["region", "place", "area", "area_name", "location"],
    "scope": ["scope", "level", "extent", "geo_scope"],
    "cause": ["cause", "mechanism", "type", "category", "shutdown_type", "shutdown_type_new", "event_type"],
    "trigger": ["trigger", "reason", "actual_cause", "justification", "gov_justification"],
    "impact": ["impact", "affected", "population", "severity", "value", "count"],
    "source": ["source", "reference", "report", "url", "source_url", "news_link", "info_source_link"],
    "notes": ["notes", "note", "description", "summary", "event"],
}
CAUSE_LABELS = {
    "shutdown": "Shutdown",
    "throttle": "Throttle",
    "jamming": "Jamming",
    "cable": "Cable cut",
    "cyber": "Cyberattack",
    "power": "Power",
    "unknown": "Unknown",
}
CAUSE_KEYS = ["shutdown", "throttle", "jamming", "cable", "cyber", "power", "unknown"]
SCOPE_MAP = {"level 1": "local", "level 2": "regional", "level 3": "national"}
COUNTRY_ALIASES = {
    "iran (islamic republic of)": "Iran",
    "tanzania, united republic of": "Tanzania",
    "venezuela (bolivarian republic of)": "Venezuela",
    "viet nam": "Vietnam",
    "bolivia (plurinational state of)": "Bolivia",
    "korea, republic of": "South Korea",
    "korea, democratic people's republic of": "North Korea",
    "moldova, republic of": "Moldova",
    "syrian arab republic": "Syria",
    "lao people's democratic republic": "Laos",
    "russian federation": "Russia",
    "czech republic": "Czechia",
    "t\u00fcrkiye": "Turkey",
    "united states of america": "United States of America",
}


def page_json(obj):
    """JSON for a <script> block. '<' is escaped so an input value can never close the tag."""
    return (json.dumps(obj, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))


def pick(header, kind):
    low = {h.strip().lower(): h for h in header}
    for n in NAMES[kind]:
        if n in low:
            return low[n]
    return None


def parse_day(value, date_format="auto"):
    """Return (date, reason). Slash dates need an explicit us or eu when they are ambiguous."""
    v = str(value or "").strip()
    if not v:
        return None, "empty"
    if v.isdigit() and 5 == len(v) and 30000 <= int(v) <= 60000:
        # Spreadsheet exports sometimes leave a date as an Excel serial number (days since 1899-12-30).
        return date(1899, 12, 30) + timedelta(days=int(v)), None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(v[:10], fmt).date(), None
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", v)
    if not m:
        return None, "format"
    a, b, y = (int(x) for x in m.groups())
    if date_format == "us":
        day, month = b, a
    elif date_format == "eu":
        day, month = a, b
    elif a > 12 and b <= 12:
        day, month = a, b
    elif b > 12 and a <= 12:
        day, month = b, a
    else:
        return None, "ambiguous"
    try:
        return date(y, month, day), None
    except ValueError:
        return None, "range"


def cause_key(value):
    v = str(value or "").strip().lower()
    if not v:
        return "unknown"
    if "throttle" in v and "shutdown" in v:
        return "shutdown"
    for key in CAUSE_KEYS:
        if key in v:
            return key
    if "cut" in v or "cable" in v:
        return "cable"
    if "jam" in v or "gps" in v:
        return "jamming"
    if "shut" in v or "blackout" in v:
        return "shutdown"
    if "attack" in v or "ddos" in v:
        return "cyber"
    return "unknown"


def map_scope(value):
    v = str(value or "").strip()
    return SCOPE_MAP.get(v.lower(), v)


def number(value, default=0.0):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def load(path):
    if os.path.splitext(path)[1].lower() == ".json":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("events") or data.get("rows") or data.get("data")
        if not isinstance(data, list):
            sys.exit(f"{path}: expected a list of rows (or an object with events/rows/data)")
        return data
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"{path}: no rows")
    return rows


def parse(rows, lookup, date_format="auto", snapshot=None, lane_by="country"):
    if not rows:
        return [], {}
    snapshot = snapshot or date.today()
    header = list(rows[0].keys())
    cols = {k: pick(header, k) for k in NAMES}
    if not cols["start"] or not cols["country"]:
        sys.exit(f"need start and country columns; found {header}")
    events, unmapped, reasons = [], set(), {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        start, reason = parse_day(row.get(cols["start"]), date_format)
        raw = str(row.get(cols["country"]) or "").strip()
        if not start:
            reasons[reason or "start"] = reasons.get(reason or "start", 0) + 1
            continue
        if not raw:
            reasons["no country"] = reasons.get("no country", 0) + 1
            continue
        end_val = row.get(cols["end"]) if cols["end"] else ""
        end, ereason = parse_day(end_val, date_format)
        open_kind = ""
        if not end:
            dur = number(row.get(cols["duration"])) if cols["duration"] else 0
            label = str(end_val or "").strip().lower()
            if dur > 0:
                end = start + timedelta(days=int(dur) - 1)
                open_kind = "duration"
            elif label in ("", "ongoing", "unknown", "unkown", "not known", "n/a", "na"):
                end = snapshot if snapshot >= start else start
                open_kind = "ongoing" if "ongoing" in label else "unknown"
            else:
                reasons[ereason or "end"] = reasons.get(ereason or "end", 0) + 1
                continue
        if end < start:
            end = start
        name = lookup.get(raw.lower()) or raw
        if lookup and raw.lower() not in lookup:
            unmapped.add(raw)
        region = (str(row.get(cols["region"]) or "").strip() if cols["region"] else "")
        lane = (region or name) if lane_by == "region" else name
        events.append({
            "s": start.isoformat(),
            "e": end.isoformat(),
            "c": name,
            "lane": lane,
            "region": region,
            "scope": map_scope(row.get(cols["scope"]) if cols["scope"] else ""),
            "cause": cause_key(row.get(cols["cause"]) if cols["cause"] else ""),
            "trigger": (str(row.get(cols["trigger"]) or "").strip() if cols["trigger"] else "")[:80],
            "impact": number(row.get(cols["impact"])) if cols["impact"] else 0,
            "src": (str(row.get(cols["source"]) or "").strip() if cols["source"] else "")[:300],
            "note": (str(row.get(cols["notes"]) or "").strip() if cols["notes"] else "")[:300],
            "open": open_kind,
            "days": (end - start).days + 1,
        })
    return events, {"rows": len(rows), "skipped": sum(reasons.values()), "reasons": reasons,
                    "unmapped": sorted(unmapped), "columns": {k: v for k, v in cols.items() if v},
                    "date_format": date_format, "snapshot": snapshot.isoformat(), "lane_by": lane_by}


def country_index(data):
    """Map spellings, ISO codes and sovereign names to the Natural Earth NAME."""
    names, sovereign, codes = {}, {}, {}
    for f in data.get("features", []):
        p = f.get("properties", {})
        name = p.get("NAME") or p.get("ADMIN")
        if not name:
            continue
        for key in ("NAME", "NAME_LONG", "ADMIN", "NAME_SORT"):
            v = p.get(key)
            if v and str(v) not in ("-99", ""):
                names.setdefault(str(v).strip().lower(), name)
        v = p.get("SOVEREIGNT")
        if v and str(v) not in ("-99", ""):
            sovereign.setdefault(str(v).strip().lower(), name)
        owns = p.get("SOVEREIGNT") == name
        for key in ("ISO_A2", "ISO_A3", "ISO_A2_EH"):
            v = p.get(key)
            if v and str(v) not in ("-99", ""):
                k = str(v).strip().lower()
                if k not in codes or owns:
                    codes[k] = name
    lookup = dict(codes)
    lookup.update(sovereign)
    lookup.update(names)
    known = set(names.values())
    for code, name in (("fra", "France"), ("gbr", "United Kingdom"), ("usa", "United States of America"),
                       ("nor", "Norway"), ("swe", "Sweden")):
        if name in known:
            lookup.setdefault(code, name)
    for alias, name in COUNTRY_ALIASES.items():
        if name in known:
            lookup.setdefault(alias, name)
    return lookup


def rings_of(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def simplify(pts, tol):
    if len(pts) < 4:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy) or 1e-12
        best, bi = -1, -1
        for i in range(a + 1, b):
            d = abs(dy * pts[i][0] - dx * pts[i][1] + bx * ay - by * ax) / length
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


def ne_data():
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "ne_110m_admin_0_countries.geojson")
    try:
        if not os.path.exists(path):
            req = urllib.request.Request(NE, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
                f.write(r.read())
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as ex:
        print(f"note: no country outlines ({ex}); the map will be blank and the tables will still be right")
        return None


def view_countries(data, wanted):
    if data is None:
        return [], None
    feats = {}
    for f in data.get("features", []):
        name = f.get("properties", {}).get("NAME")
        if not name:
            continue
        rings = []
        for ring in rings_of(f["geometry"]):
            pts = [[q[0], q[1]] for q in ring[0]]
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts = pts[:-1]
            if len(pts) >= 3:
                rings.append(pts)
        if rings:
            feats[name] = rings
    lons = [p[0] for n in wanted if n in feats for r in feats[n] for p in r]
    lats = [p[1] for n in wanted if n in feats for r in feats[n] for p in r]
    if not wanted or not lons:
        view = [-180, -60, 180, 75]
    else:
        padx = max(2.0, (max(lons) - min(lons)) * 0.25)
        pady = max(2.0, (max(lats) - min(lats)) * 0.25)
        view = [min(lons) - padx, min(lats) - pady, max(lons) + padx, max(lats) + pady]
    tol = max(0.08, min(0.8, (view[2] - view[0]) / 45))
    out = []
    for name, rings in feats.items():
        lons = [p[0] for r in rings for p in r]
        lats = [p[1] for r in rings for p in r]
        if max(lons) < view[0] or min(lons) > view[2] or max(lats) < view[1] or min(lats) > view[3]:
            continue
        polys = []
        for r in rings:
            s = simplify(r, tol)
            if len(s) >= 3:
                polys.append([[round(p[0], 3), round(p[1], 3)] for p in s])
        if polys:
            out.append({"name": name, "polys": polys})
    return out, view


def month_span(start, end):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield cur.strftime("%Y-%m")
        cur = date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("input")
    ap.add_argument("--title", default="Disruption events")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--source", default="", help="where the events came from, shown on the graphic")
    ap.add_argument("--from", dest="since", help="keep events ending on or after this day (YYYY-MM-DD)")
    ap.add_argument("--to", dest="until", help="keep events starting on or before this day (YYYY-MM-DD)")
    ap.add_argument("--cause", action="append", default=[], help="keep only this cause (repeatable)")
    ap.add_argument("--scope", action="append", default=[], help="keep only this scope (repeatable)")
    ap.add_argument("--country", action="append", default=[], help="keep only this country (repeatable)")
    ap.add_argument("--min-days", type=int, default=0, help="drop events shorter than this")
    ap.add_argument("--date-format", choices=["auto", "us", "eu"], default="auto",
                    help="how to read slash dates; auto needs one part above 12")
    ap.add_argument("--snapshot", help="day an Ongoing or Unknown event is treated as running to (YYYY-MM-DD)")
    ap.add_argument("--lane-by", choices=["country", "region"], default="country",
                    help="group the Gantt bars by country or by area name")
    ap.add_argument("--no-basemap", action="store_true", help="skip the Natural Earth outlines")
    ap.add_argument("--theme", choices=["dark", "light"], default="dark")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    snapshot = None
    if a.snapshot:
        snapshot, reason = parse_day(a.snapshot)
        if not snapshot:
            sys.exit(f"--snapshot: not a date ({reason}): {a.snapshot!r}")
    geo = None if a.no_basemap else ne_data()
    lookup = country_index(geo) if geo else {}
    rows = load(a.input)
    events, meta = parse(rows, lookup, a.date_format, snapshot, a.lane_by)
    if a.since:
        events = [e for e in events if e["e"] >= a.since]
    if a.until:
        events = [e for e in events if e["s"] <= a.until]
    if a.cause:
        keep = {cause_key(c) for c in a.cause}
        events = [e for e in events if e["cause"] in keep]
    if a.scope:
        keep = {s.strip().lower() for s in a.scope}
        events = [e for e in events if e["scope"].strip().lower() in keep]
    if a.country:
        keep = {c.strip().lower() for c in a.country}
        events = [e for e in events if e["c"].strip().lower() in keep]
    if a.min_days:
        events = [e for e in events if e["days"] >= a.min_days]
    if not events:
        sys.exit("no events left after filtering; check the dates, country spellings and filters")

    by_country, by_lane, by_cause, by_trigger, by_scope, by_month = {}, {}, {}, {}, {}, {}
    total_days = 0
    for e in events:
        total_days += e["days"]
        c = by_country.setdefault(e["c"], {"name": e["c"], "days": 0, "events": 0})
        c["days"] += e["days"]; c["events"] += 1
        l = by_lane.setdefault(e["lane"], {"name": e["lane"], "days": 0, "events": 0})
        l["days"] += e["days"]; l["events"] += 1
        k = by_cause.setdefault(e["cause"], {"key": e["cause"], "label": CAUSE_LABELS.get(e["cause"], e["cause"]), "days": 0, "events": 0})
        k["days"] += e["days"]; k["events"] += 1
        if e["trigger"]:
            tr = by_trigger.setdefault(e["trigger"], {"name": e["trigger"], "days": 0, "events": 0})
            tr["days"] += e["days"]; tr["events"] += 1
        s = by_scope.setdefault(e["scope"] or "Not stated", {"name": e["scope"] or "Not stated", "days": 0, "events": 0})
        s["days"] += e["days"]; s["events"] += 1
        for m in month_span(date.fromisoformat(e["s"]), date.fromisoformat(e["e"])):
            by_month.setdefault(m, {"month": m, "days": 0, "events": 0})["events"] += 1
        start = date.fromisoformat(e["s"])
        for i in range(e["days"]):
            d = (start + timedelta(days=i)).strftime("%Y-%m")
            by_month[d]["days"] += 1

    start_all = min(date.fromisoformat(e["s"]) for e in events)
    end_all = max(date.fromisoformat(e["e"]) for e in events)
    months = [by_month.get(m, {"month": m, "days": 0, "events": 0}) for m in month_span(start_all, end_all)]
    countries, view = ([], None) if a.no_basemap else view_countries(geo, set(by_country))
    data = {
        "title": a.title, "subtitle": a.subtitle, "source": a.source, "theme": a.theme,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "input": os.path.basename(a.input), "events": events,
        "total_events": len(events), "total_days": total_days,
        "lane_by": a.lane_by,
        "lanes": sorted(by_lane.values(), key=lambda x: -x["days"]),
        "countries": sorted(by_country.values(), key=lambda x: -x["days"]),
        "causes": sorted(by_cause.values(), key=lambda x: -x["days"]),
        "triggers": sorted(by_trigger.values(), key=lambda x: -x["days"]),
        "scopes": sorted(by_scope.values(), key=lambda x: -x["days"]),
        "months": months, "basemap": countries, "view": view,
        "range": [start_all.isoformat(), end_all.isoformat()],
        "unmapped": meta["unmapped"], "meta": meta,
    }
    with open(TEMPLATE, encoding="utf-8") as tf:
        page = tf.read()
    page = page.replace("/*__DATA__*/null", page_json(data)).replace("__TITLE__", html.escape(a.title))
    dest = a.out or os.path.splitext(a.input)[0] + "-timeline.html"
    with open(dest, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"wrote {dest} ({os.path.getsize(dest) // 1024} KB)")
    print(f"  {meta['rows']} rows, {len(events)} events, {total_days} event-days, "
          f"{len(by_country)} countries, {len(by_cause)} causes, {len(months)} months")
    print(f"  dates: {meta['date_format']}, open events to {meta['snapshot']}, lanes by {meta['lane_by']}")
    for c in data["countries"][:6]:
        print(f"    {c['name']}: {c['days']} days / {c['events']} events")
    if meta["reasons"]:
        print("  skipped: " + ", ".join(f"{k} {v}" for k, v in sorted(meta["reasons"].items())))
    if meta["unmapped"]:
        print("  country spellings not in the outline set (shown in the tables, not on the map): " +
              ", ".join(meta["unmapped"][:6]))
    if not a.source:
        print("note: no --source given; say where the events came from")
    print("  note: a reported disruption is not a measured one. Say what the source counts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())