"""Offline tests for the outage timeline. The demo events are invented; the outlines are synthetic."""
import csv
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "tests", "fixtures", "demo-outages.csv")

GEO = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"NAME": "France", "ISO_A2": "-99", "ISO_A3": "-99", "ISO_A2_EH": "FR",
                                       "SOVEREIGNT": "France"},
     "geometry": {"type": "Polygon", "coordinates": [[[0, 42], [8, 42], [8, 50], [0, 50], [0, 42]]]}},
    {"type": "Feature", "properties": {"NAME": "Fr. S. Antarctic Lands", "ISO_A2": "FR", "ISO_A3": "ATF",
                                       "SOVEREIGNT": "France"},
     "geometry": {"type": "Polygon", "coordinates": [[[60, -50], [70, -50], [70, -40], [60, -40], [60, -50]]]}},
    {"type": "Feature", "properties": {"NAME": "Antarctica", "ISO_A2": "AQ", "ISO_A3": "ATA",
                                       "SOVEREIGNT": "Antarctica"},
     "geometry": {"type": "Polygon", "coordinates": [[[0, -80], [10, -80], [10, -70], [0, -70], [0, -80]]]}},
    {"type": "Feature", "properties": {"NAME": "Iran", "ISO_A2": "IR", "ISO_A3": "IRN",
                                       "SOVEREIGNT": "Iran"},
     "geometry": {"type": "Polygon", "coordinates": [[[44, 25], [63, 25], [63, 40], [44, 40], [44, 25]]]}},
]}


