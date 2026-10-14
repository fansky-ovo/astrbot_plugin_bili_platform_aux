"""AstrBot auxiliary plugin for an existing 380nm Bilibili dynamic platform."""

from __future__ import annotations

import asyncio
import inspect
import json
import httpx
import os
import re
import time
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.core.platform.message_type import MessageType

from .config_manager import AuxConfigError, AuxConfigManager
from .render import render_preview_card
from .platform_client import (
    BiliPlatformClient,
    DEFAULT_PLATFORM_URL,
    PlatformAPIError,
    normalize_platform_url,
    normalize_sid,
)

PLATFORM_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
PLATFORM_MAX_IMAGES = 9
HELP_TEXT = """\
B站动态辅助发布

/bdhelp                      查看指令列表
/bd login <用户名> <密码>      私聊登录 380nm 平台
/bd logout                    退出平台会话
/bd status                    查看平台登录与默认账号
/bd accounts                  查看平台已绑定 B站账号
/bd account use <账号ID>      设置默认账号
/bd templates                 查看平台模板
/bd presets                   查看发布预设
/bd preset use <名称>         使用发布预设
/bd preset add <名称> <JSON>  新增/覆盖发布预设
/bd preset remove <名称>      删除发布预设
/bd upload                    把消息附件上传到平台图库
/bd images                    查看平台图库数量
/bd preview <正文>            预览发布内容，不写入平台
/bd confirm                   确认预览并创建任务
/bd draft                     查看当前草稿
/bd draft cancel              取消当前草稿
/bd notify on|off             开启/关闭发布结果通知
/bd var <变量> <值>           设置模板变量
/bd title <标题>              设置草稿标题（「无」表示不要标题）
/bd type <原创|转载>          设置草稿内容类型
/bd topic <关键词>            搜索话题
/bd topic use <序号>          绑定话题到草稿
/bd topic skip                本贴不要话题标签
/bd mention <关键词>          搜索 @用户
/bd mention add <序号>        添加 @用户到草稿
/bd import <链接> [|| 正文]   调用平台导入 Pixiv/X/Danbooru
/bd post <正文>               立即创建发布任务
/bd schedule <时间> || <正文> 创建定时发布任务
/bd queue [状态]              查看/筛选平台发布队列
/bd job <任务ID>              查看任务详情
/bd edit <任务ID> <JSON>      编辑平台任务并重新排队
/bd duplicate <任务ID>        复制任务到草稿
/bd library [关键词]          搜索平台图库
/bd image use <序号|key>      把图库图片加入草稿
/bd image order <key1,key2>   调整草稿图片顺序
/bd image remove <key>        从草稿移除图片
/bd image clear               清空草稿图片
/bd cancel <任务ID>           取消任务
/bd now <任务ID>              立即发布任务
/bd retry <任务ID>            重新入队
/bd delete <任务ID>           删除任务
/bd logs [数量]               查看平台运行日志

时间格式：`+30m`、`+2h`、`明天上午八点`、`今晚8点`、`下周三晚上7点`、`3天后`、
`明天08:00`、`2026-10-10 20:00`。

群聊限制：查询、草稿、预览、搜索对所有人开放；上传、导入、发布、编辑和任务操作仅管理员可用。
平台密码只能私聊登录；sid 加密保存，发布结果通知会发到最近一次使用 /bd 的会话。
"""


_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_NUM = r"(?:\d{1,2}|[零〇一二三四五六七八九十两]{1,3})"
_CN_DAY_OFFSETS = {
    "今天": 0,
    "今日": 0,
    "今晚": 0,
    "今夜": 0,
    "今早": 0,
    "明天": 1,
    "明日": 1,
    "明早": 1,
    "明晚": 1,
    "明夜": 1,
    "后天": 2,
    "后日": 2,
    "大后天": 3,
}
_CN_DAY_HINTS = {
    "今晚": "晚上",
    "今夜": "晚上",
    "今早": "早上",
    "明早": "早上",
    "明晚": "晚上",
    "明夜": "晚上",
}
_CN_MORNING = {"凌晨", "早上", "早晨", "上午"}
_CN_EVENING = {"下午", "傍晚", "晚上", "夜里", "夜晚"}
_CN_NOON = {"中午", "正午"}
_CN_MIDNIGHT = {"半夜", "午夜", "凌晨"}
_CN_PERIODS = sorted(
    _CN_MORNING | _CN_EVENING | _CN_NOON | _CN_MIDNIGHT, key=len, reverse=True
)
_CN_PERIOD_DEFAULT = {
    "凌晨": 1,
    "早上": 8,
    "早晨": 8,
    "上午": 9,
    "中午": 12,
    "正午": 12,
    "下午": 15,
    "傍晚": 18,
    "晚上": 20,
    "夜里": 21,
    "夜晚": 21,
    "半夜": 0,
    "午夜": 0,
}
_CN_WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_CN_KEYWORDS = re.compile(
    r"[今天明日早晚凌晨午夜上午下午中午周星期礼拜点時时后刻半]"
)


