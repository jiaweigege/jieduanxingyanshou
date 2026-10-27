"""HTTP and MCP adapters with pinned-address connections and bounded results."""
import asyncio
import ipaddress
import json
import logging
import os
import re
import socket
import time
from datetime import timedelta
from urllib.parse import urlsplit

import anyio
import httpcore
import httpx
from jsonschema import validators, ValidationError, SchemaError
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from flask import current_app
from app import db
from app.platform_models import ToolConnection, ToolDefinitionVersion
from app.platform_resources import PlatformError, digest


PROTOCOL = "2025-11-25"


class ProtocolLogFilter(logging.Filter):
    """Third-party transport exceptions must not echo remote bodies or headers."""
    def filter(self, record):
        record.msg, record.args, record.exc_info, record.exc_text = "MCP transport event", (), None, None
        return True


for logger_name in tuple(logging.Logger.manager.loggerDict):
    if not logger_name.startswith(("mcp.", "httpx", "httpcore")):
        continue
    logging.getLogger(logger_name).addFilter(ProtocolLogFilter())


class BoundedAsyncStream(httpx.AsyncByteStream):
    def __init__(self, stream, limit):
        self.stream, self.limit = stream, limit

    async def __aiter__(self):
        consumed = 0
        async for chunk in self.stream:
            consumed += len(chunk)
            if consumed > self.limit:
                raise PlatformError("tool_result_too_large", 503)
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


def validate_schema(schema):
    if not isinstance(schema, dict) or len(json.dumps(schema)) > 16000:
        raise PlatformError("invalid_tool_schema")
    if schema.get("$schema") not in (None, "https://json-schema.org/draft/2020-12/schema", "http://json-schema.org/draft-07/schema#", "https://json-schema.org/draft-07/schema#"):
        raise PlatformError("invalid_tool_schema")
    def check_refs(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"$ref", "$dynamicRef"} and (not isinstance(child, str) or not child.startswith("#")):
                    raise PlatformError("invalid_tool_schema")
                check_refs(child)
        elif isinstance(value, list):
            for child in value:
                check_refs(child)
    check_refs(schema)
    try:
        validators.validator_for(schema).check_schema(schema)
    except (SchemaError, ValueError, RecursionError):
        raise PlatformError("invalid_tool_schema") from None
    return schema


def validate_arguments(schema, arguments):
    try:
        validators.validator_for(schema)(schema).validate(arguments)
    except (ValidationError, ValueError, RecursionError):
        raise PlatformError("invalid_tool_arguments") from None


def validate_target(url, resolve=True):
    try:
        target = urlsplit(url)
        if (target.scheme != "https" or not target.hostname or target.username or target.password
                or target.query or target.fragment or target.port not in (None, 443)
                or target.hostname not in current_app.config["AI_TOOL_ALLOWED_HOSTS"]):
            raise ValueError()
        if resolve:
            resolver = current_app.config.get("AI_DNS_RESOLVER") if current_app.testing else None
            addresses = resolver(target.hostname) if resolver else {
                info[4][0] for info in socket.getaddrinfo(target.hostname, 443, type=socket.SOCK_STREAM)
            }
            if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
                raise ValueError()
            return target.hostname, sorted(addresses)
        return target.hostname, []
    except (ValueError, TypeError, OSError):
        raise PlatformError("tool_target_forbidden") from None


class PinnedSyncBackend(httpcore.SyncBackend):
    def __init__(self, host, addresses):
        self.host, self.addresses = host, addresses

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host != self.host or port != 443:
            raise PlatformError("tool_target_forbidden")
        return super().connect_tcp(self.addresses[0], port, timeout, local_address, socket_options)


class PinnedAsyncBackend(httpcore.AnyIOBackend):
    def __init__(self, host, addresses):
        self.host, self.addresses = host, addresses

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host != self.host or port != 443:
            raise PlatformError("tool_target_forbidden")
        return await super().connect_tcp(self.addresses[0], port, timeout, local_address, socket_options)


def connection_headers(connection):
    if not connection.credential_ref:
        return {}
    reference = current_app.config["AI_CREDENTIAL_REFERENCES"].get(connection.credential_ref)
    if not reference or connection.class_id not in reference["class_ids"]:
        raise PlatformError("tool_credential_unavailable", 503)
    secret = os.environ.get(reference["env"])
    if not secret or len(secret) > 4096 or "\n" in secret or "\r" in secret:
        raise PlatformError("tool_credential_unavailable", 503)
    return {"Authorization": "Bearer " + secret}


def credentials_for_redaction(connection):
    return [value.removeprefix("Bearer ") for value in connection_headers(connection).values()]


