"""One in-process worker: claims queued jobs, runs them, survives restarts."""
from __future__ import annotations

import asyncio
import logging
import sqlite3

log = logging.getLogger("worker")


class Worker:
    def __init__(self, conn: sqlite3.Connection, handlers: dict, concurrency: int = 1) -> None:
        self.conn = conn
        self.handlers = handlers
        self.sem = asyncio.Semaphore(concurrency)
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        # anything left running when the process died is requeued, not lost
        self.conn.execute("UPDATE jobs SET state='queued' WHERE state='running'")
        self.conn.commit()
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            row = self.conn.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                await asyncio.sleep(1.5)
                continue
            await self.sem.acquire()
            asyncio.create_task(self._run(row))

    async def _run(self, row: sqlite3.Row) -> None:
        try:
            self._set_state(row["id"], "running")
            handler = self.handlers.get(row["kind"])
            if handler is None:
                raise RuntimeError(f"no handler for {row['kind']}")
            await handler(row)
            self._set_state(row["id"], "done", progress=1.0)
        except Exception as exc:  # noqa: BLE001
            log.exception("job %s failed", row["id"])
            self._set_state(row["id"], "error", error=str(exc)[:500])
        finally:
            self.sem.release()

    def _set_state(self, job_id: str, state: str, **fields) -> None:
        sets = ["state=?", "updated_at=datetime('now')"]
        vals: list = [state]
        for k, v in fields.items():
            sets.append(f"{k}=?")
            vals.append(v)
        vals.append(job_id)
        self.conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", vals)
        self.conn.commit()
