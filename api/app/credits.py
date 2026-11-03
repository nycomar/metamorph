"""Render credit guard: per-IP and global counters stored in SQLite."""
from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass

from fastapi import Request

from .config import settings

HOUR_S = 3600.0
DAY_S = 86400.0


def client_ip(request: Request) -> str:
    """Real client IP, trusting the reverse proxy's forwarded headers."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    return request.client.host if request.client else "unknown"


@dataclass
class CreditDecision:
    allowed: bool
    retry_after_s: int = 0
    error: str = ""


def check_and_record(
    conn: sqlite3.Connection,
    ip: str,
    now: float | None = None,
) -> CreditDecision:
    """Atomically check both windows and record one render if admitted."""
    now = time.time() if now is None else now
    per_ip_limit = max(0, int(settings.render_per_ip_hour))
    global_limit = max(0, int(settings.render_global_day))

    with conn:
        conn.execute("DELETE FROM render_events WHERE created_at < ?", (now - DAY_S,))

        ip_count = conn.execute(
            "SELECT COUNT(*) FROM render_events WHERE ip=? AND created_at >= ?",
            (ip, now - HOUR_S),
        ).fetchone()[0]
        global_count = conn.execute(
            "SELECT COUNT(*) FROM render_events WHERE created_at >= ?",
            (now - DAY_S,),
        ).fetchone()[0]

        if ip_count >= per_ip_limit:
            oldest = conn.execute(
                "SELECT MIN(created_at) FROM render_events WHERE ip=? AND created_at >= ?",
                (ip, now - HOUR_S),
            ).fetchone()[0]
            retry = max(1, math.ceil((oldest or now) + HOUR_S - now))
            return CreditDecision(
                allowed=False,
                retry_after_s=retry,
                error=f"render limit reached: {per_ip_limit} per hour from this IP",
            )

        if global_count >= global_limit:
            oldest = conn.execute(
                "SELECT MIN(created_at) FROM render_events WHERE created_at >= ?",
                (now - DAY_S,),
            ).fetchone()[0]
            retry = max(1, math.ceil((oldest or now) + DAY_S - now))
            return CreditDecision(
                allowed=False,
                retry_after_s=retry,
                error=f"global render limit reached: {global_limit} per 24 hours",
            )

        conn.execute(
            "INSERT INTO render_events (ip, created_at) VALUES (?, ?)",
            (ip, now),
        )
    return CreditDecision(allowed=True)