def _cn_number(text: str) -> int | None:
    """把「八」「十二」「二十」「三十」或阿拉伯数字转成整数。"""

    text = (text or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if text in _CN_DIGITS:
        return _CN_DIGITS[text]
    if text == "十":
        return 10
    if text.startswith("十") and len(text) == 2 and text[1] in _CN_DIGITS:
        return 10 + _CN_DIGITS[text[1]]
    if len(text) == 2 and text[0] in _CN_DIGITS and text[1] == "十":
        return _CN_DIGITS[text[0]] * 10
    if (
        len(text) == 3
        and text[1] == "十"
        and text[0] in _CN_DIGITS
        and text[2] in _CN_DIGITS
    ):
        return _CN_DIGITS[text[0]] * 10 + _CN_DIGITS[text[2]]
    return None


def _cn_clock(text: str) -> tuple[int, int] | None:
    """从「八点半」「8点20分」「9:30」「八点」里取出 (时, 分)。"""

    match = re.search(rf"({_CN_NUM})\s*[:：]\s*({_CN_NUM})", text)
    if match:
        hour = _cn_number(match.group(1))
        minute = _cn_number(match.group(2))
        if hour is not None and minute is not None:
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute
    match = re.search(rf"({_CN_NUM})\s*[点時时]\s*(半|一刻|三刻|(?:{_CN_NUM})\s*分?)?", text)
    if match:
        hour = _cn_number(match.group(1))
        if hour is None or not 0 <= hour <= 23:
            return None
        tail = (match.group(2) or "").strip()
        if tail == "半":
            return hour, 30
        if tail == "一刻":
            return hour, 15
        if tail == "三刻":
            return hour, 45
        if tail:
            minute = _cn_number(tail.rstrip("分").strip())
            if minute is None or not 0 <= minute <= 59:
                return None
            return hour, minute
        return hour, 0
    return None


def _cn_schedule(value: str, now: float) -> float | None:
    """解析中文自然语言时间；不认识时返回 None，交给后续格式解析。"""

    raw = re.sub(r"\s+", "", str(value or ""))
    if not raw or not _CN_KEYWORDS.search(raw):
        return None

    # 相对时间：三十分钟后 / 两小时后 / 3天后 / 1周后
    match = re.fullmatch(rf"({_CN_NUM})个?(分钟|小时|天|周|星期)(?:后|之后|以后)", raw)
    if match:
        amount = _cn_number(match.group(1))
        if amount is None:
            return None
        unit = {
            "分钟": 60,
            "小时": 3600,
            "天": 86400,
            "周": 7 * 86400,
            "星期": 7 * 86400,
        }[match.group(2)]
        return now + amount * unit

    current = datetime.fromtimestamp(now)
    rest = raw
    day_offset: int | None = None
    period_hint: str = ""
    for word in sorted(_CN_DAY_OFFSETS, key=len, reverse=True):
        if rest.startswith(word):
            day_offset = _CN_DAY_OFFSETS[word]
            period_hint = _CN_DAY_HINTS.get(word, "")
            rest = rest[len(word) :]
            break

    weekday: int | None = None
    week_mode = ""
    if day_offset is None:
        match = re.match(
            r"(下下周|下下星期|下周|下星期|下个周|下个星期|本周|这周|这个周|周|星期|礼拜)([一二三四五六日天])",
            rest,
        )
        if match:
            weekday = _CN_WEEKDAY[match.group(2)]
            label = match.group(1)
            if label.startswith("下下"):
                week_mode = "next2"
            elif label.startswith("下"):
                week_mode = "next"
            else:
                week_mode = "this"
            rest = rest[match.end() :]

    period = period_hint or next(
        (word for word in _CN_PERIODS if word in rest), ""
    )
    clock = _cn_clock(rest)
    if clock is None and not period:
        if weekday is None and day_offset is None:
            return None
        # 只有「明天」「下周三」这种，没有具体钟点，交给其他格式解析
        return None
    if clock is None:
        hour = _CN_PERIOD_DEFAULT.get(period, 8)
        minute = 0
    else:
        hour, minute = clock

    if period in _CN_NOON and hour < 12:
        hour += 12
    elif period in _CN_EVENING and hour < 12:
        hour += 12
    elif period in _CN_MIDNIGHT and hour == 12:
        hour = 0

    if weekday is not None:
        if week_mode == "next":
            days = (7 - current.weekday()) + weekday
        elif week_mode == "next2":
            days = (14 - current.weekday()) + weekday
        else:
            days = (weekday - current.weekday()) % 7
        base = current + timedelta(days=days)
    elif day_offset:
        base = current + timedelta(days=day_offset)
    else:
        base = current

    target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target.timestamp() <= now:
        if week_mode == "this":
            target += timedelta(days=7)
        elif day_offset == 0:
            target += timedelta(days=1)
        elif day_offset is None and weekday is None:
            target += timedelta(days=1)
    return target.timestamp()


class BiliPlatformAuxPlugin(star.Star):
    def __init__(self, context: star.Context, config: dict | None = None) -> None:
        self.context = context
        self._conf: dict = dict(config) if config else {}
        data_dir = os.environ.get(
            "BILI_PLATFORM_AUX_DATA_DIR", "data/bili_platform_aux"
        )
        self.config = AuxConfigManager(data_dir)
        self._clients: dict[str, BiliPlatformClient] = {}
        self._last_action: dict[str, float] = {}
        self._image_results: dict[str, list[dict]] = {}
        self._topic_results: dict[str, list[dict]] = {}
        self._mention_results: dict[str, list[dict]] = {}
        self._job_status: dict[str, dict[str, str]] = {}
        self._notify_task: asyncio.Task[None] | None = None
        self._avatar_cache: dict[str, bytes | None] = {}
        self._bili_face_cache: dict[str, bytes | None] = {}
        self._cache: dict[str, tuple[float, Any]] = {}

    async def initialize(self) -> None:
        if self._notify_task is None or self._notify_task.done():
            self._notify_task = asyncio.create_task(
                self._notify_loop(), name="bili-platform-notify"
            )

    async def terminate(self) -> None:
        task = self._notify_task
        self._notify_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._clients.clear()

    def _owner(self, event: AstrMessageEvent) -> str:
        return str(event.get_sender_id())

    # ---- WebUI 插件配置卡片（_conf_schema.json）----

    def _conf_raw(self, key: str) -> Any:
        try:
            return (self._conf or {}).get(key)
        except Exception:
            return None

    def _conf_str(self, key: str, default: str = "") -> str:
        value = self._conf_raw(key)
        if value is None:
            return default
        text = str(value).strip()
        return text or default

    def _conf_bool(self, key: str, default: bool = False) -> bool:
        value = self._conf_raw(key)
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _conf_int(self, key: str, default: int) -> int:
        value = self._conf_raw(key)
        if value is None or value == "":
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _conf_json(self, key: str, default: dict) -> dict:
        raw = self._conf_raw(key)
        if raw is None or not str(raw).strip():
            return dict(default)
        if isinstance(raw, dict):
            return dict(raw)
        try:
            parsed = json.loads(str(raw))
        except json.JSONDecodeError:
            logger.warning("bili platform config %s is not valid JSON", key)
            return dict(default)
        return dict(parsed) if isinstance(parsed, dict) else dict(default)

    def _platform_url(self) -> str:
        return self._conf_str(
            "platform_url",
            os.environ.get("BILI_PLATFORM_URL", DEFAULT_PLATFORM_URL).strip()
            or DEFAULT_PLATFORM_URL,
        )

    def _allowed_hosts(self) -> set[str]:
        raw = self._conf_str(
            "allowed_hosts",
            os.environ.get("BILI_PLATFORM_ALLOWED_HOSTS", "bilidyn.basmc.org"),
        )
        return {item.strip().lower() for item in raw.split(",") if item.strip()}

    def _default_sid(self) -> str:
        return normalize_sid(
            self._conf_str("sid", os.environ.get("BILI_PLATFORM_SID", ""))
        )

    def _default_username(self) -> str:
        return self._conf_str(
            "platform_username",
            os.environ.get("BILI_PLATFORM_USERNAME", "").strip(),
        )

    def _validate_platform_url(self, value: str) -> str:
        url = normalize_platform_url(value)
        parsed = urlparse(url)
        allowed = self._allowed_hosts()
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" and host not in {"127.0.0.1", "localhost"}:
            raise ValueError("平台地址必须使用 HTTPS")
        if allowed and host not in allowed:
            raise ValueError(
                "平台地址不在允许列表内，请在插件配置卡片或 "
                "BILI_PLATFORM_ALLOWED_HOSTS 中添加该主机"
            )
        return url

    @staticmethod
    def _group_admin(event: AstrMessageEvent) -> bool:
        checker = getattr(event, "is_admin", None)
        if callable(checker):
            try:
                if checker():
                    return True
            except Exception:
                pass
        message_obj = getattr(event, "message_obj", None)
        raw_message = getattr(message_obj, "raw_message", None)
        sender = getattr(raw_message, "sender", None)
        if sender is None and isinstance(raw_message, dict):
            sender = raw_message.get("sender")
        if isinstance(sender, dict):
            role = str(sender.get("role") or "")
        else:
            role = str(getattr(sender, "role", "") or "")
        return role in {"owner", "admin"}

    def _require_write(self, event: AstrMessageEvent) -> None:
        if event.get_message_type() != MessageType.GROUP_MESSAGE:
            return
        if not self._conf_bool("group_write_admin_only", True):
            return
        if self._group_admin(event):
            return
        raise PlatformAPIError(
            "群聊中只有管理员可以发布、上传、导入或操作任务；其他成员请私聊操作。"
        )

    def _check_rate(
        self, event: AstrMessageEvent, action: str, seconds: float = 2.0
    ) -> None:
        owner = self._owner(event)
        key = f"{owner}:{action}"
        now = time.time()
        last = self._last_action.get(key, 0.0)
        if now - last < seconds:
            raise PlatformAPIError("操作过于频繁，请稍后再试")
        self._last_action[key] = now

    def _client(self, event: AstrMessageEvent) -> BiliPlatformClient:
        owner = self._owner(event)
        session = self.config.load_session(owner)
        self._check_shared_access(event, session)
        if not session:
            raise PlatformAPIError("尚未登录 380nm 平台，请私聊 /bd login <用户名> <密码>")
        cache_key = owner + "|" + session["platform_url"] + "|" + session["sid"]
        client = self._clients.get(cache_key)
        if client is None:
            client = BiliPlatformClient(
                session["platform_url"], sid=session["sid"]
            )
            self._clients[cache_key] = client
        return client

    @filter.command("bdhelp")
    async def bdhelp(self, event: AstrMessageEvent) -> None:
        yield event.plain_result(HELP_TEXT)

    @filter.command("bd")
    async def bd(self, event: AstrMessageEvent) -> None:
        text = event.get_message_str().strip()
        parts = text.split(None, 2)
        subcmd = parts[1].lower() if len(parts) > 1 else ""
        args = parts[2] if len(parts) > 2 else ""
        try:
            await self._bootstrap_from_env(event)
            if subcmd not in ("login", "logout", "help", ""):
                self._check_shared_access(event, self.config.load_session(self._owner(event)))
            session = self.config.load_session(self._owner(event))
            if session and (not self._is_shared(session) or event.unified_msg_origin in self._shared_origins()):
                if self.config.get_origin(self._owner(event)) != event.unified_msg_origin:
                    self.config.set_origin(
                        self._owner(event), event.unified_msg_origin
                    )
            if subcmd in ("", "help"):
                yield event.plain_result(HELP_TEXT)
            elif subcmd == "login":
                yield event.plain_result(await self._login(event, args))
            elif subcmd == "logout":
                yield event.plain_result(await self._logout(event))
            elif subcmd == "status":
                yield event.plain_result(self._status(event))
            elif subcmd == "accounts":
                yield event.plain_result(await self._accounts(event))
            elif subcmd == "account":
                yield event.plain_result(await self._account_action(event, args))
            elif subcmd == "templates":
                yield event.plain_result(await self._templates(event))
            elif subcmd == "presets":
                yield event.plain_result(self._preset_list(event))
            elif subcmd == "preset":
                yield event.plain_result(self._preset_command(event, args))
            elif subcmd == "upload":
                yield event.plain_result(await self._upload(event))
            elif subcmd == "images":
                yield event.plain_result(await self._images(event))
            elif subcmd == "import":
                yield event.plain_result(await self._import_link(event, args))
            elif subcmd == "preview":
                yield event.plain_result(await self._preview(event, args, ""))
            elif subcmd == "confirm":
                yield event.plain_result(await self._confirm(event))
            elif subcmd == "draft":
                action = args.strip().lower()
                if action == "cancel":
                    self.config.clear_draft(self._owner(event))
                    yield event.plain_result("当前草稿已取消。")
                else:
                    yield event.plain_result(self._draft_text(event))
            elif subcmd == "notify":
                yield event.plain_result(self._notify_command(event, args))
            elif subcmd == "title":
                yield event.plain_result(self._title_set(event, args))
            elif subcmd == "type":
                yield event.plain_result(self._type_set(event, args))
            elif subcmd == "var":
                yield event.plain_result(self._var_set(event, args))
            elif subcmd == "topic":
                yield event.plain_result(await self._topic_command(event, args))
            elif subcmd == "mention":
                yield event.plain_result(await self._mention_command(event, args))
            elif subcmd == "post":
                yield event.plain_result(await self._create(event, args, ""))
            elif subcmd == "schedule":
                yield event.plain_result(await self._schedule(event, args))
            elif subcmd == "queue":
                yield event.plain_result(await self._queue(event, args))
            elif subcmd == "job":
                yield event.plain_result(await self._job_command(event, args))
            elif subcmd == "edit":
                yield event.plain_result(await self._job_edit(event, args))
            elif subcmd == "duplicate":
                yield event.plain_result(await self._duplicate(event, args))
            elif subcmd == "library":
                yield event.plain_result(await self._library(event, args))
            elif subcmd == "image":
                yield event.plain_result(self._image_command(event, args))
            elif subcmd == "cancel":
                yield event.plain_result(
                    await self._job_action(event, args, "cancel")
                )
            elif subcmd == "now":
                yield event.plain_result(
                    await self._job_action(event, args, "publish-now")
                )
            elif subcmd == "retry":
                yield event.plain_result(
                    await self._job_action(event, args, "retry")
                )
            elif subcmd == "delete":
                yield event.plain_result(
                    await self._job_action(event, args, "delete")
                )
            elif subcmd == "logs":
                yield event.plain_result(await self._logs(event, args))
            else:
                yield event.plain_result("未知子命令。\n\n" + HELP_TEXT)
        except PlatformAPIError as exc:
            if exc.status_code == 401:
                self.config.clear_session(self._owner(event))
                yield event.plain_result("平台会话已过期，请重新登录。")
            else:
                yield event.plain_result(f"操作失败: {exc}")
        except (AuxConfigError, ValueError) as exc:
            yield event.plain_result(f"操作失败: {exc}")

    def _shared_origins(self) -> set[str]:
        raw = self._conf_str("shared_session_whitelist", os.environ.get("BILI_PLATFORM_SHARED_SESSION_WHITELIST", ""))
        return {item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()}

    def _is_shared(self, session: dict | None) -> bool:
        # Legacy automatically saved sessions had no source marker.
        return bool(session and (session.get("shared") or (
            self._default_sid() and session.get("sid") == self._default_sid()
        )))

    def _check_shared_access(self, event, session) -> None:
        if self._is_shared(session) and event.unified_msg_origin not in self._shared_origins():
            raise PlatformAPIError("当前会话不在共享账号白名单中，请绑定个人平台账号，或联系管理员配置会话白名单。")

    async def _bootstrap_from_env(self, event: AstrMessageEvent) -> None:
        if self.config.load_session(self._owner(event)):
            return
        sid = self._default_sid()
        if not sid:
            return
        if event.unified_msg_origin not in self._shared_origins():
            return
        platform_url = self._validate_platform_url(self._platform_url())
        client = BiliPlatformClient(platform_url, sid=sid)
        user = await client.me()
        self.config.save_session(
            self._owner(event),
            platform_url=platform_url,
            username=str(
                self._default_username()
                or user.get("username")
                or "env-session"
            ),
            sid=sid,
            user=user,
            shared=True,
        )
        self.config.set_origin(self._owner(event), event.unified_msg_origin)

    async def _login(self, event: AstrMessageEvent, args: str) -> str:
        env_allows = (
            os.environ.get("BILI_PLATFORM_ALLOW_PASSWORD_LOGIN", "") == "1"
        )
        if not self._conf_bool("allow_password_login", env_allows):
            return (
                "密码登录默认关闭。请使用 BILI_PLATFORM_SID 环境变量，"
                "或在服务器运行 admin_cli.py set-session；"
                "确需密码登录时设置 BILI_PLATFORM_ALLOW_PASSWORD_LOGIN=1。"
            )
        if event.get_message_type() == MessageType.GROUP_MESSAGE:
            return "平台密码涉及账号安全，请私聊使用 /bd login <用户名> <密码>。"
        tokens = args.split()
        if len(tokens) < 2:
            return "用法: /bd login <用户名> <密码>"
        platform_url = self._platform_url()
        if tokens[0].startswith(("http://", "https://")):
            if len(tokens) < 3:
                return "用法: /bd login <平台URL> <用户名> <密码>"
            platform_url = self._validate_platform_url(tokens[0])
            username, password = tokens[1], tokens[2]
        else:
            platform_url = self._validate_platform_url(platform_url)
            username, password = tokens[0], tokens[1]
        client = BiliPlatformClient(platform_url)
        result = await client.login(username, password)
        self.config.save_session(
            self._owner(event),
            platform_url=platform_url,
            username=username,
            sid=result["sid"],
            user=result.get("user") or {},
        )
        self.config.set_origin(
            self._owner(event), event.unified_msg_origin
        )
        user = result.get("user") or {}
        return (
            f"登录成功 | 平台={platform_url} | "
            f"用户={user.get('username') or username} | "
            f"角色={user.get('role') or '?'}"
        )

    async def _logout(self, event: AstrMessageEvent) -> str:
        try:
            client = self._client(event)
            await client.logout()
        except PlatformAPIError:
            pass
        self.config.clear_session(self._owner(event))
        self._clients = {
            key: value
            for key, value in self._clients.items()
            if not key.startswith(self._owner(event) + "|")
        }
        return "已退出 380nm 平台会话。"

    def _status(self, event: AstrMessageEvent) -> str:
        self._check_shared_access(event, self.config.load_session(self._owner(event)))
        status = self.config.status(self._owner(event))
        if not status.get("logged_in"):
            return "尚未登录 380nm 平台。"
        user = status.get("user") or {}
        return "\n".join(
            (
                "380nm 平台状态",
                f"地址: {status['platform_url']}",
                f"用户: {status.get('username') or user.get('username') or '?'}",
                f"角色: {user.get('role') or '?'}",
                f"默认账号: {status.get('account_id') or '未设置（使用第一个账号）'}",
                f"待发布图片: {status.get('pending_images', 0)} 张",
                f"当前预设: {status.get('active_preset') or '无'}",
                f"发布通知: {'开启' if status.get('notify', True) else '关闭'}",
            )
        )

    async def _accounts(self, event: AstrMessageEvent) -> str:
        accounts = await self._client(event).list_accounts()
        if not accounts:
            return "平台没有已绑定的 B站账号。"
        return "\n".join(
            f"- {item.get('id')} | {item.get('name') or item.get('uname')} | "
            f"uid={item.get('uid')}"
            for item in accounts
        )

    async def _account_action(self, event: AstrMessageEvent, args: str) -> str:
        parts = args.split()
        if len(parts) != 2 or parts[0] != "use":
            return "用法: /bd account use <账号ID>"
        account_id = parts[1]
        accounts = await self._client(event).list_accounts()
        if account_id not in {item.get("id") for item in accounts}:
            return "找不到该平台账号。"
        self.config.set_default_account(self._owner(event), account_id)
        return f"默认 B站账号已设置为 {account_id}。"

    async def _templates(self, event: AstrMessageEvent) -> str:
        templates = await self._client(event).list_templates()
        if not templates:
            return "平台没有模板。"
        return "\n".join(
            f"- {item.get('id')} | {item.get('name')} | "
            f"变量={','.join(v.get('key', '') for v in item.get('variables') or [])}"
            for item in templates
        )

    async def _upload(self, event: AstrMessageEvent) -> str:
        self._require_write(event)
        self._check_rate(event, "upload", 2.0)
        images, note = await self._collect_images(event)
        if not images:
            hint = f"（{note}）" if note else "图片也可以放在被引用的消息里。"
            return "没有检测到图片附件。" + hint
        uploaded = await self._client(event).upload_images(images)
        self.config.set_pending_images(
            self._owner(event),
            [
                {
                    "key": item.get("key", ""),
                    "name": item.get("name", ""),
                    "url": item.get("url", ""),
                }
                for item in uploaded
            ],
        )
        return "\n".join(
            f"已上传 {len(uploaded)} 张图片；后续 /bd post 会自动带图。"
        )

    async def _images(self, event: AstrMessageEvent) -> str:
        images = await self._client(event).list_images()
        return f"平台图库共 {len(images)} 张图片。"

    def _preset_list(self, event: AstrMessageEvent) -> str:
        presets = self.config.list_presets(self._owner(event))
        active, _ = self.config.get_active_preset(self._owner(event))
        if not presets:
            return "当前没有发布预设。"
        lines = ["发布预设:"]
        for name, config in sorted(presets.items()):
            mark = " [当前]" if name == active else ""
            lines.append(
                f"- {name}{mark} | template={config.get('template_id', '')} | "
                f"account={config.get('account_id', '')}"
            )
        return "\n".join(lines)

    def _preset_command(self, event: AstrMessageEvent, args: str) -> str:
        action, _, rest = args.strip().partition(" ")
        action = action or "list"
        owner = self._owner(event)
        if action == "list":
            return self._preset_list(event)
        if action == "use":
            self.config.set_active_preset(owner, rest.strip())
            return f"当前发布预设已切换为 {rest.strip()}。"
        if action == "remove":
            self.config.remove_preset(owner, rest.strip())
            return f"发布预设 {rest.strip()} 已删除。"
        if action == "add":
            name, _, raw = rest.strip().partition(" ")
            if not name or not raw:
                return "用法: /bd preset add <名称> <JSON>"
            try:
                config = json.loads(raw)
            except json.JSONDecodeError as exc:
                return f"预设 JSON 格式错误: {exc}"
            if not isinstance(config, dict):
                return "预设 JSON 必须是对象。"
            allowed = {
                "account_id", "template_id", "title", "topic_id",
                "topic_name", "task_type", "variables", "slots",
            }
            clean = {key: value for key, value in config.items() if key in allowed}
            self.config.set_preset(owner, name, clean)
            return f"发布预设 {name} 已保存。"
        return "用法: /bd preset list|use|add|remove"

    @staticmethod
    def _env_publish_defaults() -> dict:
        variables = {}
        slots = {}
        try:
            variables = json.loads(
                os.environ.get("BILI_PLATFORM_VARIABLES_JSON", "{}") or "{}"
            )
        except json.JSONDecodeError:
            variables = {}
        try:
            slots = json.loads(
                os.environ.get("BILI_PLATFORM_SLOTS_JSON", "{}") or "{}"
            )
        except json.JSONDecodeError:
            slots = {}
        return {
            "account_id": os.environ.get("BILI_PLATFORM_ACCOUNT_ID", "").strip(),
            "template_id": os.environ.get("BILI_PLATFORM_TEMPLATE_ID", "").strip(),
            "title": os.environ.get("BILI_PLATFORM_TITLE", ""),
            "topic_id": os.environ.get("BILI_PLATFORM_TOPIC_ID", "").strip(),
            "topic_name": os.environ.get("BILI_PLATFORM_TOPIC_NAME", "").strip(),
            "task_type": os.environ.get("BILI_PLATFORM_TASK_TYPE", "原创"),
            "variables": variables if isinstance(variables, dict) else {},
            "slots": slots if isinstance(slots, dict) else {},
        }

    def _publish_defaults(self) -> dict:
        defaults = self._env_publish_defaults()
        overrides = {
            "account_id": self._conf_str("account_id"),
            "template_id": self._conf_str("template_id"),
            "title": self._conf_str("title"),
            "topic_id": self._conf_str("topic_id"),
            "topic_name": self._conf_str("topic_name"),
            "task_type": self._conf_str("task_type"),
        }
        for key, value in overrides.items():
            if value:
                defaults[key] = value
        variables = self._conf_json("variables_json", {})
        if variables:
            merged = dict(defaults.get("variables") or {})
            merged.update(variables)
            defaults["variables"] = merged
        slots = self._conf_json("slots_json", {})
        if slots:
            merged = dict(defaults.get("slots") or {})
            merged.update(slots)
            defaults["slots"] = merged
        return defaults

    def _resolve_preset(
        self, event: AstrMessageEvent, preset_name: str = ""
    ) -> dict:
        result = self._publish_defaults()
        owner = self._owner(event)
        active_name, active = self.config.get_active_preset(owner)
        if preset_name:
            presets = self.config.list_presets(owner)
            if preset_name not in presets:
                raise ValueError(f"找不到发布预设: {preset_name}")
            selected = presets[preset_name]
        else:
            selected = active
        if selected:
            result.update(selected)
        result["preset_name"] = preset_name or active_name
        return result

    @staticmethod
    def _extract_preset_prefix(text: str) -> tuple[str, str]:
        match = re.match(r"^preset:([^\s]+)\s+(.*)$", text, re.S)
        if not match:
            return "", text
        return match.group(1), match.group(2)

    async def _build_plan(
        self,
        event: AstrMessageEvent,
        text: str,
        schedule: str,
        preset_name: str = "",
    ) -> dict:
        prefix_preset, text = self._extract_preset_prefix(text)
        if not text.strip():
            raise ValueError("正文不能为空。")
        publish = self._resolve_preset(event, preset_name or prefix_preset)
        owner = self._owner(event)
        draft = self.config.get_draft(owner)
        client = self._client(event)
        accounts = await self._cached(event, "accounts", 60.0, client.list_accounts)
        configured_account = str(publish.get("account_id") or "").strip()
        valid_accounts = {str(item.get("id")) for item in accounts}
        if configured_account and configured_account in valid_accounts:
            account_id = configured_account
        elif configured_account:
            raise ValueError(
                f"配置的 B站账号 {configured_account} 不在当前平台账号列表中；"
                "请用 /bd accounts 核对，或清空账号配置改用默认账号。"
            )
        else:
            account_id = self._resolve_account_id(event, accounts)
        if not account_id:
            raise ValueError("平台没有可用的 B站账号，请先在 380nm 平台绑定。")
        template_id = str(publish.get("template_id") or "").strip()
        if template_id:
            templates = await self._cached(
                event, "templates", 60.0, client.list_templates
            )
            template = next(
                (item for item in templates if str(item.get("id")) == template_id),
                None,
            )
            if template is None:
                raise ValueError(f"找不到发布预设指定的模板: {template_id}")
        else:
            template = await self._cached(
                event, "quick_template", 60.0, client.ensure_quick_template
            )
        variables = dict(publish.get("variables") or {})
        variables.update(draft.get("variables") or {})
        variables["text"] = text
        existing_jobs = await self._cached(event, "jobs", 15.0, client.list_jobs)
        duplicate_job_ids = [
            str(job.get("id"))
            for job in existing_jobs
            if str(job.get("text") or "").strip() == text.strip()
            and job.get("status") in {"pending", "publishing", "published"}
        ]
        required = [
            str(item.get("key"))
            for item in template.get("variables") or []
            if isinstance(item, dict) and item.get("key")
        ]
        missing = [
            key for key in required
            if variables.get(key) in (None, "")
        ]
        topic_id = str(
            draft.get("topic_id")
            or publish.get("topic_id")
            or ""
        ).strip()
        topic_name = str(
            draft.get("topic_name")
            or publish.get("topic_name")
            or ""
        ).strip()
        mentions = list(publish.get("mentions") or [])
        mentions.extend(draft.get("mentions") or [])
        deduped = []
        for mention in mentions:
            uid = str(mention.get("uid") or "")
            if uid and not any(str(item.get("uid")) == uid for item in deduped):
                deduped.append({"uid": uid, "name": str(mention.get("name") or "")})
        title = str(
            draft.get("title")
            if draft.get("title_decided")
            else (publish.get("title") or "")
        ).strip()
        return {
            "text": text,
            "schedule": schedule,
            "account_id": account_id,
            "template_id": str(template.get("id") or ""),
            "template_name": str(template.get("name") or ""),
            "template_content": str(template.get("content") or ""),
            "variables": variables,
            "required_variables": required,
            "missing_variables": missing,
            "title": title,
            "title_decided": bool(draft.get("title_decided")),
            "topic_decided": bool(draft.get("topic_decided")),
            "topic_id": topic_id,
            "topic_name": topic_name,
            "mentions": deduped,
            "task_type": str(
                draft.get("task_type") or publish.get("task_type") or "原创"
            ),
            "slots": publish.get("slots") or {},
            "image_keys": self._merge_plan_images(
                self.config.get_pending_images(owner),
                draft.get("image_keys") or [],
            ),
            "preset_name": publish.get("preset_name", ""),
            "duplicate_job_ids": duplicate_job_ids,
        }

    @staticmethod
    def _merge_plan_images(
        first: list[dict], second: list[dict]
    ) -> list[dict]:
        result: list[dict] = []
        for item in [*first, *second]:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            if not key or any(str(existing.get("key")) == key for existing in result):
                continue
            result.append(
                {
                    "key": key,
                    "name": str(item.get("name") or ""),
                    "url": str(item.get("url") or ""),
                }
            )
            if len(result) >= 9:
                break
        return result

    async def _execute_plan(self, event: AstrMessageEvent, plan: dict) -> dict:
        self._require_write(event)
        self._check_rate(event, "create", 2.0)
        client = self._client(event)
        template_id = str(plan.get("template_id") or "")
        if template_id:
            templates = await self._cached(
                event, "templates", 60.0, client.list_templates
            )
            template = next(
                (item for item in templates if str(item.get("id")) == template_id),
                None,
            )
            if template is None:
                raise ValueError(f"找不到模板: {template_id}")
        else:
            template = await self._cached(
                event, "quick_template", 60.0, client.ensure_quick_template
            )
        variables = dict(plan.get("variables") or {})
        missing_keys = [
            str(item.get("key"))
            for item in template.get("variables") or []
            if isinstance(item, dict) and item.get("key")
        ]
        missing_keys = [
            key for key in missing_keys if variables.get(key) in (None, "")
        ]
        if missing_keys:
            raise ValueError("缺少模板变量: " + "、".join(missing_keys))
        images = list(plan.get("image_keys") or [])
        event_images, _ = await self._collect_images(event)
        if event_images:
            uploaded = await client.upload_images(event_images)
            images.extend(uploaded)
        job = await client.create_job(
            template_id=template.get("id", ""),
            account_id=str(plan.get("account_id") or ""),
            variables=plan.get("variables") or {},
            images=images[:9],
            scheduled_at=(
                self._parse_schedule(str(plan.get("schedule")))
                if plan.get("schedule")
                else time.time()
            ),
            topic=(
                {"id": plan.get("topic_id"), "name": plan.get("topic_name")}
                if plan.get("topic_id") and plan.get("topic_name")
                else None
            ),
            title=str(plan.get("title") or ""),
            mentions=plan.get("mentions") or [],
            task_type=str(plan.get("task_type") or "原创"),
            slots=plan.get("slots") or {},
        )
        self.config.clear_draft(self._owner(event))
        self.config.set_pending_images(self._owner(event), [])
        return job

    @staticmethod
    def _render_preview(plan: dict) -> str:
        content = str(plan.get("template_content") or "{{text}}")
        variables = plan.get("variables") or {}
        rendered = re.sub(
            r"\{\{\s*([\w\-\u4e00-\u9fa5]+)\s*\}\}",
            lambda match: str(variables.get(match.group(1), "")),
            content,
        )
        return rendered

    def _plan_gaps(self, plan: dict) -> list[dict]:
        """列出这次发布还缺哪些信息，以及怎么补。"""

        gaps: list[dict] = []
        if not str(plan.get("text") or "").strip():
            gaps.append(
                {
                    "field": "text",
                    "label": "正文",
                    "required": True,
                    "how": "先让用户给出正文，再 /bd preview <正文>",
                }
            )
        if plan.get("missing_variables"):
            gaps.append(
                {
                    "field": "variables",
                    "label": "模板变量",
                    "required": True,
                    "how": "缺少变量 "
                    + "、".join(plan["missing_variables"])
                    + "，用 /bd var <变量> <值> 补齐后再确认",
                }
            )
        if not str(plan.get("title") or "").strip():
            gaps.append(
                {
                    "field": "title",
                    "label": "标题",
                    "required": self._conf_bool("require_title", False)
                    and not plan.get("title_decided"),
                    "how": "问用户标题写什么；用 /bd title <标题> 设置，"
                    "用户明确不要标题时用 /bd title 无",
                }
            )
        if not str(plan.get("topic_name") or "").strip():
            gaps.append(
                {
                    "field": "topic",
                    "label": "话题标签",
                    "required": self._conf_bool("require_topic", False)
                    and not plan.get("topic_decided"),
                    "how": "问用户要带什么话题；用 /bd topic <关键词> 搜索后 "
                    "/bd topic use <序号>，不要话题时用 /bd topic skip",
                }
            )
        if not plan.get("image_keys"):
            gaps.append(
                {
                    "field": "images",
                    "label": "图片",
                    "required": False,
                    "how": "把图片作为附件随消息发送，或 /bd import <链接> / "
                    "/bd library + /bd image use",
                }
            )
        if not plan.get("mentions"):
            gaps.append(
                {
                    "field": "mentions",
                    "label": "@提及",
                    "required": False,
                    "how": "用 /bd mention <关键词> 搜索后 /bd mention add <序号>",
                }
            )
        return gaps

    def _required_gaps(self, plan: dict) -> list[dict]:
        return [gap for gap in self._plan_gaps(plan) if gap["required"]]

    def _gaps_text(self, plan: dict) -> str:
        gaps = self._plan_gaps(plan)
        if not gaps:
            return ""
        required = [gap for gap in gaps if gap["required"]]
        lines = []
        if required:
            lines.append(
                "请先向用户确认下面的信息，不要替用户编造，也不要在确认前重复提交："
            )
        else:
            lines.append(
                "以下内容目前为空；如果用户没有明确说明可以留空，建议先确认一句："
            )
        for gap in gaps:
            tag = "必填" if gap["required"] else "可选"
            lines.append(f"- {gap['label']}（{tag}）：{gap['how']}")
        return "\n".join(lines)

    def _preview_text(self, plan: dict) -> str:
        lines = [
            "发布预览",
            f"预设: {plan.get('preset_name') or '环境默认/无'}",
            f"账号: {plan.get('account_id')}",
            f"模板: {plan.get('template_name')} ({plan.get('template_id')})",
            f"标题: {plan.get('title') or '无'}",
            f"话题: {('#' + plan['topic_name'] + '#') if plan.get('topic_name') else '无'}",
            f"@提及: {', '.join(item['name'] for item in plan.get('mentions') or []) or '无'}",
            f"图片: {len(plan.get('image_keys') or [])} 张",
            f"计划: {plan.get('schedule') or '立即'}",
        ]
        if plan.get("duplicate_job_ids"):
            lines.append(
                "重复提醒: 平台已有相同正文任务 "
                + "、".join(plan["duplicate_job_ids"][:5])
            )
        gaps = self._plan_gaps(plan)
        lines.append("")
        lines.append(self._render_preview(plan))
        lines.append("")
        if self._required_gaps(plan):
            lines.append(self._gaps_text(plan))
            lines.append("补齐后重新 /bd preview 核对，或 /bd draft cancel 取消。")
        else:
            lines.append("确认创建请回复 /bd confirm；取消请回复 /bd draft cancel。")
            if gaps:
                lines.append(self._gaps_text(plan))
        return "\n".join(lines)

    async def _import_link(self, event: AstrMessageEvent, args: str) -> str:
        self._require_write(event)
        self._check_rate(event, "import", 3.0)
        link, _, text = args.partition("||")
        if not link.strip():
            return "用法: /bd import <链接> [|| 正文]"
        result = await self._client(event).import_library_link(link.strip())
        images = [
            {
                "key": item.get("key", ""),
                "name": item.get("name", ""),
                "url": item.get("url", ""),
            }
            for item in result.get("images") or []
        ]
        if not images:
            return "平台没有从该链接导入到图片。"
        self.config.set_pending_images(self._owner(event), images)
        if text.strip():
            return await self._preview(event, text.strip(), "")
        return (
            f"已从链接导入 {len(images)} 张图片到平台图库。"
            "请回复 /bd preview <正文> 预览并确认发布。"
        )

    async def _create(
        self,
        event: AstrMessageEvent,
        text: str,
        schedule: str,
        preset_name: str = "",
    ) -> str:
        plan = await self._build_plan(event, text, schedule, preset_name)
        if self._required_gaps(plan):
            self.config.update_draft(self._owner(event), **plan)
            return (
                "任务未创建：还缺少必填信息。\n"
                + self._gaps_text(plan)
                + "\n补齐后可用 /bd confirm 创建，或 /bd draft cancel 取消。"
            )
        job = await self._execute_plan(event, plan)
        return (
            f"平台任务已创建 | id={job.get('id')} | "
            f"状态={job.get('status')} | 计划={job.get('scheduledAt')}"
        )

    async def _preview(
        self, event: AstrMessageEvent, text: str, schedule: str = ""
    ) -> str:
        plan = await self._build_plan(event, text, schedule)
        self.config.update_draft(self._owner(event), **plan)
        note = await self._send_preview_card(event, plan)
        rendered = self._preview_text(plan)
        return rendered + ("\n" + note if note else "")

    async def _confirm(self, event: AstrMessageEvent) -> str:
        plan = self.config.get_draft(self._owner(event))
        if not plan:
            return "当前没有待确认草稿。"
        if self._required_gaps(plan):
            return "任务未创建：草稿还缺少必填信息。\n" + self._gaps_text(plan)
        job = await self._execute_plan(event, plan)
        return (
            f"平台任务已创建 | id={job.get('id')} | "
            f"状态={job.get('status')} | 计划={job.get('scheduledAt')}"
        )

    def _draft_text(self, event: AstrMessageEvent) -> str:
        plan = self.config.get_draft(self._owner(event))
        if not plan:
            return "当前没有草稿。"
        return self._preview_text(plan)

    async def _llm(self, target):
        """把工具里的异常转成可读文本，避免 AstrBot 只拿到空的 error。"""

        try:
            result = target() if callable(target) else target
            if inspect.isawaitable(result):
                result = await result
            return result
        except PlatformAPIError as exc:
            if exc.status_code == 401:
                return "操作失败: 平台会话已过期，请重新登录。"
            return f"操作失败: {exc}"
        except httpx.HTTPError as exc:
            return (
                "操作失败: 平台连接超时或不可达（"
                + type(exc).__name__
                + "），请稍后重试。"
            )
        except (AuxConfigError, ValueError) as exc:
            return f"操作失败: {exc}"
        except Exception as exc:  # noqa: BLE001
            logger.warning("bili tool failed: %r", exc)
            return f"操作失败: {type(exc).__name__}"

    def _preview_temp_dir(self) -> Path:
        path = Path(self.config.data_dir) / "temp"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _clean_preview_temp(self) -> None:
        cutoff = time.time() - 1800
        try:
            for item in self._preview_temp_dir().glob("preview_*.png"):
                if item.stat().st_mtime < cutoff:
                    item.unlink()
        except OSError:
            pass

    def _absolute_url(self, url: str) -> str:
        value = str(url or "").strip()
        if not value:
            return ""
        if value.startswith("/"):
            return self._platform_url().rstrip("/") + value
        return value

    async def _cached(self, event: AstrMessageEvent, key: str, ttl: float, factory):
        self._check_shared_access(event, self.config.load_session(self._owner(event)))
        cache_key = f"{self._owner(event)}:{key}"
        entry = self._cache.get(cache_key)
        now = time.time()
        if entry and now - entry[0] < ttl:
            return entry[1]
        value = await factory()
        self._cache[cache_key] = (now, value)
        return value

    @staticmethod
    def _fetch_headers() -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com/",
        }

    async def _fetch_json(self, url: str, params: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
                headers=self._fetch_headers(),
            ) as client:
                response = await client.get(url, params=params)
                payload = response.json()
        except Exception as exc:
            logger.debug("bili json fetch failed: %r", exc)
            return {}
        return payload if isinstance(payload, dict) else {}

    async def _bili_face_bytes(self, uid: str) -> bytes | None:
        """平台账号没存头像时，按 uid 直接向 B站 要一次 face。"""

        value = str(uid or "").strip()
        if not value.isdigit():
            return None
        if value in self._bili_face_cache:
            return self._bili_face_cache[value]
        payload = await self._fetch_json(
            "https://api.bilibili.com/x/web-interface/card", {"mid": value}
        )
        card = (payload.get("data") or {}).get("card") or {}
        face = str(card.get("face") or "")
        data = await self._fetch_binary(face) if face else None
        self._bili_face_cache[value] = data
        return data

    async def _fetch_binary(self, url: str) -> bytes | None:
        target = self._absolute_url(url)
        if not target.startswith(("http://", "https://")):
            return None
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
                headers=self._fetch_headers(),
            ) as client:
                response = await client.get(target)
        except Exception as exc:
            logger.debug("bili preview fetch failed: %r", exc)
            return None
        if response.status_code >= 400 or not response.content:
            return None
        if len(response.content) > 12 * 1024 * 1024:
            return None
        return response.content

    @staticmethod
    def _preview_time_text(schedule: str) -> str:
        raw = str(schedule or "").strip()
        if not raw:
            return "立即发布"
        try:
            when = datetime.fromtimestamp(
                BiliPlatformAuxPlugin._parse_schedule(raw)
            )
        except ValueError:
            return raw
        return (
            f"{when.year}年{when.month}月{when.day}日 "
            f"{when.hour:02d}:{when.minute:02d}"
        )

    async def _preview_image_bytes(
        self, event: AstrMessageEvent, plan: dict
    ) -> list[bytes]:
        images: list[bytes] = []
        attachments, _ = await self._collect_images(event)
        for item in attachments:
            images.append(item.get("data") or b"")
        images = [item for item in images if item]
        for item in plan.get("image_keys") or []:
            if len(images) >= 9:
                break
            data = await self._fetch_binary(str(item.get("url") or ""))
            if data:
                images.append(data)
        return images[:9]

    def _resources_dir(self) -> Path:
        return Path(self.config.data_dir) / "resources"

    def _plugin_resources(self) -> Path:
        return Path(__file__).resolve().parent / "resources"

    def _emoji_font_path(self) -> str:
        for candidate in (
            self._resources_dir() / "NotoColorEmoji.ttf",
            self._plugin_resources() / "NotoColorEmoji.ttf",
        ):
            if candidate.is_file():
                return str(candidate)
        return ""

    def _avatar_fallback_source(self) -> str:
        raw = self._conf_str("preview_avatar")
        if raw:
            return raw
        for candidate in (
            self._resources_dir() / "avatar.png",
            self._plugin_resources() / "avatar.png",
        ):
            if candidate.is_file():
                return str(candidate)
        return ""

    async def _avatar_fallback_bytes(self) -> bytes | None:
        raw = self._avatar_fallback_source()
        if not raw:
            return None
        if raw.startswith(("http://", "https://", "/")):
            return await self._fetch_binary(raw)
        local = Path(raw).expanduser()
        if local.is_file():
            try:
                return local.read_bytes()
            except OSError:
                return None
        return None

    async def _render_preview_card(self, event: AstrMessageEvent, plan: dict) -> Path | None:
        if not self._conf_bool("preview_card", True):
            return None
        account_id = str(plan.get("account_id") or "")
        account_name = str(plan.get("account_name") or "")
        avatar: bytes | None = None
        try:
            client = self._client(event)
            accounts = await self._cached(event, "accounts", 60.0, client.list_accounts)
        except PlatformAPIError:
            accounts = []
        account = next(
            (
                item
                for item in accounts
                if str(item.get("id")) == account_id
            ),
            None,
        )
        if account:
            account_name = str(
                account.get("name") or account.get("uname") or account_name
            )
            if account_id and account_id not in self._avatar_cache:
                self._avatar_cache[account_id] = await self._fetch_binary(
                    str(account.get("avatar") or account.get("face") or "")
                )
            avatar = self._avatar_cache.get(account_id)
            if avatar is None:
                avatar = await self._bili_face_bytes(str(account.get("uid") or ""))
        data = {
            "title": plan.get("title") or "",
            "account_name": account_name or account_id,
            "account_avatar": avatar
            or await self._avatar_fallback_bytes(),
            "emoji_font_path": self._emoji_font_path(),
            "resources_dir": str(self._resources_dir()),
            "time_text": self._preview_time_text(str(plan.get("schedule") or "")),
            "topic": plan.get("topic_name") or "",
            "text": self._render_preview(plan),
            "footer": self._conf_str("preview_footer"),
            "image_bytes": await self._preview_image_bytes(event, plan),
        }
        card = render_preview_card(data)
        self._clean_preview_temp()
        target = self._preview_temp_dir() / f"preview_{int(time.time() * 1000)}.png"
        card.save(target)
        return target

    async def _send_preview_card(self, event: AstrMessageEvent, plan: dict) -> str:
        if self._required_gaps(plan):
            return ""
        try:
            card = await self._render_preview_card(event, plan)
        except Exception as exc:  # noqa: BLE001
            logger.warning("bili preview card render failed: %r", exc)
            return "（预览图渲染失败，以上方文字为准）"
        if card is None:
            return ""
        try:
            await event.send(MessageChain().file_image(str(card)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("bili preview card send failed: %r", exc)
            return "（预览图发送失败，以上方文字为准）"
        return ""

    def _title_set(self, event: AstrMessageEvent, title: str) -> str:
        value = str(title or "").strip()
        if value in {"", "无", "不要", "不用", "none", "None", "-", "空"}:
            self.config.update_draft(
                self._owner(event), title="", title_decided=True
            )
            return "已记录：这条动态不带标题（不会再提示标题必填）。"
        if len(value) > 20:
            return "标题最多 20 个字（平台限制），请缩短。"
        self.config.update_draft(
            self._owner(event), title=value, title_decided=True
        )
        return f"标题已设置为「{value}」。"

    def _type_set(self, event: AstrMessageEvent, task_type: str) -> str:
        value = str(task_type or "").strip()
        mapping = {
            "原创": "原创",
            "原创内容": "原创",
            "转载": "转载",
            "搬运": "转载",
            "转发": "转载",
        }
        normalized = mapping.get(value)
        if not normalized:
            return "内容类型只能是「原创」或「转载」。"
        self.config.update_draft(self._owner(event), task_type=normalized)
        return f"内容类型已设置为「{normalized}」。"

    async def _publish_options(self, event: AstrMessageEvent) -> str:
        owner = self._owner(event)
        draft = self.config.get_draft(owner)
        try:
            client = self._client(event)
            accounts = await client.list_accounts()
            templates = await client.list_templates()
        except PlatformAPIError as exc:
            return f"读取发布选项失败（先让用户处理登录）: {exc}"
        presets = self.config.list_presets(owner)
        active, _ = self.config.get_active_preset(owner)
        defaults = self._publish_defaults()
        lines = [
            "发布选项（用于向用户确认，不要替用户决定）",
            f"账号: {self._resolve_account_id(event, accounts) or '无可用账号'}",
            f"当前预设: {active or '未设置'}",
            "可选模板:",
        ]
        for item in templates[:10]:
            keys = "、".join(
                str(v.get("key"))
                for v in item.get("variables") or []
                if isinstance(v, dict) and v.get("key")
            )
            lines.append(
                f"- {item.get('id')} | {item.get('name')} | 变量: {keys or '无'}"
            )
        if presets:
            lines.append("可用发布预设:")
            for name, conf in sorted(presets.items()):
                lines.append(
                    f"- {name} | template={conf.get('template_id', '')} | "
                    f"title={conf.get('title', '')} | topic={conf.get('topic_name', '')}"
                )
        lines.append("卡片/环境默认值:")
        lines.append(f"- 模板: {defaults.get('template_id') or '未指定（默认 AstrBot 直发）'}")
        lines.append(f"- 标题: {defaults.get('title') or '空'}")
        lines.append(f"- 话题: {defaults.get('topic_name') or '空'}")
        lines.append(f"- 类型: {defaults.get('task_type')}")
        lines.append(
            "必填策略: 标题"
            + ("必填" if self._conf_bool("require_title", False) else "可选")
            + "、话题"
            + ("必填" if self._conf_bool("require_topic", False) else "可选")
        )
        if draft:
            lines.append(
                "当前草稿: 标题="
                + (str(draft.get("title")) or "空")
                + " 话题="
                + (str(draft.get("topic_name")) or "空")
                + " 图片="
                + str(len(draft.get("image_keys") or []))
                + " 张"
            )
        lines.append(
            "请把需要用户决定的部分（用哪个模板或预设、标题、话题标签、@提及、图片）"
            "用一句话问清楚；用户说不要的项就用 /bd title 无 或 /bd topic skip 记录。"
        )
        return "\n".join(lines)

    def _var_set(self, event: AstrMessageEvent, args: str) -> str:
        key, _, value = args.partition(" ")
        if not key or not _:
            return "用法: /bd var <变量> <值>"
        draft = self.config.get_draft(self._owner(event))
        variables = dict(draft.get("variables") or {})
        variables[key.strip()] = value.strip()
        required = [
            str(item) for item in draft.get("required_variables") or [] if item
        ]
        missing = [k for k in required if variables.get(k) in (None, "")]
        self.config.update_draft(
            self._owner(event), variables=variables, missing_variables=missing
        )
        if missing:
            return f"变量 {key} 已设置；还缺: " + "、".join(missing)
        return f"变量 {key} 已设置。"

    async def _topic_command(
        self, event: AstrMessageEvent, args: str
    ) -> str:
        action, _, rest = args.strip().partition(" ")
        owner = self._owner(event)
        if action == "skip":
            self.config.update_draft(
                owner, topic_id="", topic_name="", topic_decided=True
            )
            return "已记录：这条动态不绑定话题标签。"
        if action == "use":
            try:
                index = int(rest.strip())
            except ValueError:
                return "用法: /bd topic use <序号>"
            topics = self._topic_results.get(owner) or []
            if not 1 <= index <= len(topics):
                return "话题序号无效，请重新搜索。"
            topic = topics[index - 1]
            self.config.update_draft(
                owner,
                topic_id=str(topic.get("id") or ""),
                topic_name=str(topic.get("name") or ""),
                topic_decided=True,
            )
            return f"已绑定话题 #{topic.get('name')}#。"
        keyword = (rest if action not in ("search", "") else rest).strip() or args.strip()
        if not keyword:
            return "用法: /bd topic <关键词>"
        client = self._client(event)
        account_id = self._resolve_account_id(event, await client.list_accounts())
        topics = await client.search_topics(keyword, account_id)
        self._topic_results[owner] = topics[:10]
        if not topics:
            return "没有找到话题。"
        return "\n".join(
            f"{index}. {item.get('name')} | id={item.get('id')}"
            for index, item in enumerate(topics[:10], start=1)
        )

    async def _mention_command(
        self, event: AstrMessageEvent, args: str
    ) -> str:
        action, _, rest = args.strip().partition(" ")
        owner = self._owner(event)
        if action == "add":
            try:
                index = int(rest.strip())
            except ValueError:
                return "用法: /bd mention add <序号>"
            users = self._mention_results.get(owner) or []
            if not 1 <= index <= len(users):
                return "用户序号无效，请重新搜索。"
            user = users[index - 1]
            draft = self.config.get_draft(owner)
            mentions = list(draft.get("mentions") or [])
            uid = str(user.get("uid") or "")
            if uid and not any(str(item.get("uid")) == uid for item in mentions):
                mentions.append({"uid": uid, "name": str(user.get("name") or "")})
            self.config.update_draft(owner, mentions=mentions)
            return f"已添加 @{user.get('name')}。"
        keyword = (rest if action not in ("search", "") else rest).strip() or args.strip()
        if not keyword:
            return "用法: /bd mention <关键词>"
        client = self._client(event)
        account_id = self._resolve_account_id(event, await client.list_accounts())
        users = await client.search_mentions(keyword, account_id)
        self._mention_results[owner] = users[:10]
        if not users:
            return "没有找到用户。"
        return "\n".join(
            f"{index}. {item.get('name')} | uid={item.get('uid')}"
            for index, item in enumerate(users[:10], start=1)
        )

    async def _schedule(self, event: AstrMessageEvent, args: str) -> str:
        when, sep, text = args.partition("||")
        if not sep:
            return "用法: /bd schedule <时间> || <正文>"
        return await self._create(event, text.strip(), when.strip())

    async def _queue(self, event: AstrMessageEvent, args: str = "") -> str:
        status = args.strip().lower()
        allowed = {"pending", "publishing", "published", "failed", "canceled"}
        jobs = await self._client(event).list_jobs()
        if status:
            if status not in allowed:
                return "状态只能是 pending/publishing/published/failed/canceled。"
            jobs = [job for job in jobs if job.get("status") == status]
        if not jobs:
            return "平台没有符合条件的发布任务。"
        counts = {}
        for job in await self._client(event).list_jobs():
            item_status = str(job.get("status") or "unknown")
            counts[item_status] = counts.get(item_status, 0) + 1
        lines = [
            "380nm 发布队列 | "
            + " ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        ]
        for job in jobs[:30]:
            lines.append(
                f"- {job.get('id')} | {job.get('status')} | "
                f"{job.get('scheduledAt', '')} | "
                f"{(job.get('text') or '')[:30]}"
            )
        return "\n".join(lines)

    @staticmethod
    def _job_detail_text(job: dict) -> str:
        topic = job.get("topic") or {}
        mentions = job.get("mentions") or []
        images = job.get("images") or []
        return "\n".join(
            (
                "任务详情",
                f"ID: {job.get('id')}",
                f"状态: {job.get('status')}",
                f"计划: {job.get('scheduledAt')}",
                f"模板: {job.get('templateName')} ({job.get('templateId')})",
                f"账号: {job.get('accountName')} ({job.get('accountId')})",
                f"标题: {job.get('title') or '无'}",
                f"话题: {topic.get('name') or '无'}",
                f"@提及: {', '.join(item.get('name', '') for item in mentions) or '无'}",
                f"图片: {len(images)} 张",
                f"尝试次数: {job.get('attempts', 0)}",
                f"错误: {job.get('lastError') or '无'}",
                f"动态链接: {job.get('dynamicUrl') or '无'}",
                "",
                str(job.get("text") or ""),
            )
        )

    async def _job_command(self, event: AstrMessageEvent, args: str) -> str:
        job_id = args.strip()
        if not job_id:
            return "用法: /bd job <任务ID>"
        jobs = await self._client(event).list_jobs()
        job = next((item for item in jobs if str(item.get("id")) == job_id), None)
        if not job:
            return "任务不存在或不属于当前平台用户。"
        return self._job_detail_text(job)

    async def _job_edit(self, event: AstrMessageEvent, args: str) -> str:
        job_id, _, raw = args.strip().partition(" ")
        if not job_id or not raw:
            return "用法: /bd edit <任务ID> <JSON>"
        self._require_write(event)
        try:
            patch = json.loads(raw)
        except json.JSONDecodeError as exc:
            return f"JSON 格式错误: {exc}"
        if not isinstance(patch, dict):
            return "编辑内容必须是 JSON 对象。"
        client = self._client(event)
        job = next(
            (
                item
                for item in await client.list_jobs()
                if str(item.get("id")) == job_id
            ),
            None,
        )
        if job is None:
            return "任务不存在或不属于当前平台用户。"
        status = str(job.get("status") or "")
        if status in {"publishing", "published"}:
            return (
                f"任务 {job_id} 状态为 {status}，平台不允许编辑；"
                "可用 /bd duplicate <任务ID> 复制成新草稿。"
            )
        scheduled = patch.get("scheduledAt")
        if isinstance(scheduled, bool):
            return "计划时间格式不正确。"
        if isinstance(scheduled, (int, float)):
            seconds = float(scheduled)
            if seconds >= 10**12:
                seconds /= 1000.0
            patch["scheduledAt"] = datetime.fromtimestamp(
                seconds, tz=timezone.utc
            ).isoformat()
        elif isinstance(scheduled, str) and scheduled.strip():
            try:
                patch["scheduledAt"] = datetime.fromtimestamp(
                    self._parse_schedule(scheduled), tz=timezone.utc
                ).isoformat()
            except ValueError as exc:
                return f"计划时间无法解析: {exc}"
        await client.update_job(job_id, patch)
        return f"任务 {job_id} 已更新并重新排队。"

    async def _duplicate(self, event: AstrMessageEvent, args: str) -> str:
        job_id = args.strip()
        if not job_id:
            return "用法: /bd duplicate <任务ID>"
        jobs = await self._client(event).list_jobs()
        job = next((item for item in jobs if str(item.get("id")) == job_id), None)
        if not job:
            return "任务不存在或不属于当前平台用户。"
        topic = job.get("topic") or {}
        plan = {
            "text": str(job.get("text") or ""),
            "schedule": "",
            "account_id": str(job.get("accountId") or ""),
            "template_id": "",
            "template_name": "AstrBot 直发",
            "template_content": "{{text}}",
            "variables": {"text": str(job.get("text") or "")},
            "required_variables": ["text"],
            "missing_variables": [],
            "title": str(job.get("title") or ""),
            "topic_id": str(topic.get("id") or ""),
            "topic_name": str(topic.get("name") or ""),
            "mentions": list(job.get("mentions") or []),
            "task_type": str(job.get("type") or "原创"),
            "slots": job.get("slots") or {},
            "image_keys": list(job.get("images") or []),
            "preset_name": f"duplicate:{job_id}",
        }
        self.config.update_draft(self._owner(event), **plan)
        return self._preview_text(plan)

    async def _library(self, event: AstrMessageEvent, args: str) -> str:
        keyword = args.strip().lower()
        images = await self._client(event).list_images()
        if keyword:
            images = [
                image for image in images
                if keyword in str(image.get("name") or "").lower()
                or keyword in str(image.get("key") or "").lower()
            ]
        self._image_results[self._owner(event)] = images[:30]
        if not images:
            return "没有找到图片。"
        return "\n".join(
            f"{index}. {item.get('name')} | key={item.get('key')}"
            for index, item in enumerate(images[:30], start=1)
        )

    def _image_command(self, event: AstrMessageEvent, args: str) -> str:
        action, _, rest = args.strip().partition(" ")
        owner = self._owner(event)
        draft = self.config.get_draft(owner)
        images = list(draft.get("image_keys") or [])
        if action in ("", "list"):
            if not images:
                return "草稿没有图片。"
            return "\n".join(
                f"{index}. {item.get('name')} | key={item.get('key')}"
                for index, item in enumerate(images, start=1)
            )
        if action == "clear":
            self.config.update_draft(owner, image_keys=[])
            return "草稿图片已清空。"
        if action == "use":
            value = rest.strip()
            if not value:
                return "用法: /bd image use <序号|key>"
            selected = None
            if value.isdigit():
                candidates = self._image_results.get(owner) or []
                index = int(value)
                if 1 <= index <= len(candidates):
                    selected = candidates[index - 1]
            else:
                for image in self._image_results.get(owner) or []:
                    if str(image.get("key")) == value:
                        selected = image
                        break
            if not selected:
                return "找不到图片，请先 /bd library <关键词>。"
            merged = self._merge_plan_images(images, [selected])
            self.config.update_draft(owner, image_keys=merged)
            return f"已加入图片 {selected.get('name')}。"
        if action == "remove":
            key = rest.strip()
            self.config.update_draft(
                owner,
                image_keys=[item for item in images if str(item.get("key")) != key],
            )
            return f"已移除图片 {key}。"
        if action == "order":
            keys = [item.strip() for item in rest.split(",") if item.strip()]
            available = {str(item.get("key")): item for item in images}
            ordered = [available[key] for key in keys if key in available]
            if len(ordered) != len(keys):
                return "顺序中包含草稿里不存在的 key。"
            if len(ordered) != len(images):
                return "请列出草稿中的全部图片 key。"
            self.config.update_draft(owner, image_keys=ordered)
            return "图片顺序已更新。"
        return "用法: /bd image use|order|remove|clear|list"

    async def _job_action(
        self, event: AstrMessageEvent, job_id: str, action: str
    ) -> str:
        job_id = job_id.strip()
        if not job_id:
            return "请提供任务 ID。"
        self._require_write(event)
        self._check_rate(event, "job_action", 1.0)
        if action not in {"cancel", "publish-now", "retry", "delete"}:
            return "支持的操作: cancel/publish-now/retry/delete"
        client = self._client(event)
        owned = {str(job.get("id")) for job in await client.list_jobs()}
        if job_id not in owned:
            return "任务不存在或不属于当前平台用户。"
        if action == "cancel":
            await client.cancel_job(job_id)
        elif action == "publish-now":
            await client.publish_now(job_id)
        elif action == "retry":
            await client.retry_job(job_id)
        elif action == "delete":
            await client.delete_job(job_id)
        return f"任务 {job_id} 已执行操作: {action}。"

    async def _logs(self, event: AstrMessageEvent, args: str) -> str:
        try:
            limit = int(args.strip() or 20)
        except ValueError:
            limit = 20
        logs = await self._client(event).logs(limit)
        if not logs:
            return "平台没有日志。"
        return "\n".join(
            f"- {item.get('createdAt', '')} | {item.get('level')} | "
            f"{item.get('message', '')}"
            for item in logs[:limit]
        )

    def _resolve_account_id(
        self, event: AstrMessageEvent, accounts: list[dict]
    ) -> str:
        session = self.config.load_session(self._owner(event)) or {}
        preferred = session.get("account_id", "")
        if preferred and preferred in {item.get("id") for item in accounts}:
            return preferred
        return accounts[0].get("id", "") if accounts else ""

    def _max_upload_bytes(self) -> int:
        from_env = os.environ.get(
            "BILI_PLATFORM_MAX_UPLOAD_BYTES", str(PLATFORM_MAX_UPLOAD_BYTES)
        )
        try:
            fallback = int(from_env)
        except ValueError:
            fallback = PLATFORM_MAX_UPLOAD_BYTES
        configured = self._conf_int("max_upload_bytes", fallback)
        return max(1, min(configured, PLATFORM_MAX_UPLOAD_BYTES))

    @staticmethod
    def _sniff_image(data: bytes) -> tuple[str, str]:
        head = data[:12]
        if head.startswith(b"\xff\xd8\xff"):
            return "jpg", "image/jpeg"
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png", "image/png"
        if head.startswith(b"GIF8"):
            return "gif", "image/gif"
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return "webp", "image/webp"
        if head.startswith(b"BM"):
            return "bmp", "image/bmp"
        return "jpg", "image/jpeg"

    @staticmethod
    def _reply_message_id(event: AstrMessageEvent) -> str:
        components = getattr(getattr(event, "message_obj", None), "message", None) or []
        for component in components:
            if component.__class__.__name__.lower() == "reply":
                return str(getattr(component, "id", "") or "").strip()
        return ""

    async def _quoted_images(self, event: AstrMessageEvent) -> tuple[list[dict], str]:
        """引用消息里的图片：通过 OneBot get_msg 取回。"""

        reply_id = self._reply_message_id(event)
        if not reply_id:
            return [], ""
        if not reply_id.isdigit():
            return [], "引用的消息 ID 无法识别"
        bot = getattr(event, "bot", None)
        call_action = getattr(bot, "call_action", None)
        if not callable(call_action):
            return [], "当前平台无法读取引用消息里的图片"
        try:
            payload = await call_action("get_msg", message_id=int(reply_id))
        except Exception as exc:
            logger.debug("bili quoted get_msg failed: %r", exc)
            return [], "读取被引用的消息失败"
        segments = (payload or {}).get("message") or []
        images: list[dict] = []
        failed = 0
        for segment in segments:
            if not isinstance(segment, dict) or segment.get("type") != "image":
                continue
            data = segment.get("data") or {}
            url = str(data.get("url") or "")
            if not url and data.get("file"):
                try:
                    info = await call_action("get_image", file=str(data["file"]))
                    url = str((info or {}).get("url") or "")
                except Exception:
                    url = ""
            blob = await self._fetch_binary(url) if url else None
            if not blob:
                failed += 1
                continue
            suffix, content_type = self._sniff_image(blob)
            images.append(
                {
                    "filename": f"quoted_{len(images) + 1}.{suffix}",
                    "data": blob,
                    "content_type": content_type,
                }
            )
            if len(images) >= PLATFORM_MAX_IMAGES:
                break
        note = ""
        if not images and failed:
            note = "被引用的消息里有图片，但下载失败"
        elif not images and segments:
            note = "被引用的消息里没有图片"
        return images, note

    async def _collect_images(self, event: AstrMessageEvent) -> tuple[list[dict], str]:
        images = await self._extract_images(event)
        note = ""
        if len(images) < PLATFORM_MAX_IMAGES:
            quoted, note = await self._quoted_images(event)
            images.extend(quoted)
        return images[:PLATFORM_MAX_IMAGES], note

    async def _extract_images(self, event: AstrMessageEvent) -> list[dict]:
        result: list[dict] = []
        message_obj = getattr(event, "message_obj", None)
        components = getattr(message_obj, "message", None) or []
        for index, component in enumerate(components, start=1):
            name = component.__class__.__name__.lower()
            path = ""
            if "image" in name and hasattr(component, "convert_to_file_path"):
                try:
                    path = await component.convert_to_file_path()
                except Exception:
                    path = ""
            elif "file" in name and hasattr(component, "get_file"):
                try:
                    value = await component.get_file(allow_return_url=True)
                    path = value if Path(value).is_file() else ""
                except Exception:
                    path = ""
            if not path or not Path(path).is_file():
                continue
            suffix = Path(path).suffix.lower().lstrip(".") or "jpg"
            if suffix not in {"jpg", "jpeg", "png", "gif", "webp", "bmp"}:
                continue
            if Path(path).stat().st_size > self._max_upload_bytes():
                continue
            data = Path(path).read_bytes()
            content_type = {
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "png": "image/png",
                "gif": "image/gif",
                "webp": "image/webp",
                "bmp": "image/bmp",
            }.get(suffix, "image/jpeg")
            result.append(
                {
                    "filename": f"astrbot_{int(time.time())}_{index}.{suffix}",
                    "data": data,
                    "content_type": content_type,
                }
            )
        return result[:PLATFORM_MAX_IMAGES]

    @staticmethod
    def _parse_schedule(value: str, now: float | None = None) -> float:
        raw = value.strip()
        now = time.time() if now is None else now
        match = re.fullmatch(r"\+(\d+)([mhd])", raw.lower())
        if match:
            amount = int(match.group(1))
            return now + amount * {"m": 60, "h": 3600, "d": 86400}[match.group(2)]
        if re.fullmatch(r"\d{10,}", raw):
            return float(raw)
        natural = _cn_schedule(raw, now)
        if natural is not None:
            return natural
        day_offsets = {"今天": 0, "明天": 1, "后天": 2}
        for label, offset in day_offsets.items():
            match = re.fullmatch(rf"{label}\s*(\d{{1,2}})[:：](\d{{2}})", raw)
            if match:
                current = datetime.fromtimestamp(now)
                target = current.replace(
                    hour=int(match.group(1)),
                    minute=int(match.group(2)),
                    second=0,
                    microsecond=0,
                ) + timedelta(days=offset)
                if target.timestamp() <= now and offset == 0:
                    target += timedelta(days=1)
                return target.timestamp()
        weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
        match = re.fullmatch(r"下周([一二三四五六日天])\s*(\d{1,2})[:：](\d{2})", raw)
        if match:
            current = datetime.fromtimestamp(now)
            target = (
                current
                + timedelta(
                    days=(7 - current.weekday()) + weekday_map[match.group(1)]
                )
            ).replace(
                hour=int(match.group(2)),
                minute=int(match.group(3)),
                second=0,
                microsecond=0,
            )
            return target.timestamp()
        for parser in (
            lambda: datetime.fromisoformat(raw),
            lambda: datetime.strptime(raw, "%Y-%m-%d %H:%M"),
            lambda: datetime.strptime(raw, "%Y-%m-%d %H:%M:%S"),
        ):
            try:
                return parser().timestamp()
            except ValueError:
                continue
        match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
        if match:
            current = datetime.fromtimestamp(now)
            parsed = current.replace(
                hour=int(match.group(1)),
                minute=int(match.group(2)),
                second=0,
                microsecond=0,
            )
            if parsed.timestamp() <= now:
                parsed += timedelta(days=1)
            return parsed.timestamp()
        raise ValueError(
            "无法解析时间，请使用 +30m、+2h、明天上午八点、今晚8点、"
            "下周三晚上7点、明天08:00 或 2026-10-10 20:00"
        )

    def _notify_command(self, event: AstrMessageEvent, args: str) -> str:
        action = args.strip().lower() or "status"
        owner = self._owner(event)
        if action == "status":
            state = "开启" if self.config.get_notify(owner) else "关闭"
            origin = self.config.get_origin(owner)
            return (
                f"发布结果通知: {state}\n"
                f"通知会话: {origin or '未记录，请先执行一次 /bd 命令'}\n"
                "用法: /bd notify on|off"
            )
        if action in ("on", "off"):
            self.config.set_notify(owner, action == "on")
            if action == "on":
                self.config.set_origin(owner, event.unified_msg_origin)
            return f"发布结果通知已{'开启' if action == 'on' else '关闭'}。"
        return "用法: /bd notify on|off"

    async def _notify_loop(self) -> None:
        await asyncio.sleep(5)
        while True:
            for owner in self.config.list_owners():
                try:
                    await self._poll_notifications(owner)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("bili platform notification failed: %r", exc)
            interval = max(5, self._conf_int("notify_interval_seconds", 20))
            await asyncio.sleep(interval)

    async def _poll_notifications(self, owner: str) -> None:
        if not self._conf_bool("notify_enabled", True):
            return
        if not self.config.get_notify(owner):
            return
        session = self.config.load_session(owner)
        origin = self.config.get_origin(owner)
        if not session or not origin:
            return
        if self._is_shared(session) and origin not in self._shared_origins():
            return
        client = BiliPlatformClient(session["platform_url"], sid=session["sid"])
        try:
            jobs = await client.list_jobs()
        except PlatformAPIError as exc:
            if exc.status_code == 401:
                self.config.clear_session(owner)
                await self._notify_origin(origin, "380nm 平台会话已过期，请重新登录。")
            return
        current = {
            str(job.get("id")): str(job.get("status") or "")
            for job in jobs
        }
        previous = self._job_status.get(owner)
        if previous is not None:
            for job in jobs:
                job_id = str(job.get("id"))
                status = str(job.get("status") or "")
                if previous.get(job_id) == status:
                    continue
                if status == "published":
                    await self._notify_origin(
                        origin,
                        f"B站动态已发布 | 任务 {job_id} | {job.get('dynamicUrl') or ''}",
                    )
                elif status == "failed":
                    await self._notify_origin(
                        origin,
                        f"B站动态发布失败 | 任务 {job_id} | {job.get('lastError') or ''}",
                    )
        self._job_status[owner] = current

    async def _notify_origin(self, origin: str, text: str) -> None:
        sender = getattr(self.context, "send_message", None)
        if not callable(sender):
            return
        await sender(origin, MessageChain(chain=[Plain(text)]))

    # ---- LLM tools ----

    @filter.llm_tool(name="bili_platform_status")
    async def llm_status(self, event: AstrMessageEvent):
        """查看 380nm 平台登录状态、默认账号和待发布图片数量。

        Args:
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(lambda: self._status(event))

    @filter.llm_tool(name="bili_platform_upload")
    async def llm_upload(self, event: AstrMessageEvent):
        """把当前消息中的图片附件上传到 380nm 平台图库，供后续发布任务使用。

        Args:
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._upload(event))

    @filter.llm_tool(name="bili_platform_images")
    async def llm_images(self, event: AstrMessageEvent):
        """查看 380nm 平台图库图片数量。

        Args:
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._images(event))

    @filter.llm_tool(name="bili_platform_account_use")
    async def llm_account_use(self, event: AstrMessageEvent, account_id: str):
        """设置当前用户的默认 380nm 平台 B站账号。

        Args:
            account_id(string): 平台账号 ID
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._account_action(event, f"use {account_id}"))

    @filter.llm_tool(name="bili_platform_post")
    async def llm_post(
        self, event: AstrMessageEvent, text: str, schedule: str = "", preset: str = ""
    ):
        """在现有 380nm 平台创建一条发布任务。

        若用户没有说明标题/话题/图片，或按配置这些是必填而当前为空，本工具会拒绝创建并
        返回需要确认的清单；此时必须先向用户提问，拿到答复后再调用，不要重复提交。

        Args:
            text(string): 动态正文
            schedule(string): 计划时间；为空表示立即入队
            preset(string): 发布预设名称，可为空
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._create(event, text, schedule, preset))

    @filter.llm_tool(name="bili_platform_queue")
    async def llm_queue(self, event: AstrMessageEvent, status: str = ""):
        """查看 380nm 平台发布队列，可按状态筛选。

        Args:
            status(string): pending/publishing/published/failed/canceled，可为空
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._queue(event, status))

    @filter.llm_tool(name="bili_platform_job_detail")
    async def llm_job_detail(self, event: AstrMessageEvent, job_id: str):
        """查看 380nm 平台任务详情。

        Args:
            job_id(string): 平台任务 ID
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._job_command(event, job_id))

    @filter.llm_tool(name="bili_platform_job_edit")
    async def llm_job_edit(
        self, event: AstrMessageEvent, job_id: str, patch_json: str
    ):
        """编辑待发布任务并重新排队。

        Args:
            job_id(string): 平台任务 ID
            patch_json(string): 要修改字段的 JSON，如 {"text":"新正文","scheduledAt":"..."}
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._job_edit(event, f"{job_id} {patch_json}"))

    @filter.llm_tool(name="bili_platform_duplicate")
    async def llm_duplicate(self, event: AstrMessageEvent, job_id: str):
        """复制已有任务到草稿，供预览确认。

        Args:
            job_id(string): 平台任务 ID
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._duplicate(event, job_id))

    @filter.llm_tool(name="bili_platform_import")
    async def llm_import(
        self, event: AstrMessageEvent, url: str, text: str = ""
    ):
        """调用 380nm 平台接口导入 Pixiv/X/Danbooru 链接图片。

        Args:
            url(string): 作品或图片链接
            text(string): 导入后的正文，可为空
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._import_link(event, f"{url} || {text}".strip()))

    @filter.llm_tool(name="bili_platform_library")
    async def llm_library(self, event: AstrMessageEvent, keyword: str = ""):
        """搜索 380nm 平台图库。

        Args:
            keyword(string): 文件名或 key 关键词，可为空
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._library(event, keyword))

    @filter.llm_tool(name="bili_platform_image_action")
    async def llm_image_action(
        self, event: AstrMessageEvent, action: str, value: str = ""
    ):
        """对草稿图片执行 use/order/remove/clear/list 操作。

        Args:
            action(string): use/order/remove/clear/list
            value(string): 图片序号、key 或逗号分隔的 key 顺序
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(lambda: self._image_command(event, f"{action} {value}".strip()))

    @filter.llm_tool(name="bili_platform_accounts")
    async def llm_accounts(self, event: AstrMessageEvent):
        """查看 380nm 平台已绑定的 B站账号。

        Args:
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._accounts(event))

    @filter.llm_tool(name="bili_platform_templates")
    async def llm_templates(self, event: AstrMessageEvent):
        """查看 380nm 平台模板列表。

        Args:
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._templates(event))

    @filter.llm_tool(name="bili_platform_job_action")
    async def llm_job_action(
        self, event: AstrMessageEvent, job_id: str, action: str
    ):
        """对 380nm 平台任务执行取消、立即发布、重试或删除。

        Args:
            job_id(string): 平台任务 ID
            action(string): cancel/publish-now/retry/delete
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._job_action(event, job_id, action))

    @filter.llm_tool(name="bili_platform_logs")
    async def llm_logs(self, event: AstrMessageEvent, limit: int = 20):
        """查看 380nm 平台最近日志。

        Args:
            limit(number): 返回条数
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._logs(event, str(limit)))
    @filter.llm_tool(name="bili_platform_preview")
    async def llm_preview(
        self, event: AstrMessageEvent, text: str, schedule: str = ""
    ):
        """预览发布内容并保存为草稿，不写入平台。

        返回内容会列出当前缺哪些信息（正文/标题/话题标签/图片/@提及）；有必填缺项时
        先向用户确认，不要直接调用 bili_platform_confirm。
        缺项为空时会同时给用户发一张渲染好的预览卡片（标题/账号/时间/编号/话题/正文/图片）。

        Args:
            text(string): 动态正文
            schedule(string): 计划时间，可为空
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._preview(event, text, schedule))

    @filter.llm_tool(name="bili_platform_confirm")
    async def llm_confirm(self, event: AstrMessageEvent):
        """确认当前草稿并在 380nm 平台创建发布任务。

        草稿缺少必填信息时会拒绝创建并返回需要向用户确认的清单。

        Args:
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._confirm(event))

    @filter.llm_tool(name="bili_platform_publish_options")
    async def llm_publish_options(self, event: AstrMessageEvent):
        """查看本次发布可选的模板、发布预设和当前默认值；信息不全时先调用它再向用户提问。

        Args:
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._publish_options(event))

    @filter.llm_tool(name="bili_platform_set_title")
    async def llm_set_title(self, event: AstrMessageEvent, title: str):
        """设置草稿的动态标题。用户回答标题后调用；用户明确不要标题时传「无」。

        Args:
            title(string): 动态标题（最多 20 字），或「无」表示不要标题
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(lambda: self._title_set(event, title))

    @filter.llm_tool(name="bili_platform_set_type")
    async def llm_set_type(self, event: AstrMessageEvent, task_type: str):
        """设置草稿的内容类型（原创/转载）。

        Args:
            task_type(string): 原创 或 转载
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(lambda: self._type_set(event, task_type))

    @filter.llm_tool(name="bili_platform_set_var")
    async def llm_set_var(self, event: AstrMessageEvent, key: str, value: str):
        """设置草稿的模板变量，供模板渲染使用。

        Args:
            key(string): 变量名
            value(string): 变量值
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(lambda: self._var_set(event, f"{key} {value}"))

    @filter.llm_tool(name="bili_platform_topic_search")
    async def llm_topic_search(self, event: AstrMessageEvent, keyword: str):
        """搜索 B站话题。

        Args:
            keyword(string): 话题关键词
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._topic_command(event, keyword))

    @filter.llm_tool(name="bili_platform_topic_use")
    async def llm_topic_use(self, event: AstrMessageEvent, index: int):
        """把话题搜索结果中的第 N 条绑定到草稿。

        Args:
            index(number): 搜索结果的序号，从 1 开始
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._topic_command(event, f"use {int(index)}"))

    @filter.llm_tool(name="bili_platform_mention_search")
    async def llm_mention_search(self, event: AstrMessageEvent, keyword: str):
        """搜索可以 @ 的 B站用户。

        Args:
            keyword(string): 用户关键词
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._mention_command(event, keyword))

    @filter.llm_tool(name="bili_platform_mention_add")
    async def llm_mention_add(self, event: AstrMessageEvent, index: int):
        """把用户搜索结果中的第 N 条加入草稿 @ 列表。

        Args:
            index(number): 搜索结果的序号，从 1 开始
        """
        try:
            self._check_shared_access(event, self.config.load_session(self._owner(event)))
        except PlatformAPIError as exc:
            yield str(exc)
            return
        yield await self._llm(self._mention_command(event, f"add {int(index)}"))