def prepare_connection(payload, user):
    if not isinstance(payload, dict) or set(payload) - {"name", "kind", "url", "credential_ref", "http_config", "protocol_version"}:
        raise PlatformError("invalid_connection")
    name, kind, url = payload.get("name"), payload.get("kind"), payload.get("url")
    if not isinstance(name, str) or not name.strip() or len(name) > 120 or kind not in {"http", "mcp"}:
        raise PlatformError("invalid_connection")
    validate_target(url)
    if payload.get("protocol_version", PROTOCOL) != PROTOCOL:
        raise PlatformError("unsupported_mcp_protocol")
    connection = ToolConnection(class_id=user.class_id, name=name, kind=kind, url=url,
                                credential_ref=payload.get("credential_ref"),
                                protocol_version=PROTOCOL, http_config=payload.get("http_config", {}))
    if not isinstance(connection.http_config, dict):
        raise PlatformError("invalid_connection")
    if kind == "http":
        cfg = connection.http_config
        if (set(cfg) - {"method", "parameter_map", "tool"} or cfg.get("method", "POST") not in {"GET", "POST"}
                or not isinstance(cfg.get("parameter_map", {}), dict)
                or any(not isinstance(k, str) or not isinstance(v, str) for k, v in cfg.get("parameter_map", {}).items())):
            raise PlatformError("invalid_connection")
        normalize_definitions([cfg.get("tool")])
    connection_headers(connection)
    return connection


def normalize_definitions(tools):
    if not isinstance(tools, list) or len(tools) > 128:
        raise PlatformError("invalid_tool_schema")
    result, names = [], set()
    for tool in tools:
        if not isinstance(tool, dict):
            raise PlatformError("invalid_tool_schema")
        name, description = tool.get("name"), tool.get("description", "")
        if (not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", name)
                or name in names or not isinstance(description, str) or len(description) > 4000):
            raise PlatformError("invalid_tool_schema")
        names.add(name)
        schema = validate_schema(tool.get("inputSchema"))
        if schema.get("type") != "object":
            raise PlatformError("invalid_tool_schema")
        output = tool.get("outputSchema")
        if output is not None:
            validate_schema(output)
        sensitive = tool.get("sensitive_parameters", [])
        if not isinstance(sensitive, list) or any(not isinstance(k, str) for k in sensitive):
            raise PlatformError("invalid_tool_schema")
        result.append({"name": name, "description": description, "inputSchema": schema,
                       "outputSchema": output, "sensitive_parameters": sensitive})
    return sorted(result, key=lambda value: value["name"])


async def sdk_operation(connection, method, params, timeout, headers, addresses, transport=None):
    native = httpx.AsyncHTTPTransport(retries=0)
    native._pool._network_backend = PinnedAsyncBackend(*addresses)
    wire = transport or native
    # SDK protocol messages stay on the configured origin; never accept redirects.
    async def check_response(response):
        if 300 <= response.status_code < 400:
            raise PlatformError("tool_target_forbidden")
        response.stream = BoundedAsyncStream(response.stream, current_app.config["AI_TRACE_BYTES"] * 4)
    async with httpx.AsyncClient(transport=wire, headers=headers, timeout=timeout,
                                 follow_redirects=False, trust_env=False,
                                 event_hooks={"response": [check_response]}) as client:
        with anyio.fail_after(timeout):
            async with streamable_http_client(connection.url, http_client=client) as (read, write, _):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=timeout)) as session:
                    initialized = await session.initialize()
                    if initialized.protocolVersion != PROTOCOL:
                        raise PlatformError("unsupported_mcp_protocol")
                    if not initialized.capabilities.tools:
                        raise PlatformError("mcp_tools_unsupported")
                    if method == "tools/list":
                        tools, cursor, seen = [], None, set()
                        while True:
                            page = await session.list_tools(cursor=cursor)
                            tools.extend(tool.model_dump(by_alias=True, exclude_none=True) for tool in page.tools)
                            cursor = page.nextCursor
                            if len(tools) > 128 or (cursor and cursor in seen):
                                raise PlatformError("tool_budget_exceeded", 503)
                            if not cursor:
                                return tools
                            seen.add(cursor)
                    result = await session.call_tool(params["name"], params["arguments"])
                    return result.model_dump(by_alias=True, exclude_none=True)


def mcp_operation(connection, method, params, timeout):
    addresses = validate_target(connection.url)
    headers = connection_headers(connection)
    factory = current_app.config.get("AI_MCP_HTTP_TRANSPORT") if current_app.testing else None
    try:
        return asyncio.run(sdk_operation(connection, method, params, timeout, headers, addresses,
                                         factory() if factory else None))
    except PlatformError:
        raise
    except Exception:
        raise PlatformError("mcp_unavailable", 503) from None