def load(rel, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


outage = load("skills/outage-timeline/scripts/outage.py", "outage")
adapter = load("tools/stop_to_outage.py", "stop_to_outage")

STOP_ROWS = (
    '"Counts include the start and end date.",,,,,,,,,,\n'
    "ID,start_date,end_date ,duration,country ,geo_scope,area_name ,shutdown_type_new,"
    "actual_cause,event ,news_link\n"
    '1,6/12/2016,Ongoing,,Pakistan,Level 2,Federally Administered Tribal Area,Shutdown,'
    'Protests,Curfew after protest,https://example.org/a\n'
    '2,6/13/2016,6/15/2016,3,India,Level 3,,Throttle,Elections,Vote count,https://example.org/b\n'
)


def write_stop(directory):
    path = os.path.join(directory, "stop.csv")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(STOP_ROWS)
    return path


def page_data(path):
    with open(path, encoding="utf-8") as f:
        s = f.read()
    i = s.index("const D = ") + len("const D = ")
    return json.JSONDecoder().raw_decode(s[i:])[0]


class Dates(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(outage.parse_day("2026-02-03"), (date(2026, 2, 3), None))
        self.assertEqual(outage.parse_day("2026/02/03"), (date(2026, 2, 3), None))

    def test_us_eu_auto(self):
        self.assertEqual(outage.parse_day("6/13/2016", "us"), (date(2016, 6, 13), None))
        self.assertEqual(outage.parse_day("13/6/2016", "eu"), (date(2016, 6, 13), None))
        self.assertEqual(outage.parse_day("6/13/2016"), (date(2016, 6, 13), None))   # second part > 12
        self.assertEqual(outage.parse_day("13/6/2016"), (date(2016, 6, 13), None))   # first part > 12
        self.assertEqual(outage.parse_day("03/04/2026"), (None, "ambiguous"))

    def test_bad(self):
        self.assertEqual(outage.parse_day("nope"), (None, "format"))
        self.assertEqual(outage.parse_day(""), (None, "empty"))
        self.assertEqual(outage.parse_day("2026-13-40"), (None, "format"))

    def test_excel_serial(self):
        self.assertEqual(outage.parse_day("44166"), (date(2020, 12, 1), None))
        self.assertEqual(outage.parse_day("2020"), (None, "format"))   # a year is not a serial


class OpenEnds(unittest.TestCase):
    def test_ongoing_unknown_and_duration(self):
        rows = [
            {"start": "2020-01-01", "end": "2020-01-05", "country": "India", "duration": "", "cause": "Shutdown", "trigger": "Protests"},
            {"start": "2020-02-01", "end": "Ongoing", "country": "India", "duration": "", "cause": "Throttle", "trigger": "Elections"},
            {"start": "2020-03-01", "end": "", "country": "India", "duration": "10", "cause": "Shutdown", "trigger": ""},
            {"start": "2020-04-01", "end": "Unknown", "country": "India", "duration": "", "cause": "Shutdown", "trigger": ""},
            {"start": "2020-05-01", "end": "Unkown ", "country": "India", "duration": "", "cause": "Shutdown", "trigger": ""},
        ]
        events, meta = outage.parse(rows, {}, snapshot=date(2020, 12, 31))
        self.assertEqual(len(events), 5)
        self.assertEqual(events[0]["days"], 5)
        self.assertEqual(events[0]["open"], "")
        self.assertEqual(events[1]["e"], "2020-12-31")
        self.assertEqual(events[1]["open"], "ongoing")
        self.assertEqual(events[2]["e"], "2020-03-10")
        self.assertEqual(events[2]["open"], "duration")
        self.assertEqual(events[3]["open"], "unknown")
        self.assertEqual(events[4]["open"], "unknown")
        self.assertEqual(meta["reasons"], {})

    def test_scope_and_mechanism(self):
        self.assertEqual(outage.map_scope("Level 1"), "local")
        self.assertEqual(outage.map_scope("Level 2"), "regional")
        self.assertEqual(outage.map_scope("Level 3"), "national")
        self.assertEqual(outage.cause_key("Shutdown, Throttle"), "shutdown")
        self.assertEqual(outage.cause_key("Throttle"), "throttle")
        self.assertEqual(outage.cause_key("fibre cut"), "cable")


class Parse(unittest.TestCase):
    def setUp(self):
        self.events, self.meta = outage.parse(outage.load(DEMO), outage.country_index(GEO))

    def test_totals(self):
        self.assertEqual(self.meta["rows"], 18)
        self.assertEqual(len(self.events), 18)
        self.assertEqual(sum(e["days"] for e in self.events), 49)
        self.assertEqual(self.events[0]["lane"], self.events[0]["c"])

    def test_day_defaults(self):
        e = next(x for x in self.events if x["s"] == "2026-01-20")
        self.assertEqual(e["e"], e["s"])
        self.assertEqual(e["cause"], "jamming")
        self.assertEqual(e["days"], 1)


class Countries(unittest.TestCase):
    def test_codes_and_dependencies(self):
        idx = outage.country_index(GEO)
        self.assertEqual(idx["fr"], "France")
        self.assertEqual(idx["france"], "France")
        self.assertEqual(idx["aq"], "Antarctica")
        self.assertEqual(idx["fr. s. antarctic lands"], "Fr. S. Antarctic Lands")

    def test_long_form_aliases(self):
        idx = outage.country_index(GEO)
        self.assertEqual(idx["iran (islamic republic of)"], "Iran")


class StopAdapter(unittest.TestCase):
    def test_converts_header_note_and_trailing_spaces(self):
        with tempfile.TemporaryDirectory() as d:
            src = write_stop(d)
            dest = os.path.join(d, "out.csv")
            with mock.patch.object(sys, "argv", ["stop_to_outage.py", src, "--year", "2016", "--out", dest]):
                adapter.main()
            with open(dest, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["start"], "6/12/2016")
            self.assertEqual(rows[0]["end"], "Ongoing")
            self.assertEqual(rows[0]["country"], "Pakistan")
            self.assertEqual(rows[0]["cause"], "Shutdown")
            self.assertEqual(rows[0]["trigger"], "Protests")
            self.assertEqual(rows[0]["notes"], "Curfew after protest")
            self.assertEqual(rows[0]["source"], "https://example.org/a")
            self.assertEqual(rows[1]["duration"], "3")

    def test_year_filter(self):
        with tempfile.TemporaryDirectory() as d:
            src = write_stop(d)
            dest = os.path.join(d, "out.csv")
            with mock.patch.object(sys, "argv", ["stop_to_outage.py", src, "--year", "2017", "--out", dest]):
                adapter.main()
            with open(dest, newline="", encoding="utf-8") as f:
                self.assertEqual(list(csv.DictReader(f)), [])


class Page(unittest.TestCase):
    def test_page_without_basemap(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "o.html")
            outage.main([DEMO, "--title", "T", "--source", "S", "--no-basemap", "--out", dest])
            data = page_data(dest)
            self.assertEqual(data["total_events"], 18)
            self.assertEqual(data["total_days"], 49)
            self.assertEqual(data["basemap"], [])
            self.assertEqual(data["range"], ["2026-01-12", "2026-07-02"])

    def test_lane_by_region(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "o.html")
            outage.main([DEMO, "--lane-by", "region", "--no-basemap", "--out", dest])
            data = page_data(dest)
            self.assertEqual(data["lane_by"], "region")
            self.assertTrue(all(e["lane"] == (e["region"] or e["c"]) for e in data["events"]))

    def test_cause_filter(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "o.html")
            outage.main([DEMO, "--cause", "shutdown", "--no-basemap", "--out", dest])
            data = page_data(dest)
            self.assertTrue(all(e["cause"] == "shutdown" for e in data["events"]))
            self.assertLess(data["total_events"], 18)

    def test_country_filter(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "o.html")
            outage.main([DEMO, "--country", "Germany", "--no-basemap", "--out", dest])
            data = page_data(dest)
            self.assertTrue(all(e["c"] == "Germany" for e in data["events"]))
            self.assertEqual(data["total_events"], 2)

    def test_empty_after_filter(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(SystemExit):
                outage.main([DEMO, "--cause", "nowhere", "--no-basemap", "--out", os.path.join(d, "o.html")])

    def test_input_cannot_close_the_script(self):
        with tempfile.TemporaryDirectory() as d:
            src, dest = os.path.join(d, "e.csv"), os.path.join(d, "o.html")
            with open(src, "w") as f:
                f.write('start,end,country,notes\n2026-01-01,,"</script><b>PROOF</b>","</script><b>PROOF</b>"\n')
            outage.main([src, "--no-basemap", "--out", dest])
            with open(dest, encoding="utf-8") as f:
                s = f.read()
            self.assertNotIn("<b>PROOF</b>", s)
            self.assertIn("\\u003c/script", s)


if __name__ == "__main__":
    unittest.main()