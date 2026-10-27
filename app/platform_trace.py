"""Transport-boundary evidence. Only sanitized, bounded representations persist."""
import json
import time
from uuid import uuid4
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

from flask import current_app, g, has_request_context, request

from app import db
from app.platform_models import ConversationRun, LlmCall, RunEvent, now
from app.platform_resources import PlatformError, digest


SECRET_FIELDS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "api_key", "apikey", "access_token", "token", "password", "secret", "credential", "mcp-session-id"}


class Redactor:
    def __init__(self, secrets=()):
        self.secrets = set()
        self.add(secrets)

    def add(self, values):
        for value in values:
            if isinstance(value, str) and value:
                self.secrets.add(value)
                # Provider raw JSON can escape non-ASCII secrets.
                self.secrets.add(json.dumps(value, ensure_ascii=True)[1:-1])

    def clean(self, value):
        if isinstance(value, dict):
            return {str(k): "[REDACTED]" if str(k).lower() in SECRET_FIELDS else self.clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            for secret in sorted(self.secrets, key=len, reverse=True):
                value = value.replace(secret, "[REDACTED]")
        return value

    def collect(self, value, fields=SECRET_FIELDS):
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in fields and isinstance(child, str):
                    self.add([child])
                self.collect(child, fields)
        elif isinstance(value, list):
            for child in value:
                self.collect(child, fields)

    def capture(self, raw, limit=None, total_known=True):
        if not isinstance(raw, (str, bytes)):
            raw = json.dumps(raw, ensure_ascii=False)
        original = raw if isinstance(raw, bytes) else raw.encode("utf-8")
        try:
            self.collect(json.loads(original))
        except (ValueError, UnicodeError):
            pass
        clean = self.clean(original.decode("utf-8", errors="replace")).encode("utf-8")
        limit = limit or current_app.config["AI_TRACE_BYTES"]
        selected = clean[:limit].decode("utf-8", errors="ignore")
        return {"raw": selected, "total_bytes": len(original) if total_known else None,
                "captured_bytes": len(selected.encode()), "truncated": len(clean) > limit or not total_known,
                "digest": digest(selected)}

    def sse(self, raw):
        """Mask secrets even when a provider splits them across delta events."""
        lines = raw.decode("utf-8", errors="replace").splitlines(keepends=True)
        spans, combined = [], ""
        for index, line in enumerate(lines):
            if not line.startswith("data:"):
                continue
            try:
                value = json.loads(line[5:].strip())
                content = value["choices"][0]["delta"].get("content", "")
                if not isinstance(content, str):
                    continue
                spans.append((index, len(combined), len(combined) + len(content), value, content))
                combined += content
            except (ValueError, KeyError, IndexError, TypeError):
                continue
        ranges = []
        for secret in self.secrets:
            start = combined.find(secret)
            while start >= 0:
                ranges.append((start, start + len(secret)))
                start = combined.find(secret, start + len(secret))
        for index, start, end, value, content in spans:
            mask = [False] * len(content)
            for left, right in ranges:
                for pos in range(max(start, left), min(end, right)):
                    mask[pos - start] = True
            if any(mask):
                output, masking = "", False
                for char, hidden in zip(content, mask):
                    if hidden and not masking:
                        output += "[REDACTED]"
                    if not hidden:
                        output += char
                    masking = hidden
                value["choices"][0]["delta"]["content"] = output
                lines[index] = "data: " + json.dumps(self.clean(value), ensure_ascii=False) + "\n"
        return self.clean("".join(lines))


class Trace:
    def __init__(self, run, secrets=()):
        self.run_id = run.id
        self.redactor = Redactor(secrets)
        if has_request_context():
            self.redactor.add([request.headers.get("Authorization", "").removeprefix("Bearer ")])
        self.sequence = db.session.query(db.func.count(LlmCall.id)).filter_by(run_id=run.id).scalar() or 0
        self.event_sequence = db.session.query(db.func.count(RunEvent.id)).filter_by(run_id=run.id).scalar() or 0

    @property
    def run(self):
        # SSE can cross Flask's request/session teardown boundary.
        return db.session.get(ConversationRun, self.run_id)

    def commit(self):
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.error("Trace unavailable run=%s", self.run_id)
            raise PlatformError("trace_unavailable", 503) from None

    def event(self, kind, data):
        self.event_sequence += 1
        clean = self.redactor.clean(data)
        if len(json.dumps(clean, ensure_ascii=False).encode()) > current_app.config["AI_TRACE_BYTES"]:
            clean = self.redactor.capture(clean)
        db.session.add(RunEvent(run_id=self.run.id, sequence=self.event_sequence, kind=kind, data=clean))
        self.commit()

    def begin_call(self, url, body, headers, timeout):
        self.sequence += 1
        target = urlsplit(url)
        safe_url = urlunsplit((target.scheme, target.netloc, target.path, "", ""))
        evidence = self.redactor.capture(body)
        if not evidence["truncated"]:
            try:
                evidence["json"] = self.redactor.clean(json.loads(evidence["raw"]))
            except ValueError:
                pass
        call = LlmCall(run_id=self.run.id, sequence=self.sequence,
                       request={"url": self.redactor.clean(safe_url), "headers": self.redactor.clean(headers),
                                "body": evidence, "timeout_seconds": timeout})
        db.session.add(call); self.commit()
        self.event("llm_started", {"call_id": call.id, "sequence": call.sequence})
        return call, time.monotonic()

    def end_call(self, started, status, raw, error=None, complete=True):
        call, timestamp = started
        call.response = {"http_status": status, **self.redactor.capture(raw, total_known=complete)}
        call.status = "failed" if error else "received"
        call.duration_ms = max(0, int((time.monotonic() - timestamp) * 1000))
        if error:
            call.parsed = {"error": error}
        self.commit()

    def parsed(self, call, value, error=None):
        call.parsed = self.redactor.clean(value)
        if len(json.dumps(call.parsed).encode()) > current_app.config["AI_TRACE_BYTES"]:
            call.parsed = self.redactor.capture(call.parsed)
        call.status = "failed" if error else "parsed"
        self.commit()

    def finish(self, result=None, error=None):
        self.run.result = self.redactor.clean(result)
        self.run.status = "failed" if error else "completed"
        self.run.error = error
        self.commit()


def new_trace(user, origin, config=None, secrets=()):
    redactor = Redactor(secrets)
    run = ConversationRun(class_id=user.class_id, owner_id=user.id, request_id=uuid4().hex,
                          origin=origin, config=redactor.clean(config or {}),
                          expires_at=now() + timedelta(days=current_app.config["AI_TRACE_DAYS"]))
    db.session.add(run)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise PlatformError("trace_unavailable", 503) from None
    trace = Trace(run, secrets)
    if has_request_context():
        g.platform_trace = trace
    return trace


def legacy_trace(api_key, origin, config=None):
    if not current_app.config["AI_PLATFORM_ENABLED"] or not has_request_context() or not getattr(g, "user", None):
        return None
    existing = getattr(g, "platform_trace", None)
    return existing or new_trace(g.user, origin, config, [api_key])


def cleanup_traces():
    ids = db.session.scalars(db.select(ConversationRun.id).where(ConversationRun.expires_at <= now())).all()
    if ids:
        db.session.execute(db.delete(ConversationRun).where(ConversationRun.id.in_(ids)))
    db.session.commit()
    return len(ids)
