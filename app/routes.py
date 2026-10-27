from functools import wraps

import bleach
import markdown
from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    stream_with_context,
    url_for,
)
from sqlalchemy import text
from werkzeug.exceptions import RequestEntityTooLarge

from app import db
from app.auth import (
    AuthError,
    authenticate_access_token,
    issue_access_token,
    parse_bearer_header,
    revoke_auth_token,
)
from app.models import Material, SolverSession, SolverSkill, User
from app.qa import (
    AIUnavailable,
    InvalidAPIKey,
    InvalidQuestion,
    ProviderAuthFailed,
    answer_question,
)
from app.retrieval import RetrievalUnavailable, search_knowledge
from app.solver import (
    ensure_default_skill, message_dict, save_success, session_dict, skill_dict,
    solver_messages, validate_guidance, validate_skill_payload,
)
from app.solver_stream import stream_guidance
from app.qa import normalize_api_key, normalize_question, retrieve_answer_sources
from app.platform_resources import PlatformError
import json

main_bp = Blueprint("main", __name__)

PUBLIC_ENDPOINTS = {
    "main.index",
    "main.health",
    "main.login",
    "main.materials",
    "main.api_auth_token",
    "main.openapi_document",
    "main.swagger_docs",
    "static",
}


def teacher_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not g.user.is_teacher:
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


def student_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user.is_teacher:
            return {"error": "forbidden"}, 403
        return view(*args, **kwargs)
    return wrapped_view


def not_found():
    return {"error": "not_found"}, 404


def render_markdown(body):
    html = markdown.markdown(
        body,
        extensions=[
            "extra",
            "sane_lists",
            "toc",
            "pymdownx.tasklist",
            "pymdownx.superfences",
            "pymdownx.magiclink",
        ],
    )
    allowed_tags = [
        "a", "abbr", "b", "blockquote", "br", "code", "em", "h1", "h2", "h3",
        "h4", "h5", "h6", "hr", "i", "img", "li", "ol", "p", "pre", "q",
        "span", "strong", "table", "tbody", "td", "th", "thead", "tr", "ul",
        "input",
    ]
    allowed_attrs = {
        "*": ["class"],
        "a": ["href", "title"],
        "img": ["src", "alt", "title"],
        "input": ["type", "checked", "disabled"],
    }
    return bleach.clean(
        html,
        tags=allowed_tags,
        attributes=allowed_attrs,
        protocols=["http", "https", "mailto"],
        strip=True,
    )


@main_bp.before_app_request
def load_logged_in_user():
    g.user = None
    g.auth_token = None

    if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    if not request.path.startswith("/api/"):
        return None

    try:
        encoded = parse_bearer_header(request.headers.get("Authorization"))
        g.user, g.auth_token = authenticate_access_token(encoded)
    except AuthError as exc:
        return {"error": exc.code}, 401
    return None


@main_bp.after_app_request
def prevent_knowledge_answer_caching(response):
    if request.path == "/api/knowledge/answer":
        response.headers["Cache-Control"] = "no-store"
    return response


@main_bp.route("/")
def index():
    return redirect(url_for("main.materials"))


@main_bp.route("/health")
def health():
    db.session.execute(text("SELECT 1"))
    return {"status": "ok"}, 200


@main_bp.route("/login", methods=("GET",))
def login():
    presets = None
    if request.remote_addr in {"127.0.0.1", "::1"}:
        teacher_password = current_app.config.get("DEMO_TEACHER_PASSWORD")
        student_password = current_app.config.get("DEMO_STUDENT_PASSWORD")
        if teacher_password and student_password:
            presets = (
                {"label": "教师账号", "username": "teacher_a", "password": teacher_password},
                {"label": "学生账号", "username": "student_a", "password": student_password},
            )
    return render_template("login.html", presets=presets)