def discover_tools(connection, timeout=None):
    if not connection.enabled:
        raise PlatformError("connection_disabled", 409)
    if connection.kind == "mcp":
        tools = mcp_operation(connection, "tools/list", {}, timeout or current_app.config["AI_TOOL_TIMEOUT"])
    else:
        validate_target(connection.url)
        tools = [connection.http_config.get("tool")]
    tools = normalize_definitions(tools)
    fingerprint = digest(tools)
    connection.definition_digest = fingerprint
    definitions = []
    for tool in tools:
        existing = db.session.scalar(db.select(ToolDefinitionVersion).where(
            ToolDefinitionVersion.connection_id == connection.id,
            ToolDefinitionVersion.digest == fingerprint, ToolDefinitionVersion.name == tool["name"]))
        if existing is None:
            existing = ToolDefinitionVersion(class_id=connection.class_id, connection_id=connection.id,
                                             name=tool["name"], description=tool["description"],
                                             input_schema=tool["inputSchema"], output_schema=tool["outputSchema"],
                                             sensitive_parameters=tool["sensitive_parameters"], digest=fingerprint)
            db.session.add(existing); db.session.flush()
        definitions.append(existing)
    return definitions


async def _http_operation(connection, arguments, timeout):
    host, addresses = validate_target(connection.url)
    transport = httpx.AsyncHTTPTransport(retries=0)
    transport._pool._network_backend = PinnedAsyncBackend(host, addresses)
    factory = current_app.config.get("AI_HTTP_TOOL_TRANSPORT") if current_app.testing else None
    cfg = connection.http_config
    mapping = cfg.get("parameter_map", {})
    if set(mapping) - set(arguments):
        raise PlatformError("invalid_tool_arguments")
    mapped = {mapping.get(k, k): value for k, value in arguments.items()}
    method = cfg.get("method", "POST")
    try:
        with anyio.fail_after(timeout):
            async with httpx.AsyncClient(transport=factory() if factory else transport, timeout=timeout,
                                        follow_redirects=False, trust_env=False) as client:
              async with client.stream(method, connection.url, headers=connection_headers(connection),
                                       **({"params": mapped} if method == "GET" else {"json": mapped})) as response:
                if response.status_code != 200:
                    raise PlatformError("tool_unavailable", 503)
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > current_app.config["AI_TRACE_BYTES"] * 4:
                        raise PlatformError("tool_result_too_large", 503)
                if "application/json" in response.headers.get("content-type", ""):
                    result = json.loads(raw)
                    return {"structuredContent": result, "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
                return {"content": [{"type": "text", "text": raw.decode("utf-8")}], "isError": False}
    except PlatformError:
        raise
    except Exception:
        raise PlatformError("tool_unavailable", 503) from None


def http_operation(connection, arguments, timeout):
    return asyncio.run(_http_operation(connection, arguments, timeout))


def execute_external(definition, arguments, timeout, redactor=None):
    started = time.monotonic()
    connection = db.session.get(ToolConnection, definition.connection_id, populate_existing=True)
    if not connection or not connection.enabled or connection.definition_digest != definition.digest:
        raise PlatformError("stale_tool_binding", 409)
    validate_arguments(definition.input_schema, arguments)
    if connection.kind == "mcp":
        # Re-discovery prevents schema changes from silently reaching execution.
        discover_tools(connection, timeout)
        db.session.commit()
        if connection.definition_digest != definition.digest:
            raise PlatformError("stale_tool_binding", 409)
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise PlatformError("tool_timeout", 503)
        result = mcp_operation(connection, "tools/call", {"name": definition.name, "arguments": arguments}, remaining)
    else:
        result = http_operation(connection, arguments, timeout)
    if definition.output_schema is not None and not result.get("isError"):
        try:
            validate_arguments(definition.output_schema, result.get("structuredContent"))
        except PlatformError:
            raise PlatformError("invalid_tool_result", 503) from None
    projected = {"isError": bool(result.get("isError")), "content": []}
    for block in result.get("content", []):
        if block.get("type") == "text":
            projected["content"].append({"type": "text", "text": block.get("text", "")})
        else:
            projected["content"].append({"type": "unsupported", "original_type": block.get("type")})
    if "structuredContent" in result:
        projected["structuredContent"] = result["structuredContent"]
    from app.platform_trace import Redactor
    redactor = redactor or Redactor(credentials_for_redaction(connection))
    redactor.add([arguments.get(key) for key in definition.sensitive_parameters])
    total_bytes = len(json.dumps(projected, ensure_ascii=False).encode())
    raw = json.dumps(redactor.clean(projected), ensure_ascii=False)
    limit = current_app.config["AI_TOOL_RESULT_CHARS"]
    return {"text": raw[:limit], "truncated": len(raw) > limit, "isError": bool(result.get("isError")),
            "total_bytes": total_bytes}
