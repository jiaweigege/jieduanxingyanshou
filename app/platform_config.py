"""Validated configuration for the optional application platform."""
import json


POSITIVE_KEYS = (
    "AI_INPUT_BUDGET", "AI_MAX_MODEL_CALLS", "AI_MAX_TOOL_CALLS",
    "AI_TOOL_TIMEOUT", "AI_RUN_TIMEOUT", "AI_TOOL_RESULT_CHARS", "AI_TRACE_BYTES",
    "AI_TRACE_DAYS", "AI_SKILL_UPLOAD_BYTES", "AI_SKILL_EXPANDED_BYTES",
    "AI_SKILL_FILES", "AI_SKILL_BODY_CHARS", "AI_SKILL_REFERENCE_CHARS",
)


def configure_platform(app):
    flag = app.config["AI_PLATFORM_ENABLED"]
    if isinstance(flag, str) and flag.lower() in {"true", "false"}:
        flag = flag.lower() == "true"
    if not isinstance(flag, bool):
        raise RuntimeError("AI_PLATFORM_ENABLED must be true or false")
    app.config["AI_PLATFORM_ENABLED"] = flag
    for key in POSITIVE_KEYS:
        raw = app.config[key]
        try:
            value = int(raw)
        except (ValueError, TypeError):
            raise RuntimeError(f"{key} must be a positive integer") from None
        if isinstance(raw, bool) or str(value) != str(raw) or value <= 0:
            raise RuntimeError(f"{key} must be a positive integer")
        app.config[key] = value
    for key, kind in (("AI_MODEL_CAPABILITIES", dict), ("AI_TOOL_ALLOWED_HOSTS", list),
                      ("AI_CREDENTIAL_REFERENCES", dict)):
        value = app.config[key]
        try:
            value = json.loads(value) if isinstance(value, str) else value
        except (ValueError, TypeError):
            raise RuntimeError(f"{key} must be valid JSON") from None
        if not isinstance(value, kind):
            raise RuntimeError(f"{key} has an invalid type")
        app.config[key] = value
    capabilities = app.config["AI_MODEL_CAPABILITIES"]
    if not capabilities:
        capabilities[app.config["ZHIPU_MODEL"]] = {"tools": False}
    for model, options in capabilities.items():
        if (not isinstance(model, str) or not model.strip() or not isinstance(options, dict)
                or set(options) - {"tools"} or not isinstance(options.get("tools"), bool)):
            raise RuntimeError("AI_MODEL_CAPABILITIES requires model: {tools: boolean}")
    if any(not isinstance(host, str) or not host or "/" in host or ":" in host
           for host in app.config["AI_TOOL_ALLOWED_HOSTS"]):
        raise RuntimeError("AI_TOOL_ALLOWED_HOSTS requires exact host names")
    for name, reference in app.config["AI_CREDENTIAL_REFERENCES"].items():
        if (not isinstance(name, str) or not isinstance(reference, dict)
                or set(reference) != {"env", "class_ids"}
                or not isinstance(reference["env"], str)
                or not isinstance(reference["class_ids"], list)
                or any(type(i) is not int for i in reference["class_ids"])):
            raise RuntimeError("AI_CREDENTIAL_REFERENCES requires env and class_ids")
