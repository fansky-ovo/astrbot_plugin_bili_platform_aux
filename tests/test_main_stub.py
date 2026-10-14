"""Entry tests with minimal AstrBot stubs."""

from __future__ import annotations

import asyncio
import httpx
import importlib
import json
import os
import re
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

_PLUGIN_DIR = Path(__file__).resolve().parents[1]
_PARENT = _PLUGIN_DIR.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))


def _install_stubs() -> None:
    class Star:
        pass
    class Context:
        pass
    class MessageType:
        GROUP_MESSAGE = "group"
        PRIVATE_MESSAGE = "private"
    class AstrMessageEvent:
        pass
    class MessageChain:
        def __init__(self, chain=None):
            self.chain = list(chain or [])

        def file_image(self, path):
            self.chain.append(path)
            return self

    class Plain:
        def __init__(self, text=""):
            self.text = text
    def decorator(*_args, **_kwargs):
        def wrap(func):
            return func
        return wrap
    filter_mod = types.ModuleType("astrbot.api.event.filter")
    filter_mod.command = decorator
    filter_mod.llm_tool = decorator
    filter_mod.regex = decorator
    event_mod = types.ModuleType("astrbot.api.event")
    event_mod.AstrMessageEvent = AstrMessageEvent
    event_mod.MessageChain = MessageChain
    event_mod.filter = filter_mod
    logger_mod = types.ModuleType("astrbot.api.logger")
    for name in ("debug", "info", "warning", "error", "exception"):
        setattr(logger_mod, name, lambda *_args, **_kwargs: None)
    api_mod = types.ModuleType("astrbot.api")
    api_mod.star = types.SimpleNamespace(Star=Star, Context=Context)
    api_mod.logger = logger_mod
    components_mod = types.ModuleType("astrbot.api.message_components")
    components_mod.Plain = Plain
    platform_mod = types.ModuleType("astrbot.core.platform")
    platform_mod.__path__ = []
    message_type_mod = types.ModuleType("astrbot.core.platform.message_type")
    message_type_mod.MessageType = MessageType
    astrbot_mod = types.ModuleType("astrbot")
    astrbot_mod.__path__ = []
    sys.modules.update({
        "astrbot": astrbot_mod,
        "astrbot.api": api_mod,
        "astrbot.api.event": event_mod,
        "astrbot.api.event.filter": filter_mod,
        "astrbot.api.logger": logger_mod,
        "astrbot.api.message_components": components_mod,
        "astrbot.core": types.ModuleType("astrbot.core"),
        "astrbot.core.platform": platform_mod,
        "astrbot.core.platform.message_type": message_type_mod,
    })


_install_stubs()
_PLUGIN = importlib.import_module(f"{_PLUGIN_DIR.name}.main")


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ, {"BILI_PLATFORM_AUX_DATA_DIR": self.tmp.name}
        )
        self.env.start()
        self.plugin = _PLUGIN.BiliPlatformAuxPlugin(context=object())

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_preset_prefix_and_env_defaults(self):
        self.assertEqual(
            self.plugin._extract_preset_prefix("preset:daily hello"),
            ("daily", "hello"),
        )
        with patch.dict(
            os.environ,
            {
                "BILI_PLATFORM_ACCOUNT_ID": "acc1",
                "BILI_PLATFORM_TEMPLATE_ID": "tpl1",
                "BILI_PLATFORM_TITLE": "title",
                "BILI_PLATFORM_VARIABLES_JSON": '{"extra":"x"}',
            },
            clear=False,
        ):
            defaults = self.plugin._env_publish_defaults()
        self.assertEqual(defaults["account_id"], "acc1")
        self.assertEqual(defaults["template_id"], "tpl1")
        self.assertEqual(defaults["variables"]["extra"], "x")

    def test_preview_reports_missing_variables(self):
        text = self.plugin._preview_text({
            "preset_name": "p", "account_id": "a", "template_name": "t",
            "template_id": "id", "title": "", "topic_name": "",
            "mentions": [], "image_keys": [], "schedule": "",
            "variables": {"text": "hello"}, "missing_variables": ["extra"],
            "template_content": "{{text}} {{extra}}",
        })
        self.assertIn("缺少变量", text)

    def test_image_merge_and_job_detail(self):
        merged = self.plugin._merge_plan_images(
            [{"key": "a"}, {"key": "b"}], [{"key": "b"}, {"key": "c"}]
        )
        self.assertEqual([item["key"] for item in merged], ["a", "b", "c"])
        detail = self.plugin._job_detail_text(
            {"id": "j1", "status": "pending", "images": [], "mentions": []}
        )
        self.assertIn("j1", detail)

    def test_image_draft_order(self):
        class Event:
            def get_sender_id(self):
                return "u1"
        event = Event()
        self.plugin.config.update_draft(
            "u1",
            image_keys=[{"key": "a"}, {"key": "b"}],
        )
        result = self.plugin._image_command(event, "order b,a")
        self.assertIn("顺序已更新", result)
        self.assertEqual(
            [item["key"] for item in self.plugin.config.get_draft("u1")["image_keys"]],
            ["b", "a"],
        )

    def test_schedule_parser(self):
        self.assertEqual(self.plugin._parse_schedule("+30m", now=1000), 2800)

    def test_platform_url_allowlist(self):
        self.assertEqual(
            self.plugin._validate_platform_url("https://bilidyn.basmc.org/release"),
            "https://bilidyn.basmc.org",
        )
        with self.assertRaises(ValueError):
            self.plugin._validate_platform_url("http://evil.example")
        with self.assertRaises(ValueError):
            self.plugin._validate_platform_url("https://evil.example")

    def test_platform_url_normalization(self):
        self.assertEqual(
            _PLUGIN.normalize_platform_url("https://bilidyn.basmc.org/release"),
            "https://bilidyn.basmc.org",
        )