@main_bp.route("/api/auth/token", methods=("POST",))
def api_auth_token():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {"error": "invalid_credentials"}, 401
    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        return {"error": "invalid_credentials"}, 401

    user = User.query.filter_by(username=username.strip()).first()
    if user is None or not user.verify_password(password):
        return {"error": "invalid_credentials"}, 401

    try:
        encoded, _grant = issue_access_token(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Unable to issue access token")
        return {"error": "token_issue_failed"}, 500
    return {
        "access_token": encoded,
        "token_type": "Bearer",
        "expires_in": current_app.config["ACCESS_TOKEN_TTL_SECONDS"],
    }, 200


@main_bp.route("/api/auth/logout", methods=("POST",))
def api_auth_logout():
    revoke_auth_token(g.auth_token)
    db.session.commit()
    return {"status": "logged_out"}, 200


@main_bp.route("/materials")
def materials():
    return render_template("materials.html")


@main_bp.route("/solver")
def solver_page():
    return render_template("solver.html")


@main_bp.route("/openapi.json")
def openapi_document():
    return send_from_directory(current_app.root_path, "openapi.json", mimetype="application/json")


@main_bp.route("/docs")
def swagger_docs():
    return render_template("swagger.html")


@main_bp.route("/api/me")
def api_me():
    return {
        "id": g.user.id,
        "username": g.user.username,
        "role": g.user.role,
        "class": {
            "id": g.user.class_room.id,
            "name": g.user.class_room.name,
        },
    }


@main_bp.route("/api/materials")
def api_materials():
    query = request.args.get("q", "").strip()
    materials = Material.for_user(g.user, query=query).all()
    return {
        "materials": [
            {
                "id": m.id,
                "title": m.title,
                "filename": m.filename,
                "size_bytes": m.size_bytes,
                "created_at": m.created_at.isoformat(),
                "uploader": m.uploader.username,
                "class": m.class_room.name,
                "summary": (
                    m.knowledge_entry.body[:180] if m.knowledge_entry else ""
                ),
            }
            for m in materials
        ]
    }


@main_bp.route("/api/knowledge/search")
def api_knowledge_search():
    query = request.args.get("q", "")
    if not query or not query.strip():
        return {"error": "invalid_query"}, 400

    try:
        results = search_knowledge(g.user, query)
    except RetrievalUnavailable:
        return {"error": "retrieval_unavailable"}, 503

    return {"results": results}, 200


def _qa_response(payload, status):
    response = make_response(payload, status)
    response.headers["Cache-Control"] = "no-store"
    return response


@main_bp.route("/api/knowledge/answer", methods=("POST",))
def api_knowledge_answer():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _qa_response({"error": "invalid_question"}, 400)
    try:
        result = answer_question(
            g.user,
            payload.get("question"),
            payload.get("api_key"),
        )
    except InvalidQuestion as exc:
        return _qa_response({"error": exc.code}, 400)
    except InvalidAPIKey as exc:
        return _qa_response({"error": exc.code}, 400)
    except ProviderAuthFailed as exc:
        return _qa_response({"error": exc.code}, 422)
    except RetrievalUnavailable:
        return _qa_response({"error": "retrieval_unavailable"}, 503)
    except AIUnavailable as exc:
        return _qa_response({"error": exc.code}, 503)
    except PlatformError:
        return _qa_response({"error": "ai_unavailable"}, 503)
    return _qa_response(result, 200)


@main_bp.route("/api/materials/<int:material_id>")
def api_material_detail(material_id):
    material = Material.get_for_user(material_id, g.user)
    if material is None:
        return not_found()

    return {
        "id": material.id,
        "title": material.title,
        "filename": material.filename,
        "size_bytes": material.size_bytes,
        "created_at": material.created_at.isoformat(),
        "uploader": material.uploader.username,
        "class": material.class_room.name,
        "body_html": (
            render_markdown(material.knowledge_entry.body)
            if material.knowledge_entry
            else ""
        ),
    }


@main_bp.route("/api/materials/<int:material_id>/file")
def api_material_file(material_id):
    material = Material.get_for_user(material_id, g.user)
    if material is None:
        return not_found()

    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        material.stored_filename,
        as_attachment=True,
        download_name=material.filename,
        mimetype=material.content_type,
    )


@main_bp.route("/api/materials/upload", methods=("POST",))
@teacher_required
def api_upload_material():
    try:
        material = Material.create_from_upload(
            teacher=g.user,
            file_storage=request.files.get("file"),
            title=request.form.get("title", ""),
            upload_folder=current_app.config["UPLOAD_FOLDER"],
            max_size=current_app.config["MAX_CONTENT_LENGTH"],
        )
    except ValueError as exc:
        return {"error": str(exc)}, 400
    except RequestEntityTooLarge:
        return {"error": "文件过大"}, 413
    except Exception:
        return {"error": "无法保存资料"}, 500

    return {
        "id": material.id,
        "title": material.title,
        "filename": material.filename,
        "size_bytes": material.size_bytes,
        "created_at": material.created_at.isoformat(),
        "uploader": material.uploader.username,
        "class": material.class_room.name,
    }, 201


@main_bp.route("/api/solver/skills", methods=("GET", "POST"))
def api_solver_skills():
    ensure_default_skill(g.user.class_id)
    if request.method == "GET":
        skills = SolverSkill.query.filter_by(
            class_id=g.user.class_id, enabled=True
        ).order_by(SolverSkill.id).all()
        return {"skills": [skill_dict(skill) for skill in skills]}
    if not g.user.is_teacher:
        return {"error": "forbidden"}, 403
    try:
        fields = validate_skill_payload(request.get_json(silent=True))
    except ValueError:
        return {"error": "invalid_skill"}, 400
    skill = SolverSkill(class_id=g.user.class_id, **fields)
    db.session.add(skill)
    db.session.commit()
    return skill_dict(skill), 201


@main_bp.route("/api/solver/skills/<int:skill_id>", methods=("GET", "PATCH"))
def api_solver_skill_detail(skill_id):
    skill = SolverSkill.query.filter_by(id=skill_id, class_id=g.user.class_id).first()
    if skill is None or not skill.enabled:
        return not_found()
    if request.method == "GET":
        return skill_dict(skill)
    if not g.user.is_teacher:
        return {"error": "forbidden"}, 403
    try:
        fields = validate_skill_payload(request.get_json(silent=True), partial=True)
    except ValueError:
        return {"error": "invalid_skill"}, 400
    for field, value in fields.items():
        setattr(skill, field, value)
    skill.version += 1
    db.session.commit()
    return skill_dict(skill)


