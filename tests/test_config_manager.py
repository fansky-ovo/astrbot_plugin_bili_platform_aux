"""Unit tests for auxiliary session storage."""

from __future__ import annotations

import sys
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

import tempfile
import unittest

import config_manager


class AuxConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config_manager.AuxConfigManager(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_session_round_trip_and_pending_images(self):
        self.cfg.save_session(
            "u1", platform_url="https://bilidyn.basmc.org",
            username="alice", sid="sid", user={"id": "u1"},
        )
        session = self.cfg.load_session("u1")
        self.assertEqual(session["sid"], "sid")
        self.cfg.set_pending_images("u1", [{"key": "img1"}])
        self.assertEqual(self.cfg.pop_pending_images("u1"), [{"key": "img1"}])
        self.assertEqual(self.cfg.pop_pending_images("u1"), [])

    def test_preset_crud_and_active(self):
        self.cfg.set_preset("u1", "daily", {"template_id": "tpl1", "account_id": "acc1"})
        self.assertEqual(self.cfg.list_presets("u1")["daily"]["template_id"], "tpl1")
        self.cfg.set_active_preset("u1", "daily")
        name, config = self.cfg.get_active_preset("u1")
        self.assertEqual(name, "daily")
        self.assertEqual(config["account_id"], "acc1")
        self.cfg.remove_preset("u1", "daily")
        self.assertEqual(self.cfg.list_presets("u1"), {})
        self.assertEqual(self.cfg.get_active_preset("u1")[0], "")

    def test_draft_round_trip(self):
        self.cfg.update_draft("u1", text="hello", topic_name="t")
        self.assertEqual(self.cfg.get_draft("u1")["text"], "hello")
        self.cfg.clear_draft("u1")
        self.assertEqual(self.cfg.get_draft("u1"), {})

    def test_clear_session(self):
        self.cfg.save_session(
            "u1", platform_url="https://bilidyn.basmc.org",
            username="alice", sid="sid",
        )
        self.cfg.clear_session("u1")
        self.assertIsNone(self.cfg.load_session("u1"))


if __name__ == "__main__":
    unittest.main()