class LLMToolDocstringTests(unittest.TestCase):
    """AstrBot rejects plugin loads when a tool docstring uses a bad type."""

    ALLOWED = {
        "string",
        "number",
        "object",
        "array",
        "boolean",
        "str",
        "int",
        "float",
        "bool",
        "dict",
        "list",
        "tuple",
        "set",
    }

    def test_docstring_argument_types_are_supported(self):
        pattern = re.compile(r"^\s*(\w+)\(([^)]*)\):", re.M)
        checked = 0
        for name in dir(_PLUGIN.BiliPlatformAuxPlugin):
            if not name.startswith("llm_"):
                continue
            func = getattr(_PLUGIN.BiliPlatformAuxPlugin, name)
            doc = getattr(func, "__doc__", None) or ""
            if "Args:" not in doc:
                continue
            for arg_name, type_name in pattern.findall(doc):
                matched = False
                for raw in type_name.split("|"):
                    raw = raw.strip()
                    if not raw:
                        continue
                    matched = True
                    checked += 1
                    head = re.match(r"(\w+)(?:\[(\w+)\])?", raw)
                    self.assertIsNotNone(
                        head, f"{name}.{arg_name} 类型无法解析: {raw}"
                    )
                    for token in head.groups():
                        if token:
                            self.assertIn(
                                token,
                                self.ALLOWED,
                                f"{name}.{arg_name} 使用了 AstrBot 不支持的类型: {raw}",
                            )
                self.assertTrue(matched, f"{name}.{arg_name} 缺少类型注释")
        self.assertGreater(checked, 15)


class _FakeEvent:
    """Minimal AstrMessageEvent stand-in."""

    def __init__(self, sender_id="u1", message_type="private", admin=False):
        self._sender_id = sender_id
        self._message_type = message_type
        self._admin = admin
        self.unified_msg_origin = f"test:{message_type}:{sender_id}"
        self.message_obj = None

    def get_sender_id(self):
        return self._sender_id

    def get_message_type(self):
        return self._message_type

    def is_admin(self):
        return self._admin

    def get_message_str(self):
        return "/bd"

    def plain_result(self, text):
        return text


class _FakeClient:
    """Minimal BiliPlatformClient stand-in."""

    def __init__(self, jobs=None, accounts=None, templates=None):
        self.jobs = list(jobs or [])
        self.accounts = list(
            # uid 故意留空：避免测试真的去请求 B站 接口
            accounts or [{"id": "acc1", "name": "主账号", "uid": ""}]
        )
        self.templates = list(templates) if templates is not None else None
        self.created = []
        self.updated = []
        self.actions = []

    async def list_jobs(self):
        return [dict(job) for job in self.jobs]

    async def list_accounts(self):
        return list(self.accounts)

    async def list_templates(self):
        if self.templates is not None:
            return [dict(item) for item in self.templates]
        return [
            {
                "id": "tpl1",
                "name": "AstrBot 直发",
                "content": "{{text}}",
                "variables": [{"key": "text", "label": "正文"}],
            }
        ]

    async def ensure_quick_template(self):
        return {
            "id": "tpl1",
            "name": "AstrBot 直发",
            "content": "{{text}}",
            "variables": [{"key": "text", "label": "正文"}],
        }

    async def upload_images(self, images):
        return [{"key": "up1", "name": "u.jpg", "url": "u"}]

    async def create_job(self, **kwargs):
        job = {
            "id": f"job{len(self.created) + 1}",
            "status": "pending",
            "scheduledAt": "2026-10-10T10:00:00Z",
        }
        self.created.append(kwargs)
        return job

    async def update_job(self, job_id, patch):
        self.updated.append((job_id, patch))
        return {"id": job_id, **patch}

    async def cancel_job(self, job_id):
        self.actions.append(("cancel", job_id))
        return {"id": job_id}

    async def publish_now(self, job_id):
        self.actions.append(("publish-now", job_id))
        return {"id": job_id}

    async def retry_job(self, job_id):
        self.actions.append(("retry", job_id))
        return {"id": job_id}

    async def delete_job(self, job_id):
        self.actions.append(("delete", job_id))
        return None

    async def search_topics(self, keyword, account_id=""):
        return [{"id": "t1", "name": "测试话题"}]

    async def search_mentions(self, keyword, account_id=""):
        return [{"uid": "42", "name": "某UP主"}]


class PluginTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ, {"BILI_PLATFORM_AUX_DATA_DIR": self.tmp.name}
        )
        self.env.start()
        self.plugin = _PLUGIN.BiliPlatformAuxPlugin(context=object())

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()


class ScheduleParserTests(PluginTestCase):
    def _parse(self, value, now):
        return datetime.fromtimestamp(
            self.plugin._parse_schedule(value, now=now.timestamp())
        )

    def test_relative_minutes(self):
        self.assertEqual(self.plugin._parse_schedule("+30m", now=1000), 2800)

    def test_epoch_seconds(self):
        self.assertEqual(self.plugin._parse_schedule("1700000000"), 1700000000.0)

    def test_today_and_tomorrow(self):
        now = datetime(2026, 10, 8, 12, 0)
        self.assertEqual(self._parse("今天20:00", now), datetime(2026, 10, 8, 20, 0))
        self.assertEqual(self._parse("明天08:00", now), datetime(2026, 10, 9, 8, 0))

    def test_today_past_time_rolls_forward(self):
        now = datetime(2026, 10, 8, 21, 30)
        self.assertEqual(self._parse("今天20:00", now), datetime(2026, 10, 9, 20, 0))

    def test_natural_language_chinese_times(self):
        now = datetime(2026, 10, 10, 15, 0)  # 周六 15:00
        cases = {
            "明天上午八点": "2026-10-11 08:00",
            "明天早上8点": "2026-10-11 08:00",
            "明早8点": "2026-10-11 08:00",
            "今晚8点": "2026-10-10 20:00",
            "今晚八点半": "2026-10-10 20:30",
            "今晚七点一刻": "2026-10-10 19:15",
            "明晚11点": "2026-10-11 23:00",
            "下午3点": "2026-10-11 15:00",
            "上午九点": "2026-10-11 09:00",
            "凌晨12点": "2026-10-11 00:00",
            "9点30分": "2026-10-11 09:30",
            "中午": "2026-10-11 12:00",
            "后天中午12点": "2026-10-12 12:00",
            "大后天9点": "2026-10-13 09:00",
            "下周三晚上7点": "2026-10-14 19:00",
            "下周一09:00": "2026-10-12 09:00",
            "周三下午两点": "2026-10-14 14:00",
            "3天后": "2026-10-13 15:00",
            "三天后": "2026-10-13 15:00",
            "两小时后": "2026-10-10 17:00",
            "30分钟后": "2026-10-10 15:30",
            "明天08:00": "2026-10-11 08:00",
            "今天20:00": "2026-10-10 20:00",
        }
        for text, expected in cases.items():
            got = datetime.fromtimestamp(
                self.plugin._parse_schedule(text, now=now.timestamp())
            ).strftime("%Y-%m-%d %H:%M")
            self.assertEqual(got, expected, f"{text} 解析错误")

    def test_machine_formats_are_unaffected_by_natural_language(self):
        now = datetime(2026, 10, 10, 15, 0)
        cases = {
            "+2h": "2026-10-10 17:00",
            "20:00": "2026-10-10 20:00",
            "2026-10-11 08:00": "2026-10-11 08:00",
            "2026-10-11T08:00:00": "2026-10-11 08:00",
        }
        for text, expected in cases.items():
            got = datetime.fromtimestamp(
                self.plugin._parse_schedule(text, now=now.timestamp())
            ).strftime("%Y-%m-%d %H:%M")
            self.assertEqual(got, expected, f"{text} 解析错误")

    def test_next_week_weekday(self):
        now = datetime(2026, 10, 8, 20, 0)  # Thursday
        self.assertEqual(self._parse("下周一09:00", now), datetime(2026, 10, 12, 9, 0))
        self.assertEqual(self._parse("下周日9:30", now), datetime(2026, 10, 18, 9, 30))

    def test_iso_format_still_supported(self):
        self.assertEqual(
            self._parse("2026-10-10 20:00", datetime(2026, 1, 1)),
            datetime(2026, 10, 10, 20, 0),
        )

    def test_invalid_time_reports_formats(self):
        with self.assertRaises(ValueError) as ctx:
            self.plugin._parse_schedule("某天")
        self.assertIn("+30m", str(ctx.exception))