@main_bp.route("/api/solver/sessions", methods=("GET", "POST"))
@student_required
def api_solver_sessions():
    if request.method == "GET":
        sessions = SolverSession.query.filter_by(
            class_id=g.user.class_id, student_id=g.user.id
        ).order_by(SolverSession.id.desc()).all()
        return {"sessions": [session_dict(session) for session in sessions]}
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("skill_id"), int):
        return {"error": "invalid_skill"}, 400
    skill = SolverSkill.query.filter_by(
        id=payload["skill_id"], class_id=g.user.class_id, enabled=True
    ).first()
    if skill is None:
        return not_found()
    session = SolverSession(
        class_id=g.user.class_id, student_id=g.user.id, skill_id=skill.id
    )
    db.session.add(session)
    db.session.commit()
    return session_dict(session), 201


def _own_solver_session(session_id):
    return SolverSession.query.filter_by(
        id=session_id, class_id=g.user.class_id, student_id=g.user.id
    ).first()


@main_bp.route("/api/solver/sessions/<int:session_id>")
@student_required
def api_solver_session_detail(session_id):
    session = _own_solver_session(session_id)
    if session is None:
        return not_found()
    return session_dict(session, include_messages=True)


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@main_bp.route("/api/solver/sessions/<int:session_id>/messages", methods=("POST",))
@student_required
def api_solver_message(session_id):
    session = _own_solver_session(session_id)
    if session is None:
        return not_found()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {"error": "invalid_message"}, 400
    try:
        question = normalize_question(
            payload.get("content"), current_app.config["KNOWLEDGE_QA_MAX_QUESTION_CHARS"]
        )
    except InvalidQuestion:
        return {"error": "invalid_message"}, 400
    try:
        api_key = normalize_api_key(payload.get("api_key"))
    except InvalidAPIKey:
        return {"error": "invalid_api_key"}, 400
    try:
        sources = retrieve_answer_sources(
            g.user, question, current_app.config["KNOWLEDGE_QA_MAX_CONTEXT_CHARS"]
        )
    except RetrievalUnavailable:
        return {"error": "retrieval_unavailable"}, 503
    skill = session.skill
    skill_version = skill.version
    model_messages = solver_messages(question, skill, sources) if sources else None
    from app.platform_trace import legacy_trace
    from app.platform_resources import PlatformError
    try:
        trace = legacy_trace(api_key, "legacy-solver", {"skill_id": skill.id, "skill_version": skill_version, "history_replayed": False})
        if trace:
            trace.event("context", {"sources": sources, "skill_prompt_mode": "full", "skill_version": skill_version})
    except PlatformError:
        return {"error": "ai_unavailable"}, 503

    def events():
        yield _sse("sources", {"sources": sources})
        if not sources:
            answer = "本班知识库中没有相关资料。"
            live_session = db.session.get(SolverSession, session_id)
            message = save_success(live_session, question, answer, [], skill_version)
            if trace:
                trace.finish({"answer": answer, "generated": False, "sources": []})
            yield _sse("delta", {"text": answer})
            yield _sse("done", {
                "message_id": message.id, "generated": False, "citations": [],
            })
            return

        answer = ""
        emitted = 0
        try:
            for part in stream_guidance(api_key, model_messages):
                answer += part
                if len(answer) > current_app.config["KNOWLEDGE_QA_MAX_OUTPUT_TOKENS"] * 8:
                    raise AIUnavailable()
                # Hold a short tail so checks can see patterns split across chunks.
                safe_end = max(0, len(answer) - 8)
                if safe_end > emitted:
                    validate_partial = answer[:safe_end]
                    if api_key in validate_partial or "<think>" in validate_partial:
                        raise AIUnavailable()
                    if any(marker in validate_partial for marker in (
                        "最终答案", "答案是", "结果是", "完整解答",
                    )):
                        raise AIUnavailable()
                    yield _sse("delta", {"text": answer[emitted:safe_end]})
                    emitted = safe_end
            citations = validate_guidance(answer, sources, api_key)
            if len(answer) > emitted:
                yield _sse("delta", {"text": answer[emitted:]})
            live_session = db.session.get(SolverSession, session_id)
            message = save_success(live_session, question, answer, sources, skill_version)
            if trace:
                trace.finish({"answer": answer, "generated": True, "sources": sources})
            yield _sse("done", {
                "message_id": message.id, "generated": True,
                "citations": citations,
            })
        except ProviderAuthFailed:
            db.session.rollback()
            if trace:
                trace.finish(error="provider_auth_failed")
            yield _sse("error", {"error": "provider_auth_failed"})
        except AIUnavailable:
            db.session.rollback()
            if trace:
                trace.finish(error="ai_unavailable")
            yield _sse("error", {"error": "ai_unavailable"})
        except Exception:
            current_app.logger.exception("Solver stream failed")
            db.session.rollback()
            yield _sse("error", {"error": "ai_unavailable"})

    response = make_response(stream_with_context(events()))
    response.mimetype = "text/event-stream"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response
