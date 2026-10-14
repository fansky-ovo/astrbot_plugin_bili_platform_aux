"""Client for the existing 380nm Bilibili dynamic web platform."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_PLATFORM_URL = "https://bilidyn.basmc.org"
QUICK_TEMPLATE_NAME = "AstrBot 直发"


class PlatformAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int = 0) -> None:
        self.status_code = status_code
        super().__init__(message)


def normalize_sid(value: str) -> str:
    """接受纯值、`sid=值`、带引号的值或整条 Cookie 字符串，返回纯 sid 值。"""

    text = str(value or "").strip().strip('"').strip("'").strip()
    if not text:
        return ""
    if "=" in text:
        for part in text.split(";"):
            name, sep, candidate = part.partition("=")
            if sep and name.strip().lower() == "sid":
                return candidate.strip().strip('"').strip("'").strip()
    return text


def normalize_platform_url(value: str) -> str:
    raw = str(value or "").strip() or DEFAULT_PLATFORM_URL
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if not parsed.netloc:
        raise PlatformAPIError("平台地址无效")
    return f"{parsed.scheme}://{parsed.netloc}"


class BiliPlatformClient:
    def __init__(
        self,
        platform_url: str = DEFAULT_PLATFORM_URL,
        *,
        sid: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.platform_url = normalize_platform_url(platform_url)
        self.api_base = self.platform_url + "/api"
        self.sid = normalize_sid(sid)
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.api_base,
            timeout=httpx.Timeout(30.0, connect=8.0),
            follow_redirects=True,
            transport=self._transport,
            cookies={"sid": self.sid} if self.sid else None,
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        # 只对 GET 重试：POST/PUT/DELETE 重放可能重复建任务
        attempts = 3 if method.upper() == "GET" else 1
        response = None
        for attempt in range(attempts):
            try:
                async with self._client() as client:
                    response = await client.request(method, path, **kwargs)
                break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt + 1 >= attempts:
                    raise PlatformAPIError(
                        "平台连接超时或不可达（已重试），请稍后再试", 0
                    ) from exc
                await asyncio.sleep(0.6 * (attempt + 1))
        if response is None:  # pragma: no cover - 兜底
            raise PlatformAPIError("平台请求失败，请稍后再试", 0)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code == 401:
            raise PlatformAPIError("平台会话已过期，请重新登录", 401)
        if response.status_code >= 400:
            message = (
                payload.get("error") if isinstance(payload, dict) else ""
            ) or f"HTTP {response.status_code}"
            raise PlatformAPIError(str(message), response.status_code)
        return payload

    async def login(self, username: str, password: str) -> dict:
        async with self._client() as client:
            response = await client.post(
                "/auth/login",
                json={"username": username, "password": password},
            )
        if response.status_code >= 400:
            try:
                message = response.json().get("error")
            except ValueError:
                message = ""
            raise PlatformAPIError(
                str(message or "登录失败"), response.status_code
            )
        sid = response.cookies.get("sid") or ""
        if not sid:
            for header in response.headers.get_list("set-cookie"):
                if header.lower().startswith("sid="):
                    sid = header.split("=", 1)[1].split(";", 1)[0]
                    break
        if not sid:
            raise PlatformAPIError("平台登录成功但未返回 sid Cookie")
        self.sid = sid
        payload = response.json()
        return {"sid": sid, "user": payload.get("user") or {}}

    async def me(self) -> dict:
        payload = await self._request("GET", "/auth/me")
        return payload.get("user") or {}

    async def logout(self) -> None:
        if not self.sid:
            return
        try:
            await self._request("POST", "/auth/logout")
        finally:
            self.sid = ""

    async def list_accounts(self) -> list[dict]:
        payload = await self._request("GET", "/accounts")
        return payload.get("accounts") or []

    async def list_templates(self) -> list[dict]:
        payload = await self._request("GET", "/templates")
        return payload.get("templates") or []

    async def create_template(
        self, name: str, content: str, variables: list[dict], max_images: int = 9
    ) -> dict:
        payload = await self._request(
            "POST",
            "/templates",
            json={
                "name": name,
                "content": content,
                "variables": variables,
                "maxImages": max_images,
            },
        )
        return payload.get("template") or {}

    async def ensure_quick_template(self) -> dict:
        for template in await self.list_templates():
            if template.get("name") == QUICK_TEMPLATE_NAME:
                return template
        return await self.create_template(
            QUICK_TEMPLATE_NAME,
            "{{text}}",
            [{"key": "text", "label": "正文"}],
            9,
        )

    async def list_images(self) -> list[dict]:
        payload = await self._request("GET", "/images")
        return payload.get("images") or []

    async def upload_images(self, images: list[dict]) -> list[dict]:
        files = []
        for image in images:
            files.append(
                (
                    "files",
                    (
                        image.get("filename") or "image.jpg",
                        image.get("data") or b"",
                        image.get("content_type") or "image/jpeg",
                    ),
                )
            )
        if not files:
            return []
        payload = await self._request("POST", "/upload", files=files)
        return payload.get("images") or []

    async def search_topics(self, keyword: str, account_id: str = "") -> list[dict]:
        params = {"keywords": keyword}
        if account_id:
            params["accountId"] = account_id
        payload = await self._request("GET", "/topics/search", params=params)
        return payload.get("topics") or []

    async def search_mentions(self, keyword: str, account_id: str = "") -> list[dict]:
        params = {"keywords": keyword}
        if account_id:
            params["accountId"] = account_id
        payload = await self._request("GET", "/mentions/search", params=params)
        return payload.get("users") or []

    async def import_library_link(self, url: str, folder_id: str = "") -> dict:
        payload = {"url": url}
        if folder_id:
            payload["folderId"] = folder_id
        result = await self._request("POST", "/library/import", json=payload)
        return {
            "images": result.get("images") or [],
            "total": int(result.get("total") or 0),
        }

    async def list_jobs(self) -> list[dict]:
        payload = await self._request("GET", "/jobs")
        return payload.get("jobs") or []

    async def create_job(
        self,
        *,
        template_id: str,
        account_id: str,
        variables: dict,
        images: list[dict] | None = None,
        scheduled_at: float | None = None,
        topic: dict | None = None,
        title: str = "",
        mentions: list[dict] | None = None,
        task_type: str = "原创",
        slots: dict | None = None,
    ) -> dict:
        when = (
            datetime.fromtimestamp(scheduled_at, tz=timezone.utc).isoformat()
            if scheduled_at is not None
            else datetime.now(tz=timezone.utc).isoformat()
        )
        payload = await self._request(
            "POST",
            "/jobs",
            json={
                "templateId": template_id,
                "accountId": account_id,
                "variables": variables,
                "images": images or [],
                "scheduledAt": when,
                "topic": topic,
                "title": title,
                "mentions": mentions or [],
                "type": task_type,
                "slots": slots or {},
            },
        )
        return payload.get("job") or {}

    async def update_job(self, job_id: str, patch: dict) -> dict:
        payload = await self._request("PUT", f"/jobs/{job_id}", json=patch)
        return payload.get("job") or {}

    async def cancel_job(self, job_id: str) -> dict:
        payload = await self._request("POST", f"/jobs/{job_id}/cancel")
        return payload.get("job") or {}

    async def publish_now(self, job_id: str) -> dict:
        payload = await self._request("POST", f"/jobs/{job_id}/publish-now")
        return payload.get("job") or {}

    async def retry_job(self, job_id: str) -> dict:
        payload = await self._request("POST", f"/jobs/{job_id}/retry")
        return payload.get("job") or {}

    async def delete_job(self, job_id: str) -> None:
        await self._request("DELETE", f"/jobs/{job_id}")

    async def logs(self, limit: int = 50) -> list[dict]:
        payload = await self._request(
            "GET", "/logs", params={"limit": min(500, max(1, limit))}
        )
        return payload.get("logs") or []