class WriteGuardTests(PluginTestCase):
    def setUp(self):
        super().setUp()
        self.plugin.config.save_session(
            "u1",
            platform_url="https://bilidyn.basmc.org",
            username="alice",
            sid="sid",
            user={"id": "u1"},
        )
        self.plugin.config.save_session(
            "u2",
            platform_url="https://bilidyn.basmc.org",
            username="bob",
            sid="sid2",
        )
        self.client = _FakeClient()
        self._client_patch = patch.object(
            self.plugin, "_client", lambda event: self.client
        )
        self._client_patch.start()

    def tearDown(self):
        self._client_patch.stop()
        super().tearDown()

    def test_group_member_cannot_publish(self):
        event = _FakeEvent(message_type="group", admin=False)
        with self.assertRaises(_PLUGIN.PlatformAPIError):
            asyncio.run(self.plugin._create(event, "hello", ""))
        self.assertEqual(self.client.created, [])

    def test_group_admin_can_publish(self):
        event = _FakeEvent(message_type="group", admin=True)
        result = asyncio.run(self.plugin._create(event, "hello", ""))
        self.assertIn("平台任务已创建", result)
        self.assertEqual(len(self.client.created), 1)

    def test_group_member_can_preview(self):
        event = _FakeEvent(message_type="group", admin=False)
        result = asyncio.run(self.plugin._preview(event, "hello", ""))
        self.assertIn("发布预览", result)
        self.assertEqual(self.client.created, [])

    def test_private_chat_allows_publish(self):
        event = _FakeEvent(sender_id="u2", admin=False)
        result = asyncio.run(self.plugin._create(event, "hello", ""))
        self.assertIn("平台任务已创建", result)

    def test_raw_message_role_marks_admin(self):
        class _Sender:
            role = "admin"

        class _Raw:
            sender = _Sender()

        class _MessageObj:
            raw_message = _Raw()

        event = _FakeEvent(message_type="group", admin=False)
        event.message_obj = _MessageObj()
        self.assertTrue(self.plugin._group_admin(event))

    def test_preview_warns_about_duplicate_text(self):
        self.client.jobs = [
            {"id": "jobA", "status": "published", "text": "hello"}
        ]
        event = _FakeEvent()
        result = asyncio.run(self.plugin._preview(event, "hello", ""))
        self.assertIn("重复提醒", result)
        self.assertIn("jobA", result)

    def test_group_member_cannot_edit_job(self):
        self.client.jobs = [{"id": "jobA", "status": "pending"}]
        event = _FakeEvent(message_type="group", admin=False)
        with self.assertRaises(_PLUGIN.PlatformAPIError):
            asyncio.run(self.plugin._job_edit(event, 'jobA {"text":"x"}'))
        self.assertEqual(self.client.updated, [])

    def test_job_edit_rejects_foreign_job(self):
        self.client.jobs = [{"id": "jobA", "status": "pending"}]
        result = asyncio.run(
            self.plugin._job_edit(_FakeEvent(), 'jobB {"text":"x"}')
        )
        self.assertIn("不属于当前平台用户", result)
        self.assertEqual(self.client.updated, [])

    def test_job_edit_updates_owned_job(self):
        self.client.jobs = [{"id": "jobA", "status": "pending"}]
        result = asyncio.run(
            self.plugin._job_edit(_FakeEvent(), 'jobA {"text":"x"}')
        )
        self.assertIn("已更新", result)
        self.assertEqual(self.client.updated[0][0], "jobA")

    def test_job_edit_reports_bad_json(self):
        result = asyncio.run(self.plugin._job_edit(_FakeEvent(), "jobA not-json"))
        self.assertIn("JSON", result)

    def test_job_edit_converts_natural_time(self):
        self.client.jobs = [{"id": "jobA", "status": "pending"}]
        result = asyncio.run(
            self.plugin._job_edit(_FakeEvent(), 'jobA {"scheduledAt":"+30m"}')
        )
        self.assertIn("已更新", result)
        self.assertTrue(
            self.client.updated[0][1]["scheduledAt"].endswith("+00:00")
        )

    def test_job_edit_accepts_epoch_seconds(self):
        self.client.jobs = [{"id": "jobA", "status": "pending"}]
        result = asyncio.run(
            self.plugin._job_edit(_FakeEvent(), 'jobA {"scheduledAt":1760000000}')
        )
        self.assertIn("已更新", result)
        self.assertIn(
            "2025-10-09T0", self.client.updated[0][1]["scheduledAt"]
        )

    def test_job_edit_rejects_published_job(self):
        self.client.jobs = [{"id": "jobA", "status": "published"}]
        result = asyncio.run(
            self.plugin._job_edit(_FakeEvent(), 'jobA {"text":"x"}')
        )
        self.assertIn("duplicate", result)
        self.assertEqual(self.client.updated, [])

    def test_job_edit_reports_unparsable_time(self):
        self.client.jobs = [{"id": "jobA", "status": "pending"}]
        result = asyncio.run(
            self.plugin._job_edit(_FakeEvent(), 'jobA {"scheduledAt":"某天"}')
        )
        self.assertIn("无法解析", result)
        self.assertEqual(self.client.updated, [])

    def test_job_action_rejects_unknown_action(self):
        self.client.jobs = [{"id": "jobA", "status": "pending"}]
        result = asyncio.run(self.plugin._job_action(_FakeEvent(), "jobA", "nuke"))
        self.assertIn("支持的操作", result)
        self.assertEqual(self.client.actions, [])

    def test_job_action_rejects_foreign_job(self):
        self.client.jobs = [{"id": "jobA", "status": "pending"}]
        result = asyncio.run(
            self.plugin._job_action(_FakeEvent(), "jobB", "cancel")
        )
        self.assertIn("不属于当前平台用户", result)
        self.assertEqual(self.client.actions, [])

    def test_topic_and_mention_commands(self):
        event = _FakeEvent()
        self.assertIn("测试话题", asyncio.run(self.plugin._topic_command(event, "测试")))
        self.assertIn("已绑定话题", asyncio.run(self.plugin._topic_command(event, "use 1")))
        self.assertIn("某UP主", asyncio.run(self.plugin._mention_command(event, "某UP")))
        self.assertIn("已添加", asyncio.run(self.plugin._mention_command(event, "add 1")))
        draft = self.plugin.config.get_draft("u1")
        self.assertEqual(draft["topic_id"], "t1")
        self.assertEqual(draft["mentions"][0]["uid"], "42")

    def test_bd_dispatches_subcommands(self):
        async def run(cmd):
            event = _FakeEvent()
            event.get_message_str = lambda: cmd
            return [chunk async for chunk in self.plugin.bd(event)]

        self.assertIn("B站动态辅助发布", asyncio.run(run("/bd help"))[0])
        self.assertIn("380nm 平台状态", asyncio.run(run("/bd status"))[0])
        self.assertIn("发布结果通知", asyncio.run(run("/bd notify"))[0])
        self.client.jobs = [{"id": "jobA", "status": "pending"}]
        self.assertIn(
            "已更新", asyncio.run(run('/bd edit jobA {"text":"x"}'))[0]
        )
        self.assertEqual(self.plugin.config.get_origin("u1"), "test:private:u1")

    def test_status_reports_notify_state(self):
        text = self.plugin._status(_FakeEvent())
        self.assertIn("380nm 平台状态", text)
        self.assertIn("发布通知", text)


    def test_llm_tools_drive_preview_and_confirm(self):
        async def run(gen):
            return [chunk async for chunk in gen]

        event = _FakeEvent()
        out = asyncio.run(run(self.plugin.llm_preview(event, "hello")))
        self.assertIn("发布预览", out[0])
        out = asyncio.run(run(self.plugin.llm_confirm(event)))
        self.assertIn("平台任务已创建", out[0])

    def test_llm_tools_cover_topic_mention_and_variables(self):
        async def run(gen):
            return [chunk async for chunk in gen]

        event = _FakeEvent()
        self.assertIn(
            "测试话题",
            asyncio.run(run(self.plugin.llm_topic_search(event, "测试")))[0],
        )
        self.assertIn(
            "已绑定话题",
            asyncio.run(run(self.plugin.llm_topic_use(event, 1)))[0],
        )
        self.assertIn(
            "某UP主",
            asyncio.run(run(self.plugin.llm_mention_search(event, "某UP")))[0],
        )
        self.assertIn(
            "已添加",
            asyncio.run(run(self.plugin.llm_mention_add(event, 1)))[0],
        )
        self.assertIn(
            "已设置",
            asyncio.run(run(self.plugin.llm_set_var(event, "extra", "x")))[0],
        )
        draft = self.plugin.config.get_draft("u1")
        self.assertEqual(draft["variables"]["extra"], "x")
        self.assertEqual(draft["topic_id"], "t1")
        self.assertEqual(draft["mentions"][0]["uid"], "42")


