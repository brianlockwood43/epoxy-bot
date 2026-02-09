from __future__ import annotations

import asyncio


async def announcement_loop(
    *,
    bot,
    announcement_service,
    interval_seconds: int = 30,
) -> None:
    while True:
        try:
            await announcement_service.run_tick(bot)
        except Exception as e:
            print(f"[Announcements] loop error: {e}")
        await asyncio.sleep(max(10, int(interval_seconds)))
