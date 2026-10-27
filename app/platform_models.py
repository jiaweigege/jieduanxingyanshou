"""Additive platform tables. Credentials are references, never values."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import event, inspect
from sqlalchemy.orm import declared_attr

from app import db


def now():
    return datetime.now(timezone.utc)


def tenant_fk(column, table, name, ondelete=None):
    return db.ForeignKeyConstraint([column, "class_id"], [f"{table}.id", f"{table}.class_id"], name=name, ondelete=ondelete)


class Tenant:
    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=False, index=True)

    @declared_attr
    def __table_args__(cls):
        return (db.UniqueConstraint("id", "class_id"),)


class PromptTemplate(Tenant, db.Model):
    __tablename__ = "platform_templates"
    name = db.Column(db.String(120), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)


class TemplateVersion(Tenant, db.Model):
    __tablename__ = "platform_template_versions"
    __table_args__ = (db.UniqueConstraint("id", "class_id"),
                      db.UniqueConstraint("template_id", "version"),
                      tenant_fk("template_id", "platform_templates", "fk_template_version_tenant"))
    template_id = db.Column(db.Integer, nullable=False)
    version = db.Column(db.Integer, nullable=False)
    body = db.Column(db.Text, nullable=False)
    variables = db.Column(db.JSON, nullable=False, default=list)
    digest = db.Column(db.String(64), nullable=False)


class KnowledgeBase(Tenant, db.Model):
    __tablename__ = "platform_knowledge_bases"
    __table_args__ = (db.UniqueConstraint("id", "class_id"), db.UniqueConstraint("class_id", "name"))
    name = db.Column(db.String(120), nullable=False)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)


class KnowledgeBaseMaterial(db.Model):
    __tablename__ = "platform_knowledge_members"
    base_id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, nullable=False)
    __table_args__ = (
        tenant_fk("base_id", "platform_knowledge_bases", "fk_base_member_tenant", "CASCADE"),
        tenant_fk("material_id", "materials", "fk_base_material_tenant", "CASCADE"),
    )


class SkillPackage(Tenant, db.Model):
    __tablename__ = "platform_skill_packages"
    __table_args__ = (db.UniqueConstraint("id", "class_id"), db.UniqueConstraint("class_id", "name"))
    name = db.Column(db.String(120), nullable=False)
    source = db.Column(db.String(12), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)


class SkillVersion(Tenant, db.Model):
    __tablename__ = "platform_skill_versions"
    __table_args__ = (db.UniqueConstraint("id", "class_id"),
                      db.UniqueConstraint("package_id", "version"),
                      tenant_fk("package_id", "platform_skill_packages", "fk_skill_version_tenant"))
    package_id = db.Column(db.Integer, nullable=False)
    version = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=False)
    body = db.Column(db.Text, nullable=False)
    allowed_tools = db.Column(db.JSON, nullable=True)
    digest = db.Column(db.String(64), nullable=False)


class SkillFile(Tenant, db.Model):
    __tablename__ = "platform_skill_files"
    __table_args__ = (db.UniqueConstraint("id", "class_id"),
                      db.UniqueConstraint("version_id", "path"),
                      tenant_fk("version_id", "platform_skill_versions", "fk_skill_file_tenant"))
    version_id = db.Column(db.Integer, nullable=False)
    path = db.Column(db.String(240), nullable=False)
    content = db.Column(db.Text, nullable=False)
    digest = db.Column(db.String(64), nullable=False)


class ToolConnection(Tenant, db.Model):
    __tablename__ = "platform_tool_connections"
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(8), nullable=False)
    url = db.Column(db.Text, nullable=False)
    credential_ref = db.Column(db.String(120), nullable=True)
    protocol_version = db.Column(db.String(16), nullable=False, default="2025-11-25")
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    definition_digest = db.Column(db.String(64), nullable=True)
    http_config = db.Column(db.JSON, nullable=False, default=dict)


class ToolDefinitionVersion(Tenant, db.Model):
    __tablename__ = "platform_tool_definitions"
    __table_args__ = (db.UniqueConstraint("id", "class_id"),
                      db.UniqueConstraint("connection_id", "digest", "name"),
                      tenant_fk("connection_id", "platform_tool_connections", "fk_tool_definition_tenant"))
    connection_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=False)
    input_schema = db.Column(db.JSON, nullable=False)
    output_schema = db.Column(db.JSON, nullable=True)
    sensitive_parameters = db.Column(db.JSON, nullable=False, default=list)
    digest = db.Column(db.String(64), nullable=False)


class AiApplication(Tenant, db.Model):
    __tablename__ = "platform_applications"
    __table_args__ = (db.UniqueConstraint("id", "class_id"), db.UniqueConstraint("class_id", "slug"))
    slug = db.Column(db.String(120), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    purpose = db.Column(db.Text, nullable=False)
    kind = db.Column(db.String(16), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    draft = db.Column(db.JSON, nullable=False, default=dict)


class ApplicationVersion(Tenant, db.Model):
    __tablename__ = "platform_application_versions"
    __table_args__ = (db.UniqueConstraint("id", "class_id"),
                      db.UniqueConstraint("application_id", "version"),
                      tenant_fk("application_id", "platform_applications", "fk_application_version_tenant"))
    application_id = db.Column(db.Integer, nullable=False)
    version = db.Column(db.Integer, nullable=False)
    config = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)


class AppConversation(Tenant, db.Model):
    __tablename__ = "platform_conversations"
    __table_args__ = (db.UniqueConstraint("id", "class_id"),
                      tenant_fk("application_id", "platform_applications", "fk_conversation_app_tenant"),
                      tenant_fk("owner_id", "users", "fk_conversation_owner_tenant"))
    application_id = db.Column(db.Integer, nullable=False)
    owner_id = db.Column(db.Integer, nullable=False)
    active_run_id = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)


class AppMessage(Tenant, db.Model):
    __tablename__ = "platform_messages"
    __table_args__ = (db.UniqueConstraint("id", "class_id"),
                      tenant_fk("conversation_id", "platform_conversations", "fk_message_conversation_tenant"))
    conversation_id = db.Column(db.Integer, nullable=False)
    run_id = db.Column(db.String(32), nullable=False, index=True)
    role = db.Column(db.String(12), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sources = db.Column(db.JSON, nullable=False, default=list)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)


class ConversationRun(db.Model):
    __tablename__ = "platform_runs"
    __table_args__ = (db.UniqueConstraint("conversation_id", "request_id"),
                      tenant_fk("conversation_id", "platform_conversations", "fk_run_conversation_tenant"),
                      tenant_fk("owner_id", "users", "fk_run_owner_tenant"))
    id = db.Column(db.String(32), primary_key=True, default=lambda: uuid4().hex)
    class_id = db.Column(db.Integer, nullable=False)
    owner_id = db.Column(db.Integer, nullable=False)
    conversation_id = db.Column(db.Integer, nullable=True)
    request_id = db.Column(db.String(64), nullable=False)
    origin = db.Column(db.String(24), nullable=False, default="platform")
    config = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(24), nullable=False, default="running")
    result = db.Column(db.JSON, nullable=True)
    error = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)


class LlmCall(db.Model):
    __tablename__ = "platform_llm_calls"
    __table_args__ = (db.UniqueConstraint("run_id", "sequence"),)
    id = db.Column(db.String(32), primary_key=True, default=lambda: uuid4().hex)
    run_id = db.Column(db.String(32), db.ForeignKey("platform_runs.id", ondelete="CASCADE"), nullable=False)
    sequence = db.Column(db.Integer, nullable=False)
    request = db.Column(db.JSON, nullable=False)
    response = db.Column(db.JSON, nullable=True)
    parsed = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(24), nullable=False, default="pending")
    duration_ms = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)


class RunEvent(db.Model):
    __tablename__ = "platform_run_events"
    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.String(32), db.ForeignKey("platform_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(40), nullable=False)
    data = db.Column(db.JSON, nullable=False)
    __table_args__ = (db.UniqueConstraint("run_id", "sequence"),)


def immutable_version(_mapper, _connection, target):
    if any(attr.history.has_changes() for attr in inspect(target).attrs):
        raise ValueError("immutable_version")


for version_type in (TemplateVersion, SkillVersion, SkillFile, ApplicationVersion, ToolDefinitionVersion):
    event.listen(version_type, "before_update", immutable_version)
