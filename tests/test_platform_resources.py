import io
import zipfile
from types import SimpleNamespace

import pytest

from app import db
from app.models import Material, User
from app.platform_models import (
    AiApplication, SkillPackage, SkillVersion, KnowledgeBase, TemplateVersion,
    KnowledgeBaseMaterial, ApplicationVersion,
)
from app.platform_resources import (
    initialize_platform, save_template, render_template_version, parse_skill,
    save_skill, PlatformError, publish_application,
)
from app.qa import retrieve_answer_sources


def test_initialization_is_idempotent_and_versions_fixed(app, seed_users):
    with app.app_context():
        initialize_platform(); initialize_platform()
        a = seed_users["class_a_id"]
        assert AiApplication.query.filter_by(class_id=a).count() == 3
        assert SkillPackage.query.filter_by(class_id=a).count() == 2
        assert ApplicationVersion.query.count() == 6
        assert KnowledgeBaseMaterial.query.count() == 2
        teacher = db.session.get(User, seed_users["teacher_a_id"])
        application = AiApplication.query.filter_by(class_id=a, slug="chat").one()
        original = ApplicationVersion.query.filter_by(application_id=application.id).one()
        template, version = save_template(teacher, {"name": "custom", "body": "主题 {{topic}}", "variables": ["topic"]})
        application.draft = {"template_version_id": version.id}
        new = publish_application(teacher, application)
        db.session.commit()
        assert original.config["template_version_id"] != new.config["template_version_id"]
        assert render_template_version(version, {"topic": "{{other}}"}) == "主题 {{other}}"
        with pytest.raises(PlatformError, match="invalid_template_variables"):
            render_template_version(version, {})


@pytest.mark.parametrize("body", ["{{user.name}}", "{% include 'x' %}", "{{get()}}"])
def test_template_does_not_execute_expressions(app, seed_users, body):
    with app.app_context(), pytest.raises(PlatformError):
        save_template(SimpleNamespace(class_id=seed_users["class_a_id"]), {"name": "x", "body": body})


def package_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for path, content in files:
            archive.writestr(path, content)
    return stream.getvalue()


MAIN = "---\nname: demo\ndescription: 示例\n---\n主指令 unique-main"


def test_skill_import_and_references(app, seed_users):
    with app.app_context():
        user = SimpleNamespace(class_id=seed_users["class_a_id"])
        package, version = save_skill(user, "demo.zip", package_bytes([("SKILL.md", MAIN), ("references/a.md", "ref-a")]))
        _, second = save_skill(user, "SKILL.md", MAIN.encode())
        db.session.commit()
        assert second.version == 2 and version.version == 1
        assert package.source == "upload" and version.body == "主指令 unique-main"


@pytest.mark.parametrize("path", ["../evil.md", "/evil.md", "references/../evil.md", "references/a.py", "references/a.zip", "./SKILL.md", "references\\a.md"])
def test_skill_unsafe_paths(app, path):
    with app.app_context(), pytest.raises(PlatformError, match="invalid_skill_package"):
        parse_skill("demo.zip", package_bytes([("SKILL.md", MAIN), (path, "bad")]))


def test_skill_size_utf8_and_yaml_alias_limits(app):
    with app.app_context():
        for raw in (b"\xff", b"---\nname: &x demo\ndescription: *x\n---\nx", b"---\nname: x\n---\nx"):
            with pytest.raises(PlatformError, match="invalid_skill_package"):
                parse_skill("SKILL.md", raw)
        app.config["AI_SKILL_EXPANDED_BYTES"] = 10
        with pytest.raises(PlatformError):
            parse_skill("demo.zip", package_bytes([("SKILL.md", MAIN)]))


def test_retrieval_limits_before_ranking_and_reports_sent_range(app, seed_users):
    with app.app_context():
        user = db.session.get(User, seed_users["student_a_id"])
        sources = retrieve_answer_sources(user, "A班笔记", 5, material_ids=[seed_users["material_a_id"]])
        assert len(sources) == 1 and len(sources[0]["passage"]) == 5
        assert sources[0]["truncated"] and sources[0]["sent_end_char"] == 5
        assert retrieve_answer_sources(user, "A班笔记", 6000, material_ids=[]) == []
        assert retrieve_answer_sources(user, "B班笔记", 6000, material_ids=[seed_users["material_b_id"]]) == []
