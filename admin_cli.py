"""Server-side helper for managing 380nm auxiliary plugin sessions."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
from pathlib import Path
from urllib.parse import urlparse

from config_manager import AuxConfigManager
from platform_client import (
    BiliPlatformClient,
    DEFAULT_PLATFORM_URL,
    normalize_platform_url,
    normalize_sid,
)


def _data_dir() -> str:
    return os.environ.get(
        "BILI_PLATFORM_AUX_DATA_DIR", "data/bili_platform_aux"
    )


def _validate_url(value: str) -> str:
    url = normalize_platform_url(value)
    parsed = urlparse(url)
    allowed = {
        item.strip().lower()
        for item in os.environ.get(
            "BILI_PLATFORM_ALLOWED_HOSTS", "bilidyn.basmc.org"
        ).split(",")
        if item.strip()
    }
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" and host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("平台地址必须使用 HTTPS")
    if allowed and host not in allowed:
        raise SystemExit("平台地址不在 BILI_PLATFORM_ALLOWED_HOSTS 中")
    return url


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    set_session = sub.add_parser("set-session")
    set_session.add_argument("--owner", required=True)
    set_session.add_argument("--sid", default="")
    set_session.add_argument(
        "--platform-url",
        default=os.environ.get("BILI_PLATFORM_URL", DEFAULT_PLATFORM_URL),
    )
    set_session.add_argument("--username", default="")
    clear = sub.add_parser("clear-session")
    clear.add_argument("--owner", required=True)
    status = sub.add_parser("status")
    status.add_argument("--owner", default="")
    args = parser.parse_args()

    config = AuxConfigManager(_data_dir())
    if args.command == "set-session":
        sid = normalize_sid(
            args.sid or os.environ.get("BILI_PLATFORM_SID", "")
        )
        if not sid:
            sid = normalize_sid(getpass.getpass("平台 sid: "))
        if not sid:
            raise SystemExit("sid 不能为空")
        platform_url = _validate_url(args.platform_url)
        client = BiliPlatformClient(platform_url, sid=sid)
        user = asyncio.run(client.me())
        config.save_session(
            args.owner,
            platform_url=platform_url,
            username=args.username or str(user.get("username") or ""),
            sid=sid,
            user=user,
        )
        print(f"session saved for owner={args.owner} platform={platform_url}")
        return 0
    if args.command == "clear-session":
        config.clear_session(args.owner)
        print(f"session cleared for owner={args.owner}")
        return 0
    if args.command == "status":
        if args.owner:
            session = config.load_session(args.owner)
            print("logged_in" if session else "not_logged_in")
        else:
            users = config._state.get("users", {})
            print(f"owners={len(users)}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())