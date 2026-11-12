from datetime import datetime
from zoneinfo import ZoneInfo
from app.brain import parse_when, route_rules, strip_when

NOW = datetime(2026, 11, 8, 10, 0, tzinfo=ZoneInfo("Europe/London"))  # a Sunday


def at(s, tz="Europe/London"):
    return parse_when(s, tz, NOW)


def test_tomorrow_6pm():
    assert at("remind me to call mum tomorrow at 6pm") == datetime(2026, 11, 9, 18, 0, tzinfo=ZoneInfo("Europe/London"))


def test_relative():
    assert at("remind me in 2 hours to stretch") == datetime(2026, 11, 8, 12, 0, tzinfo=ZoneInfo("Europe/London"))
    assert at("in 30 minutes check the oven").minute == 30


def test_weekday_and_date():
    assert at("remind me on friday at 17:30").date().isoformat() == "2026-11-13"
    d = at("remind me on 14 nov at 7pm")
    assert (d.month, d.day, d.hour) == (11, 14, 19)
    assert at("remind me 3 jan to renew").year == 2027


def test_time_only_rolls_forward():
    assert at("remind me at 9am to stand up").date().isoformat() == "2026-11-09"


def test_timezones():
    assert at("tomorrow at 9", "Asia/Kolkata").utcoffset().total_seconds() == 19800


def test_strip_when():
    assert strip_when("remind me to call mum tomorrow at 6pm") == "call mum"


def test_router():
    assert route_rules("add milk, eggs and bread to shopping list") == {"intent": "list_add", "list_name": "shopping", "list_entries": ["milk", "eggs", "bread"]}
    assert route_rules("show my shopping list")["intent"] == "list_show"
    o = route_rules("Sofia's birthday is 12 March")
    assert (o["intent"], o["person"], o["month"], o["day"]) == ("occasion", "Sofia", 3, 12)
    assert route_rules("what was that pasta place?")["intent"] == "ask"
    assert route_rules("https://www.instagram.com/reel/abc pasta place")["collection"] == "Reels"
    assert route_rules("idea: a podcast about corner shops")["intent"] == "save"
