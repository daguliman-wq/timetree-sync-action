import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import Config
from models import Event
from sync import _is_managed_google_event, _label_id, _label_targets, reconcile


def event(source_id="1", title="Sample"):
    dt = datetime(2026, 10, 2, tzinfo=ZoneInfo("Asia/Seoul"))
    return Event(source_id, title, dt, dt, True)


def copy(source_id="1", google_id="g1", code="source", title="Sample"):
    return {"id": google_id, **event(source_id, title).to_google(code)}


class FakeGoogle:
    def __init__(self, calendars, fail_target=None):
        self.calendars = calendars
        self.calls = []
        self.fail_target = fail_target

    def list_events(self, target):
        return self.calendars.get(target, [])

    def create_event(self, target, body):
        self.calls.append(("create", target))
        if target == self.fail_target:
            raise RuntimeError("simulated failure")
        return {"id": "new", **body}

    def update_event(self, target, google_id, body):
        self.calls.append(("update", target))
        if target == self.fail_target:
            raise RuntimeError("simulated failure")

    def delete_event(self, target, google_id):
        self.calls.append(("delete", target, google_id))


class LabelSyncTests(unittest.TestCase):
    def test_label_selection(self):
        self.assertEqual(_label_id({"label_id": 3}), "3")
        self.assertEqual(_label_id({"relationships": {"label": {"data": {"id": "4"}}}}), "4")
        self.assertEqual(_label_id({"relationships": {"label": {"data": {"id": "calendar,4"}}}}), "4")
        self.assertIsNone(_label_id({}))
        self.assertEqual(_label_targets({3: {"name": " 희돈  일정 "}}, {"희돈 일정": "a"}), {"3": "a"})
        with self.assertRaises(RuntimeError):
            _label_targets({}, {"희돈 일정": "a"})
        with self.assertRaises(RuntimeError):
            _label_targets({1: {"name": "x"}, 2: {"name": "x"}}, {"x": "a"})

    def test_config_rejects_invalid_map(self):
        for raw in ['[]', '{}', '{"x": "a", "y": "a"}', '{"x": "legacy"}', 'bad']:
            with patch.object(Config, "GOOGLE_CALENDAR_MAP_JSON", raw), patch.object(Config, "GOOGLE_CALENDAR_ID", "legacy"):
                with self.assertRaises(RuntimeError):
                    Config.calendar_map()

    def test_strict_ownership(self):
        self.assertTrue(_is_managed_google_event(copy(), "source"))
        self.assertFalse(_is_managed_google_event(copy(code="other"), "source"))
        self.assertFalse(_is_managed_google_event({"extendedProperties": {"private": {"timetree_id": "1"}}}, "source"))

    def test_failure_never_deletes(self):
        google = FakeGoogle({"legacy": [copy()], "a": [copy(title="Old")], "b": []}, "b")
        with self.assertRaises(RuntimeError):
            reconcile(google, {"a": [event()], "b": [event("2")]}, "source", "legacy", cleanup=True)
        self.assertEqual(google.calls, [("update", "a"), ("create", "b")])

    def test_cleanup_default_off(self):
        google = FakeGoogle({"legacy": [copy()], "a": [copy("excluded")]})
        reconcile(google, {"a": [event()]}, "source", "legacy")
        self.assertEqual(google.calls, [("create", "a")])

    def test_migration_label_change_exclusion_and_unmanaged(self):
        google = FakeGoogle({
            "legacy": [copy(), {"id": "native"}, copy(code="other", google_id="foreign")],
            "a": [copy("moved", "old-label"), copy("excluded", "excluded")],
            "b": [copy("1", "keep"), copy("1", "duplicate")],
        })
        reconcile(google, {"a": [], "b": [event(), event("moved")]}, "source", "legacy", cleanup=True)
        self.assertEqual(google.calls[0], ("create", "b"))
        self.assertEqual(set(google.calls[1:]), {
            ("delete", "legacy", "g1"), ("delete", "a", "old-label"),
            ("delete", "a", "excluded"), ("delete", "b", "duplicate"),
        })

    def test_inclusive_all_day_end_unchanged(self):
        body = event().to_google("source")
        self.assertEqual(body["start"]["date"], "2026-10-02")
        self.assertEqual(body["end"]["date"], "2026-10-03")


if __name__ == "__main__":
    unittest.main()
