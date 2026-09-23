import asyncio
import inspect
from concurrent.futures import ThreadPoolExecutor
from threading import get_ident

from backend.async_runtime import bridge_api


def test_concurrent_sync_callers_share_one_event_loop_thread() -> None:
    @bridge_api
    class Bridge:
        async def _shutdown_bridge(self) -> None:
            return None

        async def identify_async(self, _call_number: int) -> tuple[int, int]:
            await asyncio.sleep(0)
            return get_ident(), id(asyncio.get_running_loop())

        def identify_sync(self, _call_number: int) -> tuple[int, int]:
            return get_ident(), id(asyncio.get_running_loop())

    bridge = Bridge()
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            async_results = list(executor.map(bridge.identify_async, range(8)))
            sync_results = list(executor.map(bridge.identify_sync, range(8)))
    finally:
        bridge._close_bridge()

    assert not inspect.iscoroutinefunction(Bridge.identify_async)
    assert len(set(async_results + sync_results)) == 1
