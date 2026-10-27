"""Versioned application resources and safe, declarative Skill imports."""
import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import PurePosixPath

import yaml
from flask import current_app

from app import db
from app.models import ClassRoom, Material
from app.platform_models import (
    AiApplication, ApplicationVersion, PromptTemplate, TemplateVersion,
    KnowledgeBase, KnowledgeBaseMaterial, SkillPackage, SkillVersion, SkillFile,
    ToolConnection, ToolDefinitionVersion,
)


class PlatformError(ValueError):
    def __init__(self, code, status=400, field=None):
        self.code, self.status, self.field = code, status, field
        super().__init__(code)


APPLICATION_CONFIG_KEYS = {"model", "template_version_id", "knowledge_base_ids", "skill_version_ids", "tool_definition_ids", "temperature", "max_tokens"}


def validate_draft(config):
    if not isinstance(config, dict) or set(config) - APPLICATION_CONFIG_KEYS:
        raise PlatformError("invalid_application_config")
    return config


def digest(value):
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def tenant(model, user, object_id, enabled=False):
    if type(object_id) is not int:
        raise PlatformError("not_found", 404)
    obj = db.session.get(model, object_id)
    if obj is None or obj.class_id != user.class_id or (enabled and not obj.enabled):
        raise PlatformError("not_found", 404)
    return obj


