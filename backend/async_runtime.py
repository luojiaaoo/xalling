"""Run application coroutines on one event-loop thread."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from functools import partial, wraps
from threading import Lock, get_ident
from typing import Any, Self, cast

from anyio.from_thread import BlockingPortal, start_blocking_portal


class AsyncRuntime:
    """Bridge synchronous pywebview calls to one shared async runtime."""

    def __init__(self, name: str = "xalling-async") -> None:
        self._state_lock = Lock()
        self._portal_context: AbstractContextManager[BlockingPortal] | None = (
            start_blocking_portal(name=name)
        )
        self._portal: BlockingPortal | None = self._portal_context.__enter__()
        self._thread_id = self._portal.call(get_ident)

    def call[**P, T](
        self,
        function: Callable[P, Awaitable[T]],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """Run an async function on the shared loop and wait for its result."""
        if get_ident() == self._thread_id:
            raise RuntimeError("不能从异步运行时线程同步等待协程")
        portal = self._require_portal()
        return portal.call(partial(function, *args, **kwargs))

    def call_sync[**P, T](
        self,
        function: Callable[P, T],
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """Run a short synchronous state mutation on the shared loop."""
        if get_ident() == self._thread_id:
            return function(*args, **kwargs)
        portal = self._require_portal()
        return portal.call(partial(function, *args, **kwargs))

    def close(self) -> None:
        """Stop the portal after application-owned tasks have been closed."""
        with self._state_lock:
            portal_context = self._portal_context
            self._portal_context = None
            self._portal = None
        if portal_context is not None:
            portal_context.__exit__(None, None, None)

    def _require_portal(self) -> BlockingPortal:
        with self._state_lock:
            portal = self._portal
        if portal is None:
            raise RuntimeError("异步运行时已经关闭")
        return portal

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _wrap_instance_method(function: Callable[..., Any]) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(function):

        @wraps(function)
        def async_bridge_method(self: Any, *args: Any, **kwargs: Any) -> Any:
            return self._async_runtime.call(function, self, *args, **kwargs)

        return async_bridge_method

    @wraps(function)
    def sync_bridge_method(self: Any, *args: Any, **kwargs: Any) -> Any:
        return self._async_runtime.call_sync(function, self, *args, **kwargs)

    return sync_bridge_method


def _wrap_static_method(function: Callable[..., Any]) -> Callable[..., Any]:
    def bridge_method(self: Any, *args: Any, **kwargs: Any) -> Any:
        if inspect.iscoroutinefunction(function):
            return self._async_runtime.call(function, *args, **kwargs)
        return self._async_runtime.call_sync(function, *args, **kwargs)

    bridge_method.__name__ = function.__name__
    bridge_method.__qualname__ = function.__qualname__
    bridge_method.__doc__ = function.__doc__
    bridge_method.__dict__.update(function.__dict__)
    return bridge_method


def _wrap_class_method(
    cls: type[Any],
    function: Callable[..., Any],
) -> Callable[..., Any]:
    def bridge_method(self: Any, *args: Any, **kwargs: Any) -> Any:
        if inspect.iscoroutinefunction(function):
            return self._async_runtime.call(function, cls, *args, **kwargs)
        return self._async_runtime.call_sync(function, cls, *args, **kwargs)

    bridge_method.__name__ = function.__name__
    bridge_method.__qualname__ = function.__qualname__
    bridge_method.__doc__ = function.__doc__
    bridge_method.__dict__.update(function.__dict__)
    return bridge_method


def bridge_api[T: type[Any]](cls: T) -> T:
    """Expose every public sync or async method as a pywebview sync API."""
    original_init = cls.__init__

    @wraps(original_init)
    def initialize(self: Any, *args: Any, **kwargs: Any) -> None:
        self._async_runtime = AsyncRuntime()
        self._bridge_closed = False
        try:
            original_init(self, *args, **kwargs)
        except BaseException:
            self._async_runtime.close()
            raise

    def close_bridge(self: Any) -> None:
        if self._bridge_closed:
            return
        self._bridge_closed = True
        try:
            shutdown = self._shutdown_bridge
            if shutdown is not None:
                self._async_runtime.call(shutdown)
        finally:
            self._async_runtime.close()

    cls.__init__ = initialize
    cls._close_bridge = close_bridge
    for name in dir(cls):
        if name.startswith("_"):
            continue
        descriptor = inspect.getattr_static(cls, name)
        if isinstance(descriptor, staticmethod):
            wrapped = _wrap_static_method(descriptor.__func__)
        elif isinstance(descriptor, classmethod):
            wrapped = _wrap_class_method(cls, descriptor.__func__)
        elif inspect.isfunction(descriptor):
            wrapped = _wrap_instance_method(descriptor)
        else:
            continue
        setattr(cls, name, wrapped)
    return cast(T, cls)
