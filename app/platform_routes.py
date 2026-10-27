"""Authenticated resource management, application conversation and evidence APIs."""
import json

from flask import Blueprint, current_app, g, request, render_template, make_response
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import Material
from app.platform_models import (
    AiApplication, ApplicationVersion, PromptTemplate, TemplateVersion,
    KnowledgeBase, KnowledgeBaseMaterial, SkillPackage, SkillVersion, SkillFile,
    ToolConnection, ToolDefinitionVersion, AppConversation, AppMessage,
    ConversationRun, LlmCall, RunEvent, now,
)
from app.platform_resources import (
    PlatformError, tenant, text, id_list, latest, save_template, save_skill,
    publish_application,
    validate_draft,
)
from app.platform_runtime import ConversationRunner, own_conversation
from app.platform_tools import prepare_connection, discover_tools


platform_bp = Blueprint("platform", __name__)


@platform_bp.before_request
def check_platform():
    if not current_app.config["AI_PLATFORM_ENABLED"]:
        raise PlatformError("not_found", 404)
    if request.path.startswith("/api/") and request.method in {"POST", "PATCH", "DELETE"}:
        if not request.path.startswith(("/api/app-conversations", "/api/conversation-runs")) and not g.user.is_teacher:
            raise PlatformError("forbidden", 403)


@platform_bp.errorhandler(PlatformError)
def platform_error(error):
    db.session.rollback()
    result = {"error": error.code}
    if error.field:
        result["field"] = error.field
    return result, error.status


@platform_bp.errorhandler(IntegrityError)
def platform_conflict(_error):
    db.session.rollback()
    return {"error": "resource_conflict"}, 409


@platform_bp.after_request
def no_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def payload():
    result = request.get_json(silent=True)
    if not isinstance(result, dict):
        raise PlatformError("invalid_resource")
    return result


def enabled_update(obj, data):
    if set(data) != {"enabled"} or type(data["enabled"]) is not bool:
        raise PlatformError("invalid_resource")
    obj.enabled = data["enabled"]
    db.session.commit()
    return serialize(obj)


def serialize(obj):
    result = {column.name: getattr(obj, column.name) for column in obj.__table__.columns}
    for field in ("created_at", "expires_at"):
        if field in result and result[field] is not None:
            result[field] = result[field].isoformat()
    if isinstance(obj, AiApplication):
        version = latest(ApplicationVersion, "application_id", obj.id)
        result["published"] = serialize(version) if version else None
        if not g.user.is_teacher:
            result.pop("draft", None)
    if isinstance(obj, PromptTemplate):
        result["versions"] = [serialize(v) for v in TemplateVersion.query.filter_by(template_id=obj.id).order_by(TemplateVersion.version).all()]
    if isinstance(obj, SkillPackage):
        result["versions"] = [serialize(v) for v in SkillVersion.query.filter_by(package_id=obj.id).order_by(SkillVersion.version).all()]
    if isinstance(obj, KnowledgeBase):
        result["material_ids"] = list(db.session.scalars(db.select(KnowledgeBaseMaterial.material_id).where(KnowledgeBaseMaterial.base_id == obj.id)))
    if isinstance(obj, ToolConnection):
        result["definitions"] = [serialize(v) for v in ToolDefinitionVersion.query.filter_by(connection_id=obj.id, digest=obj.definition_digest).all()]
    return result


@platform_bp.route("/apps")
def apps_page():
    return render_template("apps.html")


@platform_bp.route("/api/apps", methods=["GET", "POST"])
def apps():
    if request.method == "GET":
        objects = AiApplication.query.filter_by(class_id=g.user.class_id, enabled=True).order_by(AiApplication.id).all()
        return {"apps": [serialize(obj) for obj in objects if g.user.is_teacher or latest(ApplicationVersion, "application_id", obj.id)],
                "models": current_app.config["AI_MODEL_CAPABILITIES"]}
    data = payload()
    kind = data.get("kind", "chat")
    if kind not in {"chat", "knowledge", "solver"}:
        raise PlatformError("invalid_application_config")
    obj = AiApplication(class_id=g.user.class_id, slug=text(data.get("slug"), "slug", 120),
                        name=text(data.get("name"), "name", 120), purpose=text(data.get("purpose"), "purpose", 2000),
                        kind=kind, draft=validate_draft(data.get("config", {})))
    db.session.add(obj); db.session.commit()
    return serialize(obj), 201


