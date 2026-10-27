import os
from pathlib import Path

from flask import current_app
from werkzeug.security import generate_password_hash

from app import db
from app.models import ClassRoom, KnowledgeEntry, Material, User
from app.retrieval import FTS_TABLE, initialize_search_index, replace_entry_index
from app.solver import ensure_all_default_skills
from sqlalchemy import text


def seed_database():
    teacher_password = os.environ.get("SEED_TEACHER_PASSWORD")
    student_password = os.environ.get("SEED_STUDENT_PASSWORD")

    if not teacher_password or not student_password:
        raise RuntimeError(
            "SEED_TEACHER_PASSWORD and SEED_STUDENT_PASSWORD are required"
        )

    initialize_search_index()
    db.session.commit()

    class_a = ClassRoom.query.filter_by(name="A班").first()
    if class_a is None:
        class_a = ClassRoom(name="A班")
        db.session.add(class_a)

    class_b = ClassRoom.query.filter_by(name="B班").first()
    if class_b is None:
        class_b = ClassRoom(name="B班")
        db.session.add(class_b)

    db.session.commit()
    ensure_all_default_skills()

    accounts = [
        ("teacher_a", "teacher", class_a.id, teacher_password),
        ("student_a", "student", class_a.id, student_password),
        ("teacher_b", "teacher", class_b.id, teacher_password),
        ("student_b", "student", class_b.id, student_password),
    ]

    for username, role, class_id, password in accounts:
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(username=username, role=role, class_id=class_id)
            db.session.add(user)
        else:
            user.role = role
            user.class_id = class_id
        user.password_hash = generate_password_hash(password)

    db.session.commit()

    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    upload_folder.mkdir(parents=True, exist_ok=True)

    db.session.execute(text(f"DELETE FROM {FTS_TABLE}"))
    KnowledgeEntry.query.delete()
    Material.query.delete()
    db.session.commit()

    for old_name in ("Class A", "Class B"):
        old_class = ClassRoom.query.filter_by(name=old_name).first()
        if old_class is not None:
            db.session.delete(old_class)
    db.session.commit()

    teacher_a = User.query.filter_by(username="teacher_a").one()
    teacher_b = User.query.filter_by(username="teacher_b").one()

    seed_materials = [
        {
            "title": "A班课程大纲",
            "filename": "class-a-syllabus.md",
            "stored_filename": "class-a-syllabus.md",
            "content_type": "text/markdown",
            "class_id": class_a.id,
            "uploader_id": teacher_a.id,
            "body": "# A班课程大纲\n\n- 第 1 周：介绍\n- 第 2 周：数据建模\n- 第 3 周：Flask 路由\n",
        },
        {
            "title": "B班课程大纲",
            "filename": "class-b-syllabus.txt",
            "stored_filename": "class-b-syllabus.txt",
            "content_type": "text/plain",
            "class_id": class_b.id,
            "uploader_id": teacher_b.id,
            "body": "B班教学资料\n第 1 周：介绍\n第 2 周：认证\n第 3 周：班级隔离\n",
        },
    ]

    entries = []
    for item in seed_materials:
        path = upload_folder / item["stored_filename"]
        path.write_text(item["body"])
        material = Material(
            title=item["title"],
            filename=item["filename"],
            stored_filename=item["stored_filename"],
            content_type=item["content_type"],
            size_bytes=path.stat().st_size,
            class_id=item["class_id"],
            uploader_id=item["uploader_id"],
        )
        entry = KnowledgeEntry(
            material=material,
            class_id=item["class_id"],
            body=item["body"],
        )
        db.session.add(material)
        db.session.add(entry)
        entries.append(entry)

    db.session.flush()
    for entry in entries:
        replace_entry_index(entry)
    db.session.commit()
