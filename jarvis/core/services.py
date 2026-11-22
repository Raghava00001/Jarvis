"""
Service registry: the composition root of JARVIS.

Every long-lived subsystem (alarms, reminders, hotkeys, chat history, perception,
news, weather …) exists exactly once per process, no matter which layer asks
for it: the WebSocket server, JARVISUltimate, intent handlers or Gemini tools.

    from jarvis.core.services import shared
    alarms = shared(AlarmSystem, lambda: AlarmSystem(perception))

The first caller's factory builds the instance; later callers get that same
object. Before this, the server and JARVISUltimate each built their own copy of
~25 subsystems, so reminders were checked by two threads, hotkeys registered
twice, and handlers rebuilt objects (and rescanned installed apps) per command.

Keys are the classes themselves, so two call sites can't drift apart by using
different names for the same service.
"""

import threading
from typing import Callable, Dict, Optional, Type, TypeVar

T = TypeVar("T")

_instances: Dict[type, object] = {}
_locks: Dict[type, threading.RLock] = {}
_registry_lock = threading.Lock()


def shared(cls: Type[T], factory: Optional[Callable[[], T]] = None) -> T:
    """Return the single instance of ``cls``, creating it with ``factory`` on first use.

    Thread-safe: concurrent first calls build the instance only once. Each class
    has its own (re-entrant) lock, so building one service never blocks another,
    and a factory may itself request other services.
    """
    instance = _instances.get(cls)
    if instance is not None:
        return instance
    with _registry_lock:
        lock = _locks.setdefault(cls, threading.RLock())
    with lock:
        instance = _instances.get(cls)
        if instance is None:
            instance = factory() if factory is not None else cls()
            _instances[cls] = instance
        return instance


def peek(cls: Type[T]) -> Optional[T]:
    """The existing instance of ``cls`` or None, without creating it."""
    return _instances.get(cls)


def provide(cls: Type[T], instance: T) -> T:
    """Register an already-built instance (first one wins). Returns the registered instance."""
    return shared(cls, lambda: instance)


def registered() -> Dict[str, object]:
    """Snapshot of all live services by class name (for diagnostics)."""
    return {cls.__name__: inst for cls, inst in list(_instances.items())}


def reset() -> None:
    """Forget all services. For tests only."""
    with _registry_lock:
        _instances.clear()
        _locks.clear()