@platform_bp.route("/api/apps/<int:application_id>", methods=["GET", "PATCH"])
def app_detail(application_id):
    obj = tenant(AiApplication, g.user, application_id)
    if request.method == "GET":
        return serialize(obj)
    data = payload()
    if set(data) == {"enabled"}:
        return enabled_update(obj, data)
    if set(data) - {"name", "purpose", "config"}:
        raise PlatformError("invalid_resource")
    for key in ("name", "purpose"):
        if key in data:
            setattr(obj, key, text(data[key], key, 120 if key == "name" else 2000))
    if "config" in data:
        obj.draft = validate_draft(data["config"])
    db.session.commit()
    return serialize(obj)


@platform_bp.route("/api/apps/<int:application_id>/publish", methods=["POST"])
def publish(application_id):
    application = tenant(AiApplication, g.user, application_id, True)
    version = publish_application(g.user, application)
    db.session.commit()
    return serialize(version), 201


@platform_bp.route("/api/prompt-templates", methods=["GET", "POST"])
def templates():
    if request.method == "GET":
        return {"templates": [serialize(obj) for obj in PromptTemplate.query.filter_by(class_id=g.user.class_id, enabled=True).order_by(PromptTemplate.id)]}
    obj, _ = save_template(g.user, payload())
    db.session.commit()
    return serialize(obj), 201


@platform_bp.route("/api/prompt-templates/<int:template_id>", methods=["GET", "PATCH"])
def template_detail(template_id):
    obj = tenant(PromptTemplate, g.user, template_id)
    if request.method == "GET":
        return serialize(obj)
    data = payload()
    if set(data) == {"enabled"}:
        return enabled_update(obj, data)
    save_template(g.user, data, obj)
    db.session.commit()
    return serialize(obj)


def set_members(base, ids):
    ids = id_list(ids, "material_ids")
    for ident in ids:
        tenant(Material, g.user, ident)
    db.session.execute(db.delete(KnowledgeBaseMaterial).where(KnowledgeBaseMaterial.base_id == base.id))
    for ident in ids:
        db.session.add(KnowledgeBaseMaterial(class_id=g.user.class_id, base_id=base.id, material_id=ident))


@platform_bp.route("/api/knowledge-bases", methods=["GET", "POST"])
def knowledge_bases():
    if request.method == "GET":
        return {"knowledge_bases": [serialize(obj) for obj in KnowledgeBase.query.filter_by(class_id=g.user.class_id, enabled=True).order_by(KnowledgeBase.id)]}
    data = payload()
    obj = KnowledgeBase(class_id=g.user.class_id, name=text(data.get("name"), "name", 120))
    db.session.add(obj); db.session.flush()
    set_members(obj, data.get("material_ids", []))
    db.session.commit()
    return serialize(obj), 201


@platform_bp.route("/api/knowledge-bases/<int:base_id>", methods=["GET", "PATCH"])
def base_detail(base_id):
    obj = tenant(KnowledgeBase, g.user, base_id)
    if request.method == "GET":
        return serialize(obj)
    data = payload()
    if set(data) == {"enabled"}:
        return enabled_update(obj, data)
    if set(data) - {"name", "material_ids"}:
        raise PlatformError("invalid_resource")
    if "name" in data:
        obj.name = text(data["name"], "name", 120)
    if "material_ids" in data:
        set_members(obj, data["material_ids"])
    db.session.commit()
    return serialize(obj)


@platform_bp.route("/api/skill-packages", methods=["GET", "POST"])
def skills():
    if request.method == "GET":
        return {"skills": [serialize(obj) for obj in SkillPackage.query.filter_by(class_id=g.user.class_id, enabled=True).order_by(SkillPackage.id)]}
    upload = request.files.get("file")
    if not upload:
        raise PlatformError("invalid_skill_package")
    raw = upload.stream.read(current_app.config["AI_SKILL_UPLOAD_BYTES"] + 1)
    package, _ = save_skill(g.user, upload.filename, raw)
    db.session.commit()
    return serialize(package), 201


@platform_bp.route("/api/skill-packages/<int:package_id>", methods=["GET", "PATCH"])
def skill_detail(package_id):
    obj = tenant(SkillPackage, g.user, package_id)
    return serialize(obj) if request.method == "GET" else enabled_update(obj, payload())