class PluginConfigCardTests(unittest.TestCase):
    """The WebUI config card (_conf_schema.json) must be honoured."""

    SUPPORTED_TYPES = {
        "int",
        "float",
        "bool",
        "string",
        "text",
        "list",
        "file",
        "object",
        "template_list",
        "dict",
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                "BILI_PLATFORM_AUX_DATA_DIR": self.tmp.name,
                "BILI_PLATFORM_ACCOUNT_ID": "",
                "BILI_PLATFORM_TEMPLATE_ID": "",
                "BILI_PLATFORM_TITLE": "",
                "BILI_PLATFORM_SID": "",
                "BILI_PLATFORM_VARIABLES_JSON": "",
                "BILI_PLATFORM_ALLOW_PASSWORD_LOGIN": "",
            },
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _plugin(self, card=None):
        return _PLUGIN.BiliPlatformAuxPlugin(context=object(), config=card or {})

    def test_schema_types_and_defaults(self):
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertGreater(len(schema), 10)
        for key, item in schema.items():
            self.assertIn("type", item, key)
            self.assertIn(
                item["type"],
                self.SUPPORTED_TYPES,
                f"{key} uses an unsupported AstrBot config type",
            )
            self.assertIn("description", item, key)
            self.assertIn("default", item, key)

    def test_every_card_item_is_visible_and_read_by_the_code(self):
        plugin_dir = Path(__file__).resolve().parents[1]
        schema = json.loads(
            (plugin_dir / "_conf_schema.json").read_text(encoding="utf-8")
        )
        # AstrBot skips items flagged invisible, which silently removes them
        # from the WebUI card (the sid field was hit by this).
        for key, item in schema.items():
            self.assertFalse(
                item.get("invisible"), f"配置项 {key} 会被 WebUI 隐藏"
            )
            self.assertIn("hint", item, f"配置项 {key} 缺少 hint")

        source = (plugin_dir / "main.py").read_text(encoding="utf-8")
        read_keys = set(
            re.findall(
                r'self\._conf_(?:str|bool|int|json)\(\s*"([a-z_]+)"', source
            )
        )
        self.assertTrue(read_keys, "没有解析到任何配置项读取")
        self.assertEqual(
            read_keys,
            set(schema),
            "配置卡片与代码读取的配置项不一致",
        )

    def test_card_overrides_environment_defaults(self):
        plugin = self._plugin(
            {
                "account_id": "acc9",
                "template_id": "tpl9",
                "title": "卡片标题",
                "task_type": "转载",
                "variables_json": '{"extra":"card"}',
                "slots_json": '{"translator":"某人"}',
            }
        )
        defaults = plugin._publish_defaults()
        self.assertEqual(defaults["account_id"], "acc9")
        self.assertEqual(defaults["template_id"], "tpl9")
        self.assertEqual(defaults["title"], "卡片标题")
        self.assertEqual(defaults["task_type"], "转载")
        self.assertEqual(defaults["variables"]["extra"], "card")
        self.assertEqual(defaults["slots"]["translator"], "某人")

    def test_environment_is_kept_when_card_is_empty(self):
        with patch.dict(
            os.environ, {"BILI_PLATFORM_ACCOUNT_ID": "acc-env"}, clear=False
        ):
            plugin = self._plugin({})
            self.assertEqual(plugin._publish_defaults()["account_id"], "acc-env")

    def test_bad_json_in_card_falls_back(self):
        plugin = self._plugin({"variables_json": "not-json"})
        self.assertEqual(plugin._publish_defaults()["variables"], {})

    def test_card_controls_platform_url_and_allowlist(self):
        plugin = self._plugin({"platform_url": "https://bilidyn.basmc.org"})
        self.assertEqual(plugin._platform_url(), "https://bilidyn.basmc.org")
        self.assertEqual(plugin._validate_platform_url(plugin._platform_url()),
                         "https://bilidyn.basmc.org")
        plugin2 = self._plugin({"allowed_hosts": "example.org"})
        with self.assertRaises(ValueError):
            plugin2._validate_platform_url("https://evil.example")

    def test_card_upload_limit_is_clamped(self):
        self.assertEqual(
            self._plugin({"max_upload_bytes": 1048576})._max_upload_bytes(),
            1048576,
        )
        self.assertEqual(
            self._plugin({"max_upload_bytes": 999999999})._max_upload_bytes(),
            _PLUGIN.PLATFORM_MAX_UPLOAD_BYTES,
        )

    def test_card_dedicated_account_is_used_for_publishing(self):
        plugin = self._plugin({"account_id": "acc9"})
        plugin.config.save_session(
            "u1",
            platform_url="https://bilidyn.basmc.org",
            username="alice",
            sid="sid",
        )
        client = _FakeClient(
            accounts=[{"id": "acc1", "name": "first"}, {"id": "acc9", "name": "dedicated"}]
        )
        with patch.object(plugin, "_client", lambda event: client):
            plan = asyncio.run(plugin._build_plan(_FakeEvent(), "hello", ""))
        self.assertEqual(plan["account_id"], "acc9")

    def test_unknown_dedicated_account_is_rejected(self):
        plugin = self._plugin({"account_id": "acc9"})
        plugin.config.save_session(
            "u1",
            platform_url="https://bilidyn.basmc.org",
            username="alice",
            sid="sid",
        )
        client = _FakeClient(accounts=[{"id": "acc1", "name": "first"}])
        with patch.object(plugin, "_client", lambda event: client):
            with self.assertRaises(ValueError) as ctx:
                asyncio.run(plugin._build_plan(_FakeEvent(), "hello", ""))
        self.assertIn("acc9", str(ctx.exception))

    def test_card_can_disable_group_admin_guard(self):
        plugin = self._plugin({"group_write_admin_only": False})
        plugin.config.save_session(
            "u1",
            platform_url="https://bilidyn.basmc.org",
            username="alice",
            sid="sid",
        )
        client = _FakeClient()
        with patch.object(plugin, "_client", lambda event: client):
            result = asyncio.run(
                plugin._create(_FakeEvent(message_type="group", admin=False),
                               "hello", "")
            )
        self.assertIn("平台任务已创建", result)
        self.assertEqual(len(client.created), 1)

    def test_card_sid_bootstraps_a_session(self):
        plugin = self._plugin({"sid": "card-sid"})
        plugin._conf["shared_session_whitelist"] = _FakeEvent().unified_msg_origin
        seen = {}

        class _FakePlatformClient:
            def __init__(self, url, sid=""):
                seen["url"] = url
                seen["sid"] = sid

            async def me(self):
                return {"id": "u1", "username": "alice"}

        with patch.object(_PLUGIN, "BiliPlatformClient", _FakePlatformClient):
            asyncio.run(plugin._bootstrap_from_env(_FakeEvent()))
        session = plugin.config.load_session("u1")
        self.assertEqual(session["sid"], "card-sid")
        self.assertEqual(seen["url"], "https://bilidyn.basmc.org")

    def test_card_sid_accepts_cookie_prefix_and_quotes(self):
        plugin = self._plugin({"sid": "  sid=card-sid;  "})
        plugin._conf["shared_session_whitelist"] = _FakeEvent().unified_msg_origin
        self.assertEqual(plugin._default_sid(), "card-sid")

        class _FakePlatformClient:
            def __init__(self, url, sid=""):
                self.sid = sid
                self.seen = sid

            async def me(self):
                return {"id": "u1", "username": "alice"}

        with patch.object(_PLUGIN, "BiliPlatformClient", _FakePlatformClient):
            asyncio.run(plugin._bootstrap_from_env(_FakeEvent()))
        self.assertEqual(plugin.config.load_session("u1")["sid"], "card-sid")

    def test_card_controls_password_login_flag(self):
        blocked = self._plugin({})
        self.assertIn(
            "密码登录默认关闭", asyncio.run(blocked._login(_FakeEvent(), "a b"))
        )

        class _FakeLoginClient:
            def __init__(self, url):
                self.url = url

            async def login(self, username, password):
                return {"sid": "sid-login", "user": {"username": username}}

        allowed = self._plugin({"allow_password_login": True})
        with patch.object(_PLUGIN, "BiliPlatformClient", _FakeLoginClient):
            result = asyncio.run(allowed._login(_FakeEvent(), "alice pw"))
        self.assertIn("登录成功", result)
        self.assertEqual(allowed.config.load_session("u1")["sid"], "sid-login")

    def test_card_can_disable_notifications(self):
        plugin = self._plugin({"notify_enabled": False})
        plugin.config.save_session(
            "u1",
            platform_url="https://bilidyn.basmc.org",
            username="alice",
            sid="sid",
        )
        plugin.config.set_origin("u1", "test:private:u1")
        sent = []

        async def recorder(origin, text):
            sent.append(text)

        class _ExplodingPlatformClient:
            def __init__(self, url, sid=""):
                pass

            async def list_jobs(self):
                raise AssertionError("通知被关闭时不应查询平台")

        with patch.object(plugin, "_notify_origin", recorder):
            with patch.object(
                _PLUGIN, "BiliPlatformClient", _ExplodingPlatformClient
            ):
                asyncio.run(plugin._poll_notifications("u1"))
        self.assertEqual(sent, [])

    def test_notify_interval_is_clamped(self):
        plugin = self._plugin({"notify_interval_seconds": 1})
        self.assertEqual(max(5, plugin._conf_int("notify_interval_seconds", 20)), 5)


