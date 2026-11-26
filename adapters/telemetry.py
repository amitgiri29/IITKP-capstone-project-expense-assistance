"""Telemetry: redacted local JSONL traces always; LangSmith export only when explicitly enabled.

Exporter failures never change the application result (OBS06).
"""
import json
import logging
import threading
from datetime import datetime, timezone

from core.redaction import redact

log = logging.getLogger('expense_assistant.telemetry')


class Telemetry:
    def __init__(self, context):
        self.context = context
        self.status = 'LOCAL_ONLY'
        self._lock = threading.Lock()
        settings = context.settings.telemetry
        self.local = settings.local_trace
        self.trace_dir = context.settings.data_dir / 'traces'
        if settings.langsmith_enabled:
            # Cloud export needs an approved workspace, region and spend limit (docs/LANGSMITH_PLAN.txt).
            self.status = 'DEGRADED'
            log.warning('LangSmith export requested but not configured in this build; keeping local traces only.')

    def record(self, name, **fields):
        if not self.local:
            return
        line = {'at': datetime.now(timezone.utc).isoformat(timespec='milliseconds'), 'span': name,
                **redact(fields, self.context.secrets())}
        try:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            path = self.trace_dir / (datetime.now(timezone.utc).strftime('%Y-%m-%d') + '.jsonl')
            with self._lock, path.open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(line, default=str) + '\n')
        except OSError:
            self.status = 'DEGRADED'
