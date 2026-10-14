"""Unit tests for the 380nm platform API client."""

from __future__ import annotations

import sys
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

import asyncio
import unittest

import httpx

import platform_client


class PlatformClientTests(unittest.TestCase):
    def test_login_reads_session_cookie_and_me(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/auth/login"):
                return httpx.Response(
                    200,
                    headers={"set-cookie": "sid=abc; Path=/; HttpOnly"},
                    json={"user": {"id": "u1", "username": "alice", "role": "user"}},
                )
            if request.url.path.endswith("/auth/me"):
                return httpx.Response(200, json={"user": {"id": "u1"}})
            return httpx.Response(404)

        client = platform_client.BiliPlatformClient(
            "https://bilidyn.basmc.org/release",
            transport=httpx.MockTransport(handler),
        )
        result = asyncio.run(client.login("alice", "pw"))
        self.assertEqual(result["sid"], "abc")
        self.assertEqual(asyncio.run(client.me())["id"], "u1")

    def test_upload_and_create_job(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/upload"):
                seen["upload"] = request.content
                return httpx.Response(200, json={"images": [{"key": "img1", "name": "a.jpg", "url": "u"}]})
            if request.url.path.endswith("/templates"):
                return httpx.Response(200, json={"templates": [{"id": "tpl1", "name": "AstrBot 直发"}]})
            if request.url.path.endswith("/jobs"):
                seen["job"] = request.content.decode("utf-8")
                return httpx.Response(200, json={"job": {"id": "job1", "status": "pending"}})
            return httpx.Response(404)

        client = platform_client.BiliPlatformClient(
            "https://bilidyn.basmc.org", sid="sid", transport=httpx.MockTransport(handler)
        )
        uploaded = asyncio.run(client.upload_images([{
            "filename": "a.jpg", "data": b"image", "content_type": "image/jpeg"
        }]))
        self.assertEqual(uploaded[0]["key"], "img1")
        job = asyncio.run(client.create_job(
            template_id="tpl1", account_id="acc1", variables={"text": "hello"},
            images=uploaded, scheduled_at=None,
        ))
        self.assertEqual(job["id"], "job1")
        import json as _json
        self.assertEqual(_json.loads(seen["job"])["templateId"], "tpl1")

    def test_401_marks_session_expired(self):
        def handler(request):
            return httpx.Response(401, json={"error": "未登录"})
        client = platform_client.BiliPlatformClient(
            "https://bilidyn.basmc.org", sid="bad",
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(platform_client.PlatformAPIError) as ctx:
            asyncio.run(client.list_jobs())
        self.assertEqual(ctx.exception.status_code, 401)

    def test_import_library_link(self):
        def handler(request):
            if request.url.path.endswith("/library/import"):
                return httpx.Response(200, json={"images": [{"key": "img1", "name": "a.jpg", "url": "u"}], "total": 1})
            return httpx.Response(404)
        client = platform_client.BiliPlatformClient(
            "https://bilidyn.basmc.org", sid="sid",
            transport=httpx.MockTransport(handler),
        )
        result = asyncio.run(client.import_library_link("https://x.com/a/status/1"))
        self.assertEqual(result["images"][0]["key"], "img1")
        self.assertEqual(result["total"], 1)

    def test_topic_and_mention_search(self):
        def handler(request):
            if request.url.path.endswith("/topics/search"):
                return httpx.Response(200, json={"topics": [{"id": "1", "name": "t"}]})
            if request.url.path.endswith("/mentions/search"):
                return httpx.Response(200, json={"users": [{"uid": "2", "name": "u"}]})
            return httpx.Response(404)
        client = platform_client.BiliPlatformClient(
            "https://bilidyn.basmc.org", sid="sid",
            transport=httpx.MockTransport(handler),
        )
        self.assertEqual(asyncio.run(client.search_topics("t"))[0]["id"], "1")
        self.assertEqual(asyncio.run(client.search_mentions("u"))[0]["uid"], "2")

    def test_normalize_sid_accepts_common_paste_shapes(self):
        cases = {
            "abc123": "abc123",
            "sid=abc123": "abc123",
            "sid=abc123;": "abc123",
            '"abc123"': "abc123",
            "  abc123  ": "abc123",
            "SID=abc123": "abc123",
            "foo=1; sid=abc123; bar=2": "abc123",
            "": "",
        }
        for raw, expected in cases.items():
            self.assertEqual(
                platform_client.normalize_sid(raw), expected, repr(raw)
            )

    def test_client_normalises_sid(self):
        client = platform_client.BiliPlatformClient(
            "https://bilidyn.basmc.org", sid="sid=abc123"
        )
        self.assertEqual(client.sid, "abc123")

    def test_normalize_ui_url_to_origin(self):
        self.assertEqual(
            platform_client.normalize_platform_url("https://bilidyn.basmc.org/release"),
            "https://bilidyn.basmc.org",
        )


if __name__ == "__main__":
    unittest.main()