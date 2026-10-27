from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import current_app

from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from app import db

# Register additive platform tables before db.create_all(), including when disabled.
from app import platform_models  # noqa: F401


class ClassRoom(db.Model):
    __tablename__ = "classes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)

    users = db.relationship("User", back_populates="class_room")
    materials = db.relationship("Material", back_populates="class_room")
    knowledge_entries = db.relationship("KnowledgeEntry", back_populates="class_room")
    knowledge_chunks = db.relationship("KnowledgeChunk", back_populates="class_room")
    solver_skills = db.relationship("SolverSkill", back_populates="class_room")

    def __repr__(self):
        return f"<ClassRoom {self.name}>"


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (
        db.CheckConstraint("role IN ('teacher', 'student')", name="valid_user_role"),
        db.UniqueConstraint("id", "class_id", name="uq_user_id_class"),
    )

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=False)

    class_room = db.relationship("ClassRoom", back_populates="users")
    materials = db.relationship("Material", back_populates="uploader")
    auth_tokens = db.relationship(
        "AuthToken", back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def password(self):
        raise AttributeError("password is not a readable attribute")

    @password.setter
    def password(self, value):
        self.password_hash = generate_password_hash(value)

    def verify_password(self, value):
        return check_password_hash(self.password_hash, value)

    @property
    def is_teacher(self):
        return self.role == "teacher"

    def __repr__(self):
        return f"<User {self.username}>"


class AuthToken(db.Model):
    __tablename__ = "auth_tokens"
    __table_args__ = (
        db.Index("ix_auth_tokens_user_id", "user_id"),
        db.Index("ix_auth_tokens_expires_at", "expires_at"),
        db.Index("ix_auth_tokens_revoked_at", "revoked_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    jti = db.Column(db.String(64), nullable=False, unique=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    issued_at = db.Column(db.DateTime(timezone=True), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", back_populates="auth_tokens")

    def __repr__(self):
        return f"<AuthToken {self.jti}>"


class Material(db.Model):
    __tablename__ = "materials"
    __table_args__ = (
        db.UniqueConstraint("id", "class_id", name="uq_material_id_class"),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    content_type = db.Column(db.String(120), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=False)
    uploader_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    class_room = db.relationship("ClassRoom", back_populates="materials")
    uploader = db.relationship("User", back_populates="materials")
    knowledge_entry = db.relationship(
        "KnowledgeEntry",
        back_populates="material",
        uselist=False,
        cascade="all, delete-orphan",
    )
    knowledge_chunks = db.relationship(
        "KnowledgeChunk",
        back_populates="material",
        cascade="all, delete-orphan",
        foreign_keys="KnowledgeChunk.material_id",
    )

    @classmethod
    def create_from_upload(cls, teacher, file_storage, title, upload_folder, max_size):
        if not file_storage or not file_storage.filename:
            raise ValueError("请选择文件")
        if not title or not title.strip():
            raise ValueError("请输入标题")

        original_filename = secure_filename(file_storage.filename)
        if not original_filename:
            raise ValueError("文件名无效")

        suffix = Path(original_filename).suffix.lower()
        if suffix not in {".txt", ".md"}:
            raise ValueError("仅支持 .txt 和 .md 文件")

        file_storage.stream.seek(0, 2)
        size = file_storage.stream.tell()
        file_storage.stream.seek(0)
        if size > max_size:
            raise ValueError("文件过大")

        raw_body = file_storage.stream.read()
        try:
            body = raw_body.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
            if body.startswith("\ufeff"):
                body = body[1:]
        except UnicodeDecodeError as exc:
            raise ValueError("文件必须是有效的 UTF-8 文本") from exc

        stored_filename = f"{uuid4().hex}_{original_filename}"
        upload_path = Path(upload_folder)
        upload_path.mkdir(parents=True, exist_ok=True)
        target = upload_path / stored_filename
        target.write_bytes(raw_body)

        material = cls(
            title=title.strip(),
            filename=original_filename,
            stored_filename=stored_filename,
            content_type=file_storage.content_type or "text/plain",
            size_bytes=size,
            class_id=teacher.class_id,
            uploader_id=teacher.id,
        )
        entry = KnowledgeEntry(
            material=material,
            class_id=teacher.class_id,
            body=body,
        )
        db.session.add(material)
        db.session.add(entry)

        try:
            from app.retrieval import replace_entry_index

            db.session.flush()
            replace_entry_index(entry)
            if current_app.config["AI_PLATFORM_ENABLED"]:
                from app.platform_resources import add_default_material
                add_default_material(material)
            db.session.commit()
        except Exception:
            db.session.rollback()
            target.unlink(missing_ok=True)
            raise

        return material

    @classmethod
    def for_user(cls, user, query=None):
        q = cls.query.filter(cls.class_id == user.class_id)
        if query:
            q = q.outerjoin(KnowledgeEntry).filter(
                db.or_(
                    cls.title.ilike(f"%{query}%"),
                    KnowledgeEntry.body.ilike(f"%{query}%"),
                )
            )
        return q.order_by(cls.created_at.desc(), cls.id.desc())

    @classmethod
    def get_for_user(cls, material_id, user):
        return cls.query.filter(
            cls.id == material_id, cls.class_id == user.class_id
        ).first()

    def __repr__(self):
        return f"<Material {self.title}>"


class KnowledgeEntry(db.Model):
    __tablename__ = "knowledge_entries"
    __table_args__ = (
        db.UniqueConstraint(
            "id", "material_id", "class_id", name="uq_knowledge_entry_source"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(
        db.Integer, db.ForeignKey("materials.id"), nullable=False, unique=True
    )
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    material = db.relationship("Material", back_populates="knowledge_entry")
    class_room = db.relationship("ClassRoom", back_populates="knowledge_entries")
    chunks = db.relationship(
        "KnowledgeChunk",
        back_populates="knowledge_entry",
        cascade="all, delete-orphan",
        foreign_keys="KnowledgeChunk.knowledge_entry_id",
    )

    def __repr__(self):
        return f"<KnowledgeEntry {self.material_id}>"


class KnowledgeChunk(db.Model):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        db.ForeignKeyConstraint(
            ["knowledge_entry_id", "material_id", "class_id"],
            [
                "knowledge_entries.id",
                "knowledge_entries.material_id",
                "knowledge_entries.class_id",
            ],
            name="fk_chunk_knowledge_source",
            ondelete="CASCADE",
        ),
        db.ForeignKeyConstraint(
            ["material_id", "class_id"],
            ["materials.id", "materials.class_id"],
            name="fk_chunk_material_class",
            ondelete="CASCADE",
        ),
        db.CheckConstraint("start_line >= 1", name="ck_chunk_start_line"),
        db.CheckConstraint("end_line >= start_line", name="ck_chunk_line_range"),
        db.Index("ix_knowledge_chunks_class_id", "class_id"),
        db.Index("ix_knowledge_chunks_material_id", "material_id"),
        db.Index("ix_knowledge_chunks_entry_id", "knowledge_entry_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    chunk_id = db.Column(db.String(64), nullable=False, unique=True)
    knowledge_entry_id = db.Column(db.Integer, nullable=False)
    material_id = db.Column(db.Integer, nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=False)
    start_line = db.Column(db.Integer, nullable=False)
    end_line = db.Column(db.Integer, nullable=False)
    body = db.Column(db.Text, nullable=False)
    content_fingerprint = db.Column(db.String(64), nullable=False)

    knowledge_entry = db.relationship(
        "KnowledgeEntry",
        back_populates="chunks",
        foreign_keys=[knowledge_entry_id],
        primaryjoin="KnowledgeEntry.id == KnowledgeChunk.knowledge_entry_id",
        overlaps="material,knowledge_chunks",
    )
    material = db.relationship(
        "Material",
        back_populates="knowledge_chunks",
        foreign_keys=[material_id],
        primaryjoin="Material.id == KnowledgeChunk.material_id",
        overlaps="chunks,knowledge_entry",
    )
    class_room = db.relationship("ClassRoom", back_populates="knowledge_chunks")

    def __repr__(self):
        return f"<KnowledgeChunk {self.chunk_id}>"


class SolverSkill(db.Model):
    __tablename__ = "solver_skills"
    __table_args__ = (
        db.UniqueConstraint("id", "class_id", name="uq_solver_skill_class"),
        db.Index("ix_solver_skills_class_id", "class_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    class_room = db.relationship("ClassRoom", back_populates="solver_skills")


class SolverSession(db.Model):
    __tablename__ = "solver_sessions"
    __table_args__ = (
        db.ForeignKeyConstraint(
            ["skill_id", "class_id"], ["solver_skills.id", "solver_skills.class_id"],
            name="fk_solver_session_skill_class",
        ),
        db.ForeignKeyConstraint(
            ["student_id", "class_id"], ["users.id", "users.class_id"],
            name="fk_solver_session_student_class",
        ),
        db.UniqueConstraint("id", "class_id", name="uq_solver_session_class"),
        db.Index("ix_solver_sessions_student_id", "student_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.Integer, db.ForeignKey("classes.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    skill_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    skill = db.relationship("SolverSkill", foreign_keys=[skill_id])
    student = db.relationship("User", foreign_keys=[student_id])
    messages = db.relationship(
        "SolverMessage", back_populates="session", cascade="all, delete-orphan",
        order_by="SolverMessage.id",
    )


class SolverMessage(db.Model):
    __tablename__ = "solver_messages"
    __table_args__ = (
        db.ForeignKeyConstraint(
            ["session_id", "class_id"], ["solver_sessions.id", "solver_sessions.class_id"],
            name="fk_solver_message_session_class", ondelete="CASCADE",
        ),
        db.CheckConstraint("role IN ('student', 'assistant')", name="ck_solver_message_role"),
        db.Index("ix_solver_messages_session_id", "session_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, nullable=False)
    class_id = db.Column(db.Integer, nullable=False)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    sources_json = db.Column(db.Text, nullable=False, default="[]")
    skill_version = db.Column(db.Integer, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    session = db.relationship("SolverSession", back_populates="messages")
