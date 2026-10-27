import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.platform_models import (
    PromptTemplate, TemplateVersion, KnowledgeBase, KnowledgeBaseMaterial,
    SkillPackage, SkillVersion, SkillFile, ToolConnection, ToolDefinitionVersion,
    AppConversation, AiApplication, ConversationRun, now,
)


def test_new_tables_enforce_tenant_bindings_and_versions(app, seed_users):
    with app.app_context():
        a, b = seed_users["class_a_id"], seed_users["class_b_id"]
        template = PromptTemplate(class_id=a, name="t")
        base = KnowledgeBase(class_id=a, name="k")
        db.session.add_all([template, base]); db.session.commit()
        db.session.add(TemplateVersion(class_id=b, template_id=template.id, version=1,
                                       body="x", variables=[], digest="a" * 64))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        db.session.add(KnowledgeBaseMaterial(class_id=a, base_id=base.id,
                                             material_id=seed_users["material_b_id"]))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        version = TemplateVersion(class_id=a, template_id=template.id, version=1,
                                  body="x", variables=[], digest="a" * 64)
        db.session.add(version); db.session.commit()
        version.body = "changed"
        with pytest.raises(ValueError, match="immutable_version"):
            db.session.commit()
        db.session.rollback()


def test_skill_files_and_tool_definitions_are_versioned(app, seed_users):
    with app.app_context():
        a = seed_users["class_a_id"]
        skill = SkillPackage(class_id=a, name="demo", source="upload")
        connection = ToolConnection(class_id=a, name="demo", kind="mcp", url="https://example.test/mcp", credential_ref="class-key")
        db.session.add_all([skill, connection]); db.session.flush()
        version = SkillVersion(class_id=a, package_id=skill.id, version=1, description="d", body="b", digest="d" * 64)
        db.session.add(version); db.session.flush()
        db.session.add_all([SkillFile(class_id=a, version_id=version.id, path="references/a.md", content="a", digest="x" * 64),
                            SkillFile(class_id=a, version_id=version.id, path="references/a.md", content="b", digest="y" * 64)])
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        assert "credential" not in ToolDefinitionVersion.__table__.columns


def test_conversation_cross_tenant_owner_is_rejected(app, seed_users):
    with app.app_context():
        application = AiApplication(class_id=seed_users["class_a_id"], slug="chat", name="c", purpose="p", kind="chat")
        db.session.add(application); db.session.flush()
        db.session.add(AppConversation(class_id=seed_users["class_a_id"], application_id=application.id, owner_id=seed_users["student_b_id"]))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
