"""Encrypted local session configuration for the 380nm auxiliary plugin."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any

try:
    from cryptography.fernet import Fernet
except Exception as exc:  # pragma: no cover
    Fernet = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class AuxConfigError(ValueError):
    """Configuration is invalid or cryptography is unavailable."""


class AuxConfigManager:
    def __init__(self, data_dir: str | os.PathLike = "data/bili_platform_aux") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
        self._lock = threading.RLock()
        self._fernet = self._load_crypto()
        self._state: dict[str, Any] = {"version": 1, "users": {}}
        self._load()

    def _load_crypto(self):
        if Fernet is None:
            raise AuxConfigError(
                "缺少 cryptography，无法保存平台 sid Cookie；请先安装依赖"
            )
        external = os.environ.get("BILI_PLATFORM_AUX_SECRET_KEY", "").strip()
        if external:
            key = hashlib.sha256(external.encode("utf-8")).digest()
            return Fernet(base64.urlsafe_b64encode(key))
        path = self.data_dir / "secret.key"
        if path.exists():
            key = path.read_bytes()
        else:
            key = secrets.token_bytes(32)
            path.write_bytes(key)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        return Fernet(base64.urlsafe_b64encode(key))

    def _load(self) -> None:
        path = self.data_dir / "state.json"
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AuxConfigError("本地平台会话配置损坏") from exc
        if isinstance(payload, dict):
            self._state = {"version": 1, "users": payload.get("users") or {}}

    def save(self) -> None:
        path = self.data_dir / "state.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    def _user(self, owner_id: str) -> dict:
        user = self._state.setdefault("users", {}).setdefault(
            str(owner_id), {}
        )
        user.setdefault("pending_images", [])
        user.setdefault("presets", {})
        user.setdefault("active_preset", "")
        user.setdefault("draft", {})
        user.setdefault("notify", True)
        return user

    def list_owners(self) -> list[str]:
        with self._lock:
            return [
                str(owner)
                for owner, record in (self._state.get("users") or {}).items()
                if record.get("sid_enc")
            ]

    def set_origin(self, owner_id: str, origin: str) -> None:
        with self._lock:
            self._user(owner_id)["origin"] = str(origin or "")
            self.save()

    def get_origin(self, owner_id: str) -> str:
        with self._lock:
            return str(self._user(owner_id).get("origin") or "")

    def set_notify(self, owner_id: str, enabled: bool) -> None:
        with self._lock:
            self._user(owner_id)["notify"] = bool(enabled)
            self.save()

    def get_notify(self, owner_id: str) -> bool:
        with self._lock:
            return bool(self._user(owner_id).get("notify", True))

    def save_session(
        self,
        owner_id: str,
        *,
        platform_url: str,
        username: str,
        sid: str,
        user: dict | None = None,
        shared: bool = False,
    ) -> None:
        with self._lock:
            record = self._user(owner_id)
            record.update(
                {
                    "platform_url": platform_url,
                    "username": username,
                    "sid_enc": self._fernet.encrypt(sid.encode("utf-8")).decode("ascii"),
                    "user": user or {},
                    "shared": shared,
                }
            )
            self.save()

    def load_session(self, owner_id: str) -> dict | None:
        with self._lock:
            record = self._user(owner_id)
            token = record.get("sid_enc")
            if not token:
                return None
            try:
                sid = self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
            except Exception as exc:
                raise AuxConfigError("平台 sid 解密失败，请重新登录") from exc
            return {
                "platform_url": record.get("platform_url", ""),
                "username": record.get("username", ""),
                "sid": sid,
                "user": record.get("user") or {},
                "account_id": record.get("account_id", ""),
                "shared": bool(record.get("shared", False)),
            }

    def clear_session(self, owner_id: str) -> None:
        with self._lock:
            self._state.setdefault("users", {}).pop(str(owner_id), None)
            self.save()

    def set_default_account(self, owner_id: str, account_id: str) -> None:
        with self._lock:
            self._user(owner_id)["account_id"] = str(account_id)
            self.save()

    def get_pending_images(self, owner_id: str) -> list[dict]:
        with self._lock:
            return [dict(item) for item in self._user(owner_id).get("pending_images") or []]

    def get_draft(self, owner_id: str) -> dict:
        with self._lock:
            return dict(self._user(owner_id).get("draft") or {})

    def update_draft(self, owner_id: str, **fields: Any) -> dict:
        with self._lock:
            draft = self._user(owner_id).setdefault("draft", {})
            draft.update(fields)
            self.save()
            return dict(draft)

    def clear_draft(self, owner_id: str) -> None:
        with self._lock:
            self._user(owner_id)["draft"] = {}
            self.save()

    def set_pending_images(self, owner_id: str, images: list[dict]) -> None:
        with self._lock:
            self._user(owner_id)["pending_images"] = list(images)[:9]
            self.save()

    def pop_pending_images(self, owner_id: str) -> list[dict]:
        with self._lock:
            record = self._user(owner_id)
            images = list(record.get("pending_images") or [])
            record["pending_images"] = []
            self.save()
            return images[:9]

    def list_presets(self, owner_id: str) -> dict:
        with self._lock:
            user = self._user(owner_id)
            return {
                name: dict(value)
                for name, value in user.get("presets", {}).items()
            }

    def set_preset(self, owner_id: str, name: str, config: dict) -> None:
        name = str(name or "").strip()
        if not name:
            raise AuxConfigError("预设名称不能为空")
        if not isinstance(config, dict):
            raise AuxConfigError("预设配置必须是对象")
        with self._lock:
            self._user(owner_id).setdefault("presets", {})[name] = dict(config)
            self.save()

    def remove_preset(self, owner_id: str, name: str) -> None:
        with self._lock:
            user = self._user(owner_id)
            user.setdefault("presets", {}).pop(str(name), None)
            if user.get("active_preset") == str(name):
                user["active_preset"] = ""
            self.save()

    def set_active_preset(self, owner_id: str, name: str) -> None:
        with self._lock:
            user = self._user(owner_id)
            name = str(name or "").strip()
            if name and name not in user.get("presets", {}):
                raise AuxConfigError("找不到该预设")
            user["active_preset"] = name
            self.save()

    def get_active_preset(self, owner_id: str) -> tuple[str, dict]:
        with self._lock:
            user = self._user(owner_id)
            name = str(user.get("active_preset") or "")
            if not name:
                return "", {}
            return name, dict((user.get("presets") or {}).get(name) or {})

    def status(self, owner_id: str) -> dict:
        session = self.load_session(owner_id)
        if not session:
            return {"logged_in": False, "pending_images": 0}
        return {
            "logged_in": True,
            "platform_url": session["platform_url"],
            "username": session["username"],
            "user": session["user"],
            "account_id": session["account_id"],
            "pending_images": len(self._user(owner_id).get("pending_images") or []),
            "active_preset": self._user(owner_id).get("active_preset", ""),
            "notify": bool(self._user(owner_id).get("notify", True)),
        }