@platform_bp.route("/api/tool-connections", methods=["GET", "POST"])
def connections():
    if request.method == "GET":
        return {"connections": [serialize(obj) for obj in ToolConnection.query.filter_by(class_id=g.user.class_id).order_by(ToolConnection.id)],
                "allowed_hosts": current_app.config["AI_TOOL_ALLOWED_HOSTS"],
                "credential_references": [name for name, value in current_app.config["AI_CREDENTIAL_REFERENCES"].items() if g.user.class_id in value["class_ids"]]}
    obj = prepare_connection(payload(), g.user)
    db.session.add(obj); db.session.commit()
    return serialize(obj), 201


@platform_bp.route("/api/tool-connections/<int:connection_id>", methods=["GET", "PATCH"])
def connection_detail(connection_id):
    obj = tenant(ToolConnection, g.user, connection_id)
    return serialize(obj) if request.method == "GET" else enabled_update(obj, payload())


@platform_bp.route("/api/tool-connections/<int:connection_id>/discover", methods=["POST"])
def connection_discover(connection_id):
    obj = tenant(ToolConnection, g.user, connection_id, True)
    definitions = discover_tools(obj)
    db.session.commit()
    return {"definitions": [serialize(value) for value in definitions], "status": "connected"}


@platform_bp.route("/api/app-conversations", methods=["GET", "POST"])
def conversations():
    if request.method == "GET":
        return {"conversations": [serialize(obj) for obj in AppConversation.query.filter_by(class_id=g.user.class_id, owner_id=g.user.id).order_by(AppConversation.id.desc())]}
    application = tenant(AiApplication, g.user, payload().get("application_id"), True)
    if not latest(ApplicationVersion, "application_id", application.id):
        raise PlatformError("application_unpublished", 409)
    obj = AppConversation(class_id=g.user.class_id, owner_id=g.user.id, application_id=application.id)
    db.session.add(obj); db.session.commit()
    return serialize(obj), 201


@platform_bp.route("/api/app-conversations/<int:conversation_id>")
def conversation_detail(conversation_id):
    obj = own_conversation(g.user, conversation_id)
    return {**serialize(obj), "messages": [serialize(m) for m in AppMessage.query.filter_by(conversation_id=obj.id).order_by(AppMessage.id)]}


@platform_bp.route("/api/app-conversations/<int:conversation_id>/messages", methods=["POST"])
def conversation_message(conversation_id):
    obj = own_conversation(g.user, conversation_id)
    return ConversationRunner(g.user, obj, payload()).run()


@platform_bp.route("/api/conversation-runs", methods=["GET"])
def runs():
    objects = ConversationRun.query.filter(ConversationRun.owner_id == g.user.id, ConversationRun.class_id == g.user.class_id, ConversationRun.expires_at > now()).order_by(ConversationRun.created_at.desc()).limit(100).all()
    return {"runs": [{"id": r.id, "origin": r.origin, "status": r.status, "created_at": r.created_at.isoformat(), "error": r.error} for r in objects]}


def own_run(run_id):
    obj = db.session.get(ConversationRun, run_id)
    if (not obj or obj.class_id != g.user.class_id or obj.owner_id != g.user.id
            or obj.expires_at.replace(tzinfo=now().tzinfo) <= now()):
        raise PlatformError("not_found", 404)
    return obj


def run_evidence(obj):
    return {**serialize(obj), "calls": [serialize(c) for c in LlmCall.query.filter_by(run_id=obj.id).order_by(LlmCall.sequence)],
            "events": [serialize(e) for e in RunEvent.query.filter_by(run_id=obj.id).order_by(RunEvent.sequence)]}


@platform_bp.route("/api/conversation-runs/<run_id>", methods=["GET", "DELETE"])
def run_detail(run_id):
    obj = own_run(run_id)
    if request.method == "DELETE":
        if obj.status == "running":
            raise PlatformError("run_in_progress", 409)
        db.session.delete(obj); db.session.commit()
        return {"deleted": True}
    return run_evidence(obj)


@platform_bp.route("/api/conversation-runs/<run_id>/export")
def run_export(run_id):
    obj = own_run(run_id)
    response = make_response(json.dumps(run_evidence(obj), ensure_ascii=False))
    response.headers["Content-Type"] = "application/json; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="trace-{obj.id}.json"'
    return response
