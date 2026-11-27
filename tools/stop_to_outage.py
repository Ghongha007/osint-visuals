#!/usr/bin/env python3
"""Convert an Access Now #KeepItOn STOP shutdown table into outage-timeline input.

The STOP CSV has a note line before the header and US-format dates (M/D/YYYY). This keeps
only the event columns the skill reads, adds the trigger (actual_cause) and the mechanism
(shutdown_type_new), and credits Access Now in the source column.

Usage:
  python3 tools/stop_to_outage.py STOP-2020.csv --year 2020 --out examples/outage/stop-2020.csv
  python3 tools/stop_to_outage.py STOP-2020.csv --year 2020 --country India --out examples/outage/stop-india-2020.csv

The STOP data is public; cite Access Now and its methodology when you publish a graphic.
"""
import argparse
import csv
import re
import sys

FIELDS = ["start", "end", "duration", "country", "region", "scope", "cause", "trigger", "source", "notes"]


def find_header(lines):
    for i, line in enumerate(lines):
        if line.lstrip('"').startswith("ID,"):
            return i
    return None


def first_url(value):
    if not value:
        return ""
    urls = re.findall(r"https?://[^\s,;\"']+", value)
    return urls[0][:200] if urls else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("input")
    ap.add_argument("--year", type=int, default=None, help="keep rows whose start date is in this year")
    ap.add_argument("--country", default=None, help="keep this country only (case-insensitive substring)")
    ap.add_argument("--source", default="Access Now #KeepItOn STOP dataset", help="fallback source label")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    with open(a.input, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    i = find_header(lines)
    if i is None:
        sys.exit("no header line starting with ID,")
    rows = list(csv.DictReader(lines[i:]))
    out, kept = [], 0
    for r in rows:
        start = (r.get("start_date") or "").strip()
        year = start.split("/")[-1] if "/" in start else start[:4]
        if a.year and year != str(a.year):
            continue
        country = (r.get("country ") or r.get("country") or "").strip()
        if a.country and a.country.lower() not in country.lower():
            continue
        note = (r.get("event ") or r.get("event") or "").strip() or (r.get("notes") or "").strip()
        out.append({
            "start": start,
            "end": (r.get("end_date ") or r.get("end_date") or "").strip(),
            "duration": (r.get("duration") or "").strip(),
            "country": country,
            "region": (r.get("area_name ") or r.get("area_name") or "").strip(),
            "scope": (r.get("geo_scope") or "").strip(),
            "cause": (r.get("shutdown_type_new") or "").strip(),
            "trigger": (r.get("actual_cause") or "").strip(),
            "source": first_url(r.get("news_link ") or r.get("news_link")) or a.source,
            "notes": note[:200],
        })
        kept += 1

    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    print(f"wrote {a.out}: {kept} of {len(rows)} rows" + (f" for {a.year}" if a.year else ""))
    if kept:
        print(f"  first: {out[0]['start']} {out[0]['country']} {out[0]['cause']} / {out[0]['trigger']}")


if __name__ == "__main__":
    main()