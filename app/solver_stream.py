import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import current_app

from app.qa import AIUnavailable, ProviderAuthFailed


def _provider_chunks(url, payload, headers, timeout):
    request = Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            for line in response:
                yield line
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ProviderAuthFailed() from None
        raise AIUnavailable() from None
    except (URLError, TimeoutError, OSError):
        raise AIUnavailable() from None


def parse_provider_stream(chunks):
    buffer = b""
    ended = False
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise AIUnavailable()
        buffer += chunk
        if len(buffer) > 1024 * 1024:
            raise AIUnavailable()
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            raw = raw.strip()
            if not raw or raw.startswith(b":"):
                continue
            if not raw.startswith(b"data:"):
                continue
            data = raw[5:].strip()
            if data == b"[DONE]":
                ended = True
                break
            try:
                part = json.loads(data)
                delta = part["choices"][0]["delta"].get("content", "")
            except (UnicodeError, ValueError, TypeError, KeyError, IndexError, AttributeError):
                raise AIUnavailable() from None
            if not isinstance(delta, str):
                raise AIUnavailable()
            if delta:
                yield delta
        if ended:
            break
    if not ended:
        raise AIUnavailable()


def stream_guidance(api_key, messages):
    payload = {
        "model": current_app.config["ZHIPU_MODEL"],
        "messages": messages,
        "stream": True,
        "temperature": 0.1,
        "max_tokens": current_app.config["KNOWLEDGE_QA_MAX_OUTPUT_TOKENS"],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    transport = current_app.config.get("ZHIPU_STREAM_TRANSPORT") or _provider_chunks
    from app.platform_trace import legacy_trace
    trace = legacy_trace(api_key, "legacy-solver")
    started = trace.begin_call(current_app.config["ZHIPU_API_URL"], json.dumps(payload, ensure_ascii=False).encode(),
                               headers, current_app.config["ZHIPU_TIMEOUT_SECONDS"]) if trace else None
    raw_capture = bytearray()
    total = 0
    text_parts = []

    def observed():
        nonlocal total
        for chunk in transport(current_app.config["ZHIPU_API_URL"], payload, headers, current_app.config["ZHIPU_TIMEOUT_SECONDS"]):
            if isinstance(chunk, bytes):
                total += len(chunk)
                limit = current_app.config["AI_TRACE_BYTES"] + 8192
                raw_capture.extend(chunk[:max(0, limit - len(raw_capture))])
            yield chunk
    try:
        for part in parse_provider_stream(observed()):
            text_parts.append(part)
            yield part
        if trace:
            usage, finish_reason = None, None
            for line in bytes(raw_capture).splitlines():
                if line.startswith(b"data:") and line[5:].strip() != b"[DONE]":
                    try:
                        event = json.loads(line[5:])
                        if "usage" in event:
                            usage = event["usage"]
                        finish_reason = event.get("choices", [{}])[0].get("finish_reason") or finish_reason
                    except (ValueError, IndexError, AttributeError):
                        continue
            sanitized = trace.redactor.sse(bytes(raw_capture)) if total <= len(raw_capture) else "[SSE raw capture omitted: redaction buffer limit]"
            trace.end_call(started, 200, sanitized)
            trace.parsed(started[0], {"content": "".join(text_parts), "usage": usage, "usage_provided": usage is not None, "finish_reason": finish_reason, "completed": True})
            started[0].response = {**started[0].response, "total_bytes": total, "truncated": total > len(raw_capture) or started[0].response["truncated"]}
            trace.commit()
    except (ProviderAuthFailed, AIUnavailable):
        if trace:
            trace.end_call(started, None, trace.redactor.sse(bytes(raw_capture)), "stream_failed", complete=False)
            trace.finish(error="ai_unavailable")
        raise
    except Exception:
        if trace:
            trace.end_call(started, None, trace.redactor.sse(bytes(raw_capture)), "stream_failed", complete=False)
            trace.finish(error="ai_unavailable")
        raise AIUnavailable() from None
