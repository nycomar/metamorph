"""Thin async client for Comfy Cloud.

Uses the documented HTTP surface (submit / status / view) so the app depends on a
stable contract rather than on MCP tool shapes. The official SDK (comfy-sdk) is
installed as well and can replace these calls where it is more convenient.
"""
from __future__ import annotations

from typing import Any

import httpx


class CloudError(RuntimeError):
    pass


class CloudClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = {"X-API-Key": api_key}
        self._timeout = timeout

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, headers=self._headers, timeout=self._timeout)

    async def whoami(self) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.get("/api/user")
            if r.status_code != 200:
                raise CloudError(f"auth failed: HTTP {r.status_code}")
            return r.json()

    async def object_info(self) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.get("/api/object_info")
            r.raise_for_status()
            return r.json()

    async def upload_image(self, path: str, name: str) -> dict[str, Any]:
        async with await self._client() as c:
            with open(path, "rb") as fh:
                r = await c.post(
                    "/api/upload/image",
                    files={"image": (name, fh, "image/png")},
                    data={"overwrite": "true"},
                )
            if r.status_code != 200:
                raise CloudError(f"upload failed: HTTP {r.status_code} {r.text[:200]}")
            return r.json()

    async def submit(self, prompt: dict[str, Any]) -> str:
        async with await self._client() as c:
            r = await c.post("/api/prompt", json={"prompt": prompt})
            if r.status_code != 200:
                raise CloudError(f"submit failed: HTTP {r.status_code} {r.text[:400]}")
            return r.json()["prompt_id"]

    async def status(self, prompt_id: str) -> dict[str, Any]:
        async with await self._client() as c:
            r = await c.get(f"/api/job/{prompt_id}/status")
            r.raise_for_status()
            return r.json()

    async def download_view(self, filename: str, subfolder: str = "", kind: str = "output", dest: str = "") -> str:
        """Fetch an output. The key must NOT follow the 302 to storage."""
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as c:
            r = await c.get(
                f"{self.base_url}/api/view",
                params={"filename": filename, "subfolder": subfolder, "type": kind},
                headers=self._headers,
            )
            if r.status_code in (301, 302, 307, 308):
                signed = r.headers["location"]
            elif r.status_code == 200:
                signed = str(r.url)
                open(dest, "wb").write(r.content)
                return dest
            else:
                raise CloudError(f"view failed: HTTP {r.status_code}")
        async with httpx.AsyncClient(timeout=self._timeout) as c2:
            r2 = await c2.get(signed)
            r2.raise_for_status()
            open(dest, "wb").write(r2.content)
        return dest