def text(value, field, limit=16000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise PlatformError("invalid_resource", field=field)
    return value.strip()


def id_list(value, field):
    if not isinstance(value, list) or len(value) > 64 or any(type(x) is not int for x in value):
        raise PlatformError("invalid_resource", field=field)
    return list(dict.fromkeys(value))


def latest(model, parent_field, parent_id):
    return db.session.scalar(db.select(model).where(getattr(model, parent_field) == parent_id).order_by(model.version.desc()))


VARIABLE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def template_fields(body, variables):
    body = text(body, "body")
    if (not isinstance(variables, list) or len(variables) > 32
            or any(not isinstance(v, str) or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", v) for v in variables)
            or len(set(variables)) != len(variables)):
        raise PlatformError("invalid_template_variables")
    remainder = VARIABLE.sub("", body)
    if any(token in remainder for token in ("{{", "}}", "{%", "%}", "{#")) or set(VARIABLE.findall(body)) != set(variables):
        raise PlatformError("invalid_template_variables")
    return body, variables


def render_template_version(version, values):
    if not isinstance(values, dict) or set(values) != set(version.variables):
        raise PlatformError("invalid_template_variables")
    if any(not isinstance(v, str) or len(v) > 16000 for v in values.values()):
        raise PlatformError("invalid_template_variables")
    rendered = VARIABLE.sub(lambda match: values[match.group(1)], version.body)
    if len(rendered) > 32000:
        raise PlatformError("context_budget_exceeded")
    return rendered


def save_template(user, payload, template=None):
    body, variables = template_fields(payload.get("body"), payload.get("variables", []))
    name = text(payload.get("name", template.name if template else None), "name", 120)
    if template is None:
        template = PromptTemplate(class_id=user.class_id, name=name)
        db.session.add(template); db.session.flush()
    else:
        template.name = name
    previous = latest(TemplateVersion, "template_id", template.id)
    version = TemplateVersion(class_id=user.class_id, template_id=template.id,
                              version=previous.version + 1 if previous else 1,
                              body=body, variables=variables, digest=digest([body, variables]))
    db.session.add(version); db.session.flush()
    return template, version


def parse_skill(filename, raw):
    config = current_app.config
    if len(raw) > config["AI_SKILL_UPLOAD_BYTES"]:
        raise PlatformError("invalid_skill_package")
    files = {}
    try:
        if filename == "SKILL.md":
            files[filename] = raw.decode("utf-8")
        elif filename.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                infos = archive.infolist()
                if len(infos) > config["AI_SKILL_FILES"]:
                    raise ValueError()
                expanded = 0
                for item in infos:
                    path = PurePosixPath(item.filename)
                    mode = item.external_attr >> 16
                    if item.is_dir():
                        if (path.is_absolute() or ".." in path.parts or "\\" in item.filename
                                or path.parts[0] != "references" or stat.S_ISLNK(mode)):
                            raise ValueError()
                        continue
                    if ("\\" in item.filename or path.is_absolute()
                            or ".." in path.parts or str(path) != item.filename
                            or item.filename in files or stat.S_ISLNK(mode)
                            or (stat.S_IFMT(mode) not in (0, stat.S_IFREG))
                            or (item.filename != "SKILL.md" and not (
                                len(path.parts) >= 2 and path.parts[0] == "references"
                                and path.suffix.lower() in {".md", ".txt"}))):
                        raise ValueError()
                    expanded += item.file_size
                    if expanded > config["AI_SKILL_EXPANDED_BYTES"]:
                        raise ValueError()
                    with archive.open(item) as member:
                        data = member.read(config["AI_SKILL_EXPANDED_BYTES"] + 1)
                    if len(data) != item.file_size:
                        raise ValueError()
                    files[item.filename] = data.decode("utf-8")
        else:
            raise ValueError()
        main = files["SKILL.md"]
        if len(main) > config["AI_SKILL_BODY_CHARS"] or not main.startswith("---\n"):
            raise ValueError()
        header, body = main[4:].split("\n---\n", 1)
        if any(isinstance(token, yaml.tokens.AliasToken) for token in yaml.scan(header)):
            raise ValueError()
        metadata = yaml.safe_load(header)
        if not isinstance(metadata, dict) or set(metadata) - {"name", "description", "allowed-tools"}:
            raise ValueError()
        name = text(metadata.get("name"), "name", 120)
        description = text(metadata.get("description"), "description", 2000)
        text(body, "body", config["AI_SKILL_BODY_CHARS"])
        tools = metadata.get("allowed-tools")
        if tools is not None and (not isinstance(tools, list) or any(not isinstance(t, str) or len(t) > 128 for t in tools)):
            raise ValueError()
        if any(len(content) > config["AI_SKILL_REFERENCE_CHARS"] for path, content in files.items() if path != "SKILL.md"):
            raise ValueError()
        return name, description, body, tools, files
    except (ValueError, KeyError, UnicodeError, zipfile.BadZipFile, RuntimeError, yaml.YAMLError, RecursionError):
        raise PlatformError("invalid_skill_package") from None


def save_skill(user, filename, raw, source="upload"):
    name, description, body, tools, files = parse_skill(filename, raw)
    package = db.session.scalar(db.select(SkillPackage).where(SkillPackage.class_id == user.class_id, SkillPackage.name == name))
    if package is None:
        package = SkillPackage(class_id=user.class_id, name=name, source=source)
        db.session.add(package); db.session.flush()
    elif package.source == "builtin" and source != "builtin":
        raise PlatformError("invalid_skill_package")
    previous = latest(SkillVersion, "package_id", package.id)
    version = SkillVersion(class_id=user.class_id, package_id=package.id,
                           version=previous.version + 1 if previous else 1,
                           description=description, body=body, allowed_tools=tools, digest=digest(files))
    db.session.add(version); db.session.flush()
    for path, content in files.items():
        db.session.add(SkillFile(class_id=user.class_id, version_id=version.id, path=path, content=content, digest=digest(content)))
    db.session.flush()
    return package, version


def validate_application_config(user, config):
    validate_draft(config)
    model = config.get("model", current_app.config["ZHIPU_MODEL"])
    if not isinstance(model, str):
        raise PlatformError("unsupported_model", field="model")
    capability = current_app.config["AI_MODEL_CAPABILITIES"].get(model)
    if capability is None:
        raise PlatformError("unsupported_model", field="model")
    template = tenant(TemplateVersion, user, config.get("template_version_id"))
    tenant(PromptTemplate, user, template.template_id, True)
    result = {"model": model, "template_version_id": template.id}
    for field, cls in (("knowledge_base_ids", KnowledgeBase), ("skill_version_ids", SkillVersion), ("tool_definition_ids", ToolDefinitionVersion)):
        result[field] = id_list(config.get(field, []), field)
        for ident in result[field]:
            obj = tenant(cls, user, ident, cls is KnowledgeBase)
            if cls is SkillVersion:
                tenant(SkillPackage, user, obj.package_id, True)
            if cls is ToolDefinitionVersion:
                conn = tenant(ToolConnection, user, obj.connection_id, True)
                if conn.definition_digest != obj.digest:
                    raise PlatformError("stale_tool_binding", 409, field)
    if (result["skill_version_ids"] or result["tool_definition_ids"]) and not capability["tools"]:
        raise PlatformError("model_tools_unsupported", field="model")
    temperature, tokens = config.get("temperature", 0.1), config.get("max_tokens", 512)
    if (type(temperature) not in (float, int) or not 0 <= temperature <= 2
            or type(tokens) is not int or not 1 <= tokens <= 8192):
        raise PlatformError("invalid_application_config", field="generation")
    return {**result, "temperature": temperature, "max_tokens": tokens}


def publish_application(user, application):
    config = validate_application_config(user, application.draft)
    previous = latest(ApplicationVersion, "application_id", application.id)
    version = ApplicationVersion(class_id=user.class_id, application_id=application.id,
                                 version=previous.version + 1 if previous else 1, config=config)
    db.session.add(version); db.session.flush()
    return version


def add_default_material(material):
    base = db.session.scalar(db.select(KnowledgeBase).where(KnowledgeBase.class_id == material.class_id, KnowledgeBase.is_default.is_(True)))
    if base and not db.session.get(KnowledgeBaseMaterial, (base.id, material.id)):
        db.session.add(KnowledgeBaseMaterial(class_id=material.class_id, base_id=base.id, material_id=material.id))


def initialize_platform():
    from types import SimpleNamespace
    for class_id in db.session.scalars(db.select(ClassRoom.id)).all():
        user = SimpleNamespace(class_id=class_id)
        base = db.session.scalar(db.select(KnowledgeBase).where(KnowledgeBase.class_id == class_id, KnowledgeBase.is_default.is_(True)))
        if base is None:
            base = KnowledgeBase(class_id=class_id, name="本班默认知识库", is_default=True)
            db.session.add(base); db.session.flush()
        for material in db.session.scalars(db.select(Material).where(Material.class_id == class_id)).all():
            add_default_material(material)
        for name, description, body in (("解题引导", "提示、追问和下一步思路", "先确认已知条件，再引导下一步，不直接给最终答案。"),
                                        ("资料摘要", "按资料提炼要点", "只依据提供的资料，归纳要点并引用来源编号。")):
            if not db.session.scalar(db.select(SkillPackage.id).where(SkillPackage.class_id == class_id, SkillPackage.name == name)):
                save_skill(user, "SKILL.md", f"---\nname: {name}\ndescription: {description}\n---\n{body}".encode(), "builtin")
        for slug, name, purpose, kind, instruction in (
            ("chat", "通用对话", "回答日常问题", "chat", "简洁准确地回答用户问题。"),
            ("knowledge", "知识问答", "检索本班知识并引用来源", "knowledge", "仅依据本次来源回答，引用编号。"),
            ("solver", "解题引导", "提供提示和下一步思路", "solver", "只给提示与追问，不给最终答案。"),
        ):
            if db.session.scalar(db.select(AiApplication.id).where(AiApplication.class_id == class_id, AiApplication.slug == slug)):
                continue
            _, template = save_template(user, {"name": name, "body": instruction})
            application = AiApplication(class_id=class_id, slug=slug, name=name, purpose=purpose, kind=kind,
                                        draft={"model": current_app.config["ZHIPU_MODEL"] if current_app.config["ZHIPU_MODEL"] in current_app.config["AI_MODEL_CAPABILITIES"] else next(iter(current_app.config["AI_MODEL_CAPABILITIES"])),
                                               "template_version_id": template.id, "knowledge_base_ids": [] if kind == "chat" else [base.id]})
            db.session.add(application); db.session.flush()
            publish_application(user, application)
    db.session.commit()
