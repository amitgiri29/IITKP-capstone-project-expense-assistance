"""Instrumentation events. The evaluation harness derives observations from these,
never from what the application or the model says about itself."""
import threading
import time


class EventLog:
    def __init__(self):
        self._events = []
        self._lock = threading.Lock()

    def emit(self, kind, **data):
        with self._lock:
            self._events.append({'kind': kind, 'at': time.time(), **data})

    def all(self, kind=None):
        with self._lock:
            return [dict(e) for e in self._events if kind is None or e['kind'] == kind]

    def count(self, kind):
        return len(self.all(kind))

    def clear(self):
        with self._lock:
            self._events.clear()