class AskBeforePublishingTests(unittest.TestCase):
    """信息不全时应该先反问用户，而不是自己编标题/话题。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ, {"BILI_PLATFORM_AUX_DATA_DIR": self.tmp.name}
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _plugin(self, card=None):
        plugin = _PLUGIN.BiliPlatformAuxPlugin(context=object(), config=card or {})
        plugin.config.save_session(
            "u1",
            platform_url="https://bilidyn.basmc.org",
            username="alice",
            sid="sid",
        )
        return plugin

    def _client_patch(self, plugin, client):
        return patch.object(plugin, "_client", lambda event: client)

    def test_gaps_are_optional_by_default(self):
        plugin = self._plugin()
        plan = {"text": "hello"}
        gaps = {gap["field"]: gap for gap in plugin._plan_gaps(plan)}
        self.assertFalse(gaps["title"]["required"])
        self.assertFalse(gaps["topic"]["required"])
        self.assertFalse(gaps["images"]["required"])
        self.assertEqual(plugin._required_gaps(plan), [])

    def test_require_title_switch_blocks_publish_and_keeps_draft(self):
        plugin = self._plugin({"require_title": True})
        client = _FakeClient()
        with self._client_patch(plugin, client):
            result = asyncio.run(plugin._create(_FakeEvent(), "hello", ""))
        self.assertIn("还缺少必填信息", result)
        self.assertIn("标题", result)
        self.assertEqual(client.created, [])
        self.assertEqual(plugin.config.get_draft("u1")["text"], "hello")

    def test_confirm_after_setting_title(self):
        plugin = self._plugin({"require_title": True})
        client = _FakeClient()
        with self._client_patch(plugin, client):
            asyncio.run(plugin._create(_FakeEvent(), "hello", ""))
            self.assertIn("标题已设置", plugin._title_set(_FakeEvent(), "我的标题"))
            result = asyncio.run(plugin._confirm(_FakeEvent()))
        self.assertIn("平台任务已创建", result)
        self.assertEqual(len(client.created), 1)
        self.assertEqual(client.created[0]["title"], "我的标题")

    def test_title_can_be_explicitly_skipped(self):
        plugin = self._plugin({"require_title": True})
        client = _FakeClient()
        with self._client_patch(plugin, client):
            self.assertIn("不带标题", plugin._title_set(_FakeEvent(), "无"))
            result = asyncio.run(plugin._create(_FakeEvent(), "hello", ""))
        self.assertIn("平台任务已创建", result)
        self.assertEqual(client.created[0]["title"], "")

    def test_topic_switch_and_skip(self):
        plugin = self._plugin({"require_topic": True})
        client = _FakeClient()
        with self._client_patch(plugin, client):
            blocked = asyncio.run(plugin._create(_FakeEvent(), "hello", ""))
            self.assertIn("话题标签", blocked)
            self.assertEqual(client.created, [])
            self.assertIn(
                "不绑定话题",
                asyncio.run(plugin._topic_command(_FakeEvent(), "skip")),
            )
            result = asyncio.run(plugin._confirm(_FakeEvent()))
        self.assertIn("平台任务已创建", result)

    def test_title_length_is_validated(self):
        plugin = self._plugin()
        self.assertIn("最多 20 个字", plugin._title_set(_FakeEvent(), "x" * 21))
        self.assertEqual(plugin.config.get_draft("u1").get("title"), None)

    def test_title_and_type_from_draft_survive_new_plans(self):
        plugin = self._plugin({"require_title": True})
        client = _FakeClient()
        with self._client_patch(plugin, client):
            event = _FakeEvent()
            plugin._title_set(event, "草稿标题")
            plugin._type_set(event, "转载")
            result = asyncio.run(plugin._create(event, "hello", ""))
        self.assertIn("平台任务已创建", result)
        created = client.created[0]
        self.assertEqual(created["title"], "草稿标题")
        self.assertEqual(created["task_type"], "转载")

    def test_type_is_normalised_and_validated(self):
        plugin = self._plugin()
        self.assertIn("转载", plugin._type_set(_FakeEvent(), "搬运"))
        self.assertEqual(plugin.config.get_draft("u1")["task_type"], "转载")
        self.assertIn("只能是", plugin._type_set(_FakeEvent(), "不知道"))

    def test_setting_variable_refreshes_missing_list(self):
        plugin = self._plugin({"template_id": "tpl2"})
        template = {
            "id": "tpl2",
            "name": "双变量模板",
            "content": "{{text}} {{extra}}",
            "variables": [
                {"key": "text", "label": "正文"},
                {"key": "extra", "label": "附加"},
            ],
        }
        client = _FakeClient(templates=[template])
        with self._client_patch(plugin, client):
            preview = asyncio.run(plugin._preview(_FakeEvent(), "hello", ""))
            self.assertIn("缺少变量", preview)
            self.assertIn("extra", preview)
            plugin._var_set(_FakeEvent(), "extra 来源已授权")
            self.assertEqual(
                plugin.config.get_draft("u1")["missing_variables"], []
            )
            result = asyncio.run(plugin._confirm(_FakeEvent()))
        self.assertIn("平台任务已创建", result)

    def test_quoted_message_images_are_used(self):
        plugin = self._plugin()
        called = {}

        class Reply:
            id = "123"

        class MessageObj:
            message = [Reply()]

        class Bot:
            async def call_action(self, action, **kwargs):
                called[action] = kwargs
                return {
                    "message": [
                        {"type": "image", "data": {"url": "http://x/q.png"}}
                    ]
                }

        event = _FakeEvent()
        event.message_obj = MessageObj()
        event.bot = Bot()

        async def fake_fetch(url):
            return b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

        with patch.object(plugin, "_fetch_binary", fake_fetch):
            images, note = asyncio.run(plugin._collect_images(event))
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["content_type"], "image/png")
        self.assertEqual(called["get_msg"]["message_id"], 123)
        self.assertEqual(note, "")

    def test_quoted_message_without_readable_images(self):
        plugin = self._plugin()

        class Reply:
            id = "123"

        class MessageObj:
            message = [Reply()]

        event = _FakeEvent()
        event.message_obj = MessageObj()  # 没有 bot → 平台上读不到
        images, note = asyncio.run(plugin._collect_images(event))
        self.assertEqual(images, [])
        self.assertIn("引用", note)

    def test_tool_errors_become_readable_text(self):
        plugin = self._plugin()

        async def timed_out():
            raise httpx.ConnectTimeout("")

        self.assertIn("平台连接超时", asyncio.run(plugin._llm(timed_out())))

        async def expired():
            raise _PLUGIN.PlatformAPIError("平台会话已过期，请重新登录", 401)

        self.assertIn("重新登录", asyncio.run(plugin._llm(expired())))

        def bad_value():
            raise ValueError("正文不能为空")

        self.assertIn("正文不能为空", asyncio.run(plugin._llm(lambda: bad_value())))

    def test_platform_lookups_are_cached(self):
        plugin = self._plugin({"template_id": "tpl1"})
        counts = {"accounts": 0, "templates": 0, "jobs": 0}

        class CountingClient(_FakeClient):
            async def list_accounts(self):
                counts["accounts"] += 1
                return await super().list_accounts()

            async def list_templates(self):
                counts["templates"] += 1
                return await super().list_templates()

            async def list_jobs(self):
                counts["jobs"] += 1
                return await super().list_jobs()

        client = CountingClient()
        event = _FakeEvent()

        async def fake_send(message_chain):
            return None

        event.send = fake_send
        with self._client_patch(plugin, client):
            asyncio.run(plugin._preview(event, "正文", ""))
            asyncio.run(plugin._preview(event, "正文", ""))
        self.assertEqual(counts["accounts"], 1)
        self.assertEqual(counts["templates"], 1)
        self.assertEqual(counts["jobs"], 1)

    def test_preview_renders_and_sends_a_card(self):
        from PIL import Image

        plugin = self._plugin({"preview_footer": "IP属地：江苏"})
        client = _FakeClient()
        event = _FakeEvent()
        sent = []

        async def fake_send(message_chain):
            sent.append(message_chain)

        event.send = fake_send
        with self._client_patch(plugin, client):
            text = asyncio.run(
                plugin._preview(event, "正文内容", "明天上午八点")
            )
        self.assertIn("发布预览", text)
        self.assertNotIn("渲染失败", text)
        self.assertEqual(len(sent), 1)
        files = sorted(
            (Path(plugin.config.data_dir) / "temp").glob("preview_*.png")
        )
        self.assertEqual(len(files), 1)
        with Image.open(files[0]) as card:
            self.assertEqual(card.size[0], 760)
            self.assertGreater(card.size[1], 200)

    def test_card_uses_publishing_account_avatar(self):
        from PIL import Image

        plugin = self._plugin({"preview_avatar": "/tmp/local-avatar.png"})
        client = _FakeClient(
            accounts=[
                {"id": "acc1", "name": "主账号", "avatar": "https://i0.hdslb.com/x.jpg"}
            ]
        )
        captured = {}

        async def fake_fetch(url):
            return b"PLATFORM" if "hdslb" in url else b"LOCAL"

        async def fake_fallback():
            return b"LOCAL"

        def fake_render(data):
            captured.update(data)
            return Image.new("RGB", (10, 10), (255, 255, 255))

        event = _FakeEvent()

        async def fake_send(message_chain):
            return None

        event.send = fake_send
        with self._client_patch(plugin, client):
            with patch.object(plugin, "_fetch_binary", fake_fetch):
                with patch.object(plugin, "_avatar_fallback_bytes", fake_fallback):
                    with patch.object(_PLUGIN, "render_preview_card", fake_render):
                        asyncio.run(plugin._preview(event, "正文", ""))
        self.assertEqual(captured["account_avatar"], b"PLATFORM")
        self.assertEqual(captured["account_name"], "主账号")

    def test_card_uses_bili_uid_face_when_platform_has_none(self):
        from PIL import Image

        plugin = self._plugin()
        client = _FakeClient(
            accounts=[{"id": "acc1", "name": "主账号", "avatar": "", "uid": "12345"}]
        )
        captured = {}

        async def fake_json(url, params=None):
            self.assertIn("bilibili", url)
            return {"data": {"card": {"face": "https://i0.hdslb.com/bfs/face/x.jpg"}}}

        async def fake_fetch(url):
            return b"BILI" if "hdslb" in url else None

        async def fake_fallback():
            return b"LOCAL"

        def fake_render(data):
            captured.update(data)
            return Image.new("RGB", (10, 10), (255, 255, 255))

        event = _FakeEvent()

        async def fake_send(message_chain):
            return None

        event.send = fake_send
        with self._client_patch(plugin, client):
            with patch.object(plugin, "_fetch_json", fake_json):
                with patch.object(plugin, "_fetch_binary", fake_fetch):
                    with patch.object(plugin, "_avatar_fallback_bytes", fake_fallback):
                        with patch.object(_PLUGIN, "render_preview_card", fake_render):
                            asyncio.run(plugin._preview(event, "正文", ""))
        self.assertEqual(captured["account_avatar"], b"BILI")

    def test_card_falls_back_when_account_has_no_avatar(self):
        from PIL import Image

        plugin = self._plugin()
        client = _FakeClient(accounts=[{"id": "acc1", "name": "主账号", "avatar": ""}])
        captured = {}

        async def fake_fallback():
            return b"LOCAL"

        def fake_render(data):
            captured.update(data)
            return Image.new("RGB", (10, 10), (255, 255, 255))

        event = _FakeEvent()

        async def fake_send(message_chain):
            return None

        event.send = fake_send
        with self._client_patch(plugin, client):
            with patch.object(plugin, "_avatar_fallback_bytes", fake_fallback):
                with patch.object(_PLUGIN, "render_preview_card", fake_render):
                    asyncio.run(plugin._preview(event, "正文", ""))
        self.assertEqual(captured["account_avatar"], b"LOCAL")

    def test_preview_card_can_be_disabled(self):
        plugin = self._plugin({"preview_card": False})
        client = _FakeClient()
        event = _FakeEvent()
        sent = []

        async def fake_send(message_chain):
            sent.append(message_chain)

        event.send = fake_send
        with self._client_patch(plugin, client):
            asyncio.run(plugin._preview(event, "正文内容", ""))
        self.assertEqual(sent, [])
        self.assertEqual(
            list((Path(plugin.config.data_dir) / "temp").glob("preview_*.png")), []
        )

    def test_preview_card_failure_falls_back_to_text(self):
        plugin = self._plugin()
        client = _FakeClient()
        event = _FakeEvent()

        async def fake_send(message_chain):
            return None

        event.send = fake_send
        with self._client_patch(plugin, client):
            with patch.object(
                _PLUGIN, "render_preview_card", side_effect=RuntimeError("boom")
            ):
                text = asyncio.run(plugin._preview(event, "正文内容", ""))
        self.assertIn("发布预览", text)
        self.assertIn("预览图渲染失败", text)

    def test_preview_mentions_optional_gaps(self):
        plugin = self._plugin()
        client = _FakeClient()
        with self._client_patch(plugin, client):
            text = asyncio.run(plugin._preview(_FakeEvent(), "hello", ""))
        self.assertIn("可选", text)
        self.assertIn("图片", text)
        self.assertIn("/bd confirm", text)

    def test_publish_options_lists_templates_and_policies(self):
        plugin = self._plugin({"account_id": "acc1"})
        client = _FakeClient()
        with self._client_patch(plugin, client):
            text = asyncio.run(plugin._publish_options(_FakeEvent()))
        self.assertIn("可选模板", text)
        self.assertIn("AstrBot 直发", text)
        self.assertIn("必填策略", text)
        self.assertIn("不要替用户决定", text)

    def test_publish_options_handles_missing_session(self):
        plugin = _PLUGIN.BiliPlatformAuxPlugin(context=object(), config={})
        plugin.config.clear_session("u1")
        text = asyncio.run(plugin._publish_options(_FakeEvent()))
        self.assertIn("读取发布选项失败", text)

    def test_llm_tools_for_title_type_and_options(self):
        async def run(gen):
            return [chunk async for chunk in gen]

        plugin = self._plugin()
        client = _FakeClient()
        with self._client_patch(plugin, client):
            event = _FakeEvent()
            self.assertIn(
                "标题已设置",
                asyncio.run(run(plugin.llm_set_title(event, "LLM 标题")))[0],
            )
            self.assertIn(
                "转载",
                asyncio.run(run(plugin.llm_set_type(event, "转载")))[0],
            )
            options = asyncio.run(run(plugin.llm_publish_options(event)))[0]
        self.assertIn("可选模板", options)
        draft = plugin.config.get_draft("u1")
        self.assertEqual(draft["title"], "LLM 标题")
        self.assertEqual(draft["task_type"], "转载")


class NotificationTests(PluginTestCase):
    def setUp(self):
        super().setUp()
        self.plugin.config.save_session(
            "u1",
            platform_url="https://bilidyn.basmc.org",
            username="alice",
            sid="sid",
        )
        self.plugin.config.set_origin("u1", "test:private:u1")
        self.sent = []

        async def recorder(origin, text):
            self.sent.append((origin, text))

        self._notify_patch = patch.object(self.plugin, "_notify_origin", recorder)
        self._notify_patch.start()

    def tearDown(self):
        self._notify_patch.stop()
        super().tearDown()

    def _platform(self, jobs, error=None):
        holder = {"jobs": list(jobs), "error": error}

        class _FakePlatformClient:
            def __init__(self, url, sid=""):
                self.url = url
                self.sid = sid

            async def list_jobs(self):
                if holder["error"] is not None:
                    raise holder["error"]
                return [dict(job) for job in holder["jobs"]]

        return patch.object(_PLUGIN, "BiliPlatformClient", _FakePlatformClient)

    def test_origin_persists_in_state_file(self):
        reloaded = _PLUGIN.AuxConfigManager(self.tmp.name)
        self.assertEqual(reloaded.get_origin("u1"), "test:private:u1")
        self.assertEqual(reloaded.list_owners(), ["u1"])

    def test_first_poll_is_silent_baseline(self):
        with self._platform([{"id": "j1", "status": "pending"}]):
            asyncio.run(self.plugin._poll_notifications("u1"))
        self.assertEqual(self.sent, [])

    def test_published_and_failed_jobs_notify(self):
        with self._platform([{"id": "j1", "status": "pending"}]):
            asyncio.run(self.plugin._poll_notifications("u1"))
        with self._platform(
            [
                {"id": "j1", "status": "published", "dynamicUrl": "https://bili/x"},
                {"id": "j2", "status": "failed", "lastError": "boom"},
            ]
        ):
            asyncio.run(self.plugin._poll_notifications("u1"))
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[0][0], "test:private:u1")
        self.assertIn("已发布", self.sent[0][1])
        self.assertIn("https://bili/x", self.sent[0][1])
        self.assertIn("失败", self.sent[1][1])

    def test_unchanged_status_does_not_repeat(self):
        with self._platform([{"id": "j1", "status": "published"}]):
            asyncio.run(self.plugin._poll_notifications("u1"))
            asyncio.run(self.plugin._poll_notifications("u1"))
        self.assertEqual(self.sent, [])

    def test_expired_session_clears_and_notifies(self):
        error = _PLUGIN.PlatformAPIError("expired", 401)
        with self._platform([], error=error):
            asyncio.run(self.plugin._poll_notifications("u1"))
        self.assertIsNone(self.plugin.config.load_session("u1"))
        self.assertEqual(len(self.sent), 1)
        self.assertIn("过期", self.sent[0][1])

    def test_server_error_keeps_session_without_notice(self):
        error = _PLUGIN.PlatformAPIError("boom", 500)
        with self._platform([], error=error):
            asyncio.run(self.plugin._poll_notifications("u1"))
        self.assertIsNotNone(self.plugin.config.load_session("u1"))
        self.assertEqual(self.sent, [])

    def test_notify_off_skips_polling(self):
        self.plugin.config.set_notify("u1", False)
        error = _PLUGIN.PlatformAPIError("boom", 500)
        with self._platform([], error=error):
            asyncio.run(self.plugin._poll_notifications("u1"))
        self.assertEqual(self.sent, [])
        event = _FakeEvent()
        self.assertIn("关闭", self.plugin._notify_command(event, "status"))
        self.plugin._notify_command(event, "on")
        self.assertTrue(self.plugin.config.get_notify("u1"))
        self.assertIn("开启", self.plugin._notify_command(event, "status"))


if __name__ == "__main__":
    unittest.main()
