from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app import db
from app.models import KnowledgeChunk, KnowledgeEntry, Material, User
from app.retrieval import (
    RetrievalUnavailable,
    SearchCapabilityError,
    build_fts_query,
    chunk_text,
    delete_entry_index,
    ensure_search_capabilities,
    replace_entry_index,
    search_knowledge,
    stable_chunk_id,
)
from tests.conftest import login


def _upload(client, content=b"upload searchable phrase\n"):
    return client.post(
        "/api/materials/upload",
        data={
            "title": "可检索上传",
            "file": (BytesIO(content), "searchable.md", "text/markdown"),
        },
        content_type="multipart/form-data",
    )


def test_chunk_model_schema_and_source_constraints(app, seed_users):
    with app.app_context():
        columns = {column["name"] for column in inspect(db.engine).get_columns("knowledge_chunks")}
        assert {
            "chunk_id",
            "knowledge_entry_id",
            "material_id",
            "class_id",
            "start_line",
            "end_line",
            "body",
            "content_fingerprint",
        } <= columns

        entry_a = KnowledgeEntry.query.filter_by(material_id=seed_users["material_a_id"]).one()
        bad = KnowledgeChunk(
            chunk_id="bad-source",
            knowledge_entry_id=entry_a.id,
            material_id=seed_users["material_b_id"],
            class_id=seed_users["class_a_id"],
            start_line=1,
            end_line=1,
            body="invalid",
            content_fingerprint="x" * 64,
        )
        db.session.add(bad)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_chunk_indexes_and_persistent_fts_are_initialized(app):
    with app.app_context():
        index_names = {
            row[1]
            for row in db.session.execute(text("PRAGMA index_list('knowledge_chunks')"))
        }
        assert "ix_knowledge_chunks_class_id" in index_names
        assert "ix_knowledge_chunks_material_id" in index_names
        assert "ix_knowledge_chunks_entry_id" in index_names
        sql = db.session.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'knowledge_fts'")
        ).scalar_one()
        assert "fts5" in sql.lower()
        assert "trigram" in sql.lower()


def test_unsupported_fts_runtime_has_clear_error(app, monkeypatch):
    with app.app_context():
        def fail_execute(*_args, **_kwargs):
            raise OperationalError("probe", {}, RuntimeError("no such module: fts5"))

        monkeypatch.setattr(db.session, "execute", fail_execute)
        with pytest.raises(SearchCapabilityError, match="FTS5.*trigram"):
            ensure_search_capabilities()


def test_chunking_is_line_aware_bounded_and_deterministic():
    body = "# 标题\n\n" + "\n".join(f"第{i}行中文内容" for i in range(1, 180))
    first = chunk_text(body, target_chars=120, max_chars=160, overlap_lines=2)
    second = chunk_text(body, target_chars=120, max_chars=160, overlap_lines=2)
    assert first == second
    assert first[0].start_line == 1
    assert all(chunk.body.strip() for chunk in first)
    assert all(len(chunk.body) <= 160 for chunk in first)
    assert any(left.end_line >= right.start_line for left, right in zip(first, first[1:]))


def test_long_single_line_is_split_without_losing_line_number():
    chunks = chunk_text("中" * 2600, target_chars=1000, max_chars=1200)
    assert [len(chunk.body) for chunk in chunks] == [1200, 1200, 200]
    assert all(chunk.start_line == chunk.end_line == 1 for chunk in chunks)


def test_stable_id_changes_with_content():
    original = chunk_text("stable content", target_chars=20, max_chars=30)[0]
    same = chunk_text("stable content", target_chars=20, max_chars=30)[0]
    changed = chunk_text("changed content", target_chars=20, max_chars=30)[0]
    assert stable_chunk_id(9, original) == stable_chunk_id(9, same)
    assert stable_chunk_id(9, original) != stable_chunk_id(9, changed)


def test_replace_and_delete_index_are_transactional_and_idempotent(app, seed_users):
    with app.app_context():
        entry = KnowledgeEntry.query.filter_by(material_id=seed_users["material_a_id"]).one()
        replace_entry_index(entry)
        db.session.commit()
        first_ids = [chunk.chunk_id for chunk in entry.chunks]

        replace_entry_index(entry)
        db.session.commit()
        second_ids = [chunk.chunk_id for chunk in entry.chunks]
        fts_count = db.session.execute(
            text("SELECT count(*) FROM knowledge_fts WHERE material_id = :id"),
            {"id": entry.material_id},
        ).scalar_one()
        assert second_ids == first_ids
        assert fts_count == len(second_ids)

        delete_entry_index(entry.id)
        db.session.commit()
        assert KnowledgeChunk.query.filter_by(knowledge_entry_id=entry.id).count() == 0
        assert db.session.execute(
            text("SELECT count(*) FROM knowledge_fts WHERE material_id = :id"),
            {"id": entry.material_id},
        ).scalar_one() == 0


def test_upload_is_immediately_searchable(client, seed_users):
    login(client, "teacher_a", "teacher-password")
    response = _upload(client, "上传后的独特检索短语\n".encode())
    assert response.status_code == 201
    result = client.get("/api/knowledge/search?q=独特检索短语")
    assert result.status_code == 200
    assert result.get_json()["results"][0]["material_title"] == "可检索上传"


def test_uploaded_result_sources_are_only_openable_by_the_source_class(
    client, seed_users
):
    login(client, "teacher_a", "teacher-password")
    upload = _upload(client, "来源访问集成短语\n".encode())
    assert upload.status_code == 201
    material_id = upload.get_json()["id"]

    client.post("/api/auth/logout")
    login(client, "student_a", "student-password")
    result = client.get("/api/knowledge/search?q=来源访问集成短语").get_json()[
        "results"
    ][0]
    assert client.get(result["detail_url"]).status_code == 200
    assert client.get(result["file_url"]).status_code == 200

    client.post("/api/auth/logout")
    login(client, "student_b", "student-password")
    assert client.get("/api/knowledge/search?q=来源访问集成短语").get_json() == {
        "results": []
    }
    assert client.get(f"/api/materials/{material_id}").status_code == 404
    assert client.get(f"/api/materials/{material_id}/file").status_code == 404


def test_upload_index_failure_rolls_back_database_and_file(
    client, seed_users, monkeypatch
):
    import app.retrieval as retrieval

    login(client, "teacher_a", "teacher-password")

    def fail_index(_entry):
        raise RuntimeError("simulated FTS failure")

    monkeypatch.setattr(retrieval, "replace_entry_index", fail_index)
    response = _upload(client)
    assert response.status_code == 500
    with client.application.app_context():
        assert Material.query.filter_by(title="可检索上传").count() == 0
        assert not any(Path(client.application.config["UPLOAD_FOLDER"]).glob("*searchable*"))


def test_fts_write_failure_rolls_back_upload(client, seed_users, monkeypatch):
    login(client, "teacher_a", "teacher-password")
    original_execute = db.session.execute

    def fail_fts_insert(statement, *args, **kwargs):
        if str(statement).lstrip().startswith("INSERT INTO knowledge_fts"):
            raise OperationalError("insert", {}, RuntimeError("simulated FTS write failure"))
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db.session, "execute", fail_fts_insert)
    response = _upload(client)
    monkeypatch.setattr(db.session, "execute", original_execute)
    assert response.status_code == 500
    with client.application.app_context():
        db.session.rollback()
        assert Material.query.filter_by(title="可检索上传").count() == 0
        assert not any(Path(client.application.config["UPLOAD_FOLDER"]).glob("*searchable*"))


def test_backfill_is_ordered_idempotent_and_preserves_failed_entry(
    app, seed_users, monkeypatch
):
    import app.cli as cli_module

    with app.app_context():
        entries = KnowledgeEntry.query.order_by(KnowledgeEntry.id).all()
        before_failed = [chunk.chunk_id for chunk in entries[1].chunks]
        failing_id = entries[1].id
        original = cli_module.replace_entry_index

    seen = []

    def fail_second(entry):
        seen.append(entry.id)
        if entry.id == failing_id:
            raise RuntimeError("simulated entry failure")
        return original(entry)

    monkeypatch.setattr(cli_module, "replace_entry_index", fail_second)
    result = app.test_cli_runner().invoke(args=["backfill-knowledge-index"])
    assert result.exit_code != 0
    assert seen == sorted(seen)
    assert "1 failed" in result.output

    with app.app_context():
        failed = db.session.get(KnowledgeEntry, failing_id)
        assert [chunk.chunk_id for chunk in failed.chunks] == before_failed

    monkeypatch.setattr(cli_module, "replace_entry_index", original)
    first = app.test_cli_runner().invoke(args=["backfill-knowledge-index"])
    second = app.test_cli_runner().invoke(args=["backfill-knowledge-index"])
    assert first.exit_code == second.exit_code == 0
    with app.app_context():
        chunk_ids = [row[0] for row in db.session.execute(text("SELECT chunk_id FROM knowledge_fts"))]
        assert len(chunk_ids) == len(set(chunk_ids))


def test_backfill_rolls_back_a_failure_after_old_index_deletion(
    app, seed_users, monkeypatch
):
    with app.app_context():
        entry = KnowledgeEntry.query.filter_by(material_id=seed_users["material_b_id"]).one()
        entry_id = entry.id
        material_id = entry.material_id
        old_chunk_ids = [chunk.chunk_id for chunk in entry.chunks]
        old_fts_ids = [
            row[0]
            for row in db.session.execute(
                text("SELECT chunk_id FROM knowledge_fts WHERE material_id = :id"),
                {"id": material_id},
            )
        ]
        original_execute = db.session.execute

        def fail_target_insert(statement, params=None, *args, **kwargs):
            if (
                str(statement).lstrip().startswith("INSERT INTO knowledge_fts")
                and params
                and params.get("material_id") == material_id
            ):
                raise OperationalError(
                    "insert", {}, RuntimeError("simulated mid-replacement failure")
                )
            return original_execute(statement, params, *args, **kwargs)

        monkeypatch.setattr(db.session, "execute", fail_target_insert)

    result = app.test_cli_runner().invoke(args=["backfill-knowledge-index"])
    monkeypatch.setattr(db.session, "execute", original_execute)
    assert result.exit_code != 0

    with app.app_context():
        entry = db.session.get(KnowledgeEntry, entry_id)
        assert [chunk.chunk_id for chunk in entry.chunks] == old_chunk_ids
        current_fts_ids = [
            row[0]
            for row in db.session.execute(
                text("SELECT chunk_id FROM knowledge_fts WHERE material_id = :id"),
                {"id": material_id},
            )
        ]
        assert current_fts_ids == old_fts_ids


@pytest.mark.parametrize(
    "value",
    ["punctuation !@#$", 'quote " value', "  中文 查询  ", 'x" OR class_id:*'],
)
def test_query_builder_always_returns_one_quoted_phrase(value):
    query = build_fts_query(value)
    assert query.startswith('"') and query.endswith('"')
    assert query.count('"') % 2 == 0


def test_malicious_fts_syntax_is_treated_as_literal_text(app, seed_users):
    with app.app_context():
        user = db.session.get(User, seed_users["student_a_id"])
        assert search_knowledge(user, 'x" OR class_id:*') == []


def test_search_is_class_scoped_ranked_and_has_source_contract(app, seed_users):
    with app.app_context():
        entry_a = KnowledgeEntry.query.filter_by(material_id=seed_users["material_a_id"]).one()
        entry_b = KnowledgeEntry.query.filter_by(material_id=seed_users["material_b_id"]).one()
        entry_a.body = "公共检索词 A班专属内容\n" + "填充行\n" * 20 + "末尾命中短语"
        entry_b.body = "公共检索词 B班秘密内容"
        replace_entry_index(entry_a)
        replace_entry_index(entry_b)
        db.session.commit()

        student_a = db.session.get(User, seed_users["student_a_id"])
        common = search_knowledge(student_a, "公共检索词")
        assert common
        assert {item["material_id"] for item in common} == {seed_users["material_a_id"]}
        assert all(
            {
                "passage",
                "material_title",
                "material_id",
                "chunk_id",
                "start_line",
                "end_line",
                "detail_url",
                "file_url",
            }
            <= item.keys()
            for item in common
        )
        tail = search_knowledge(student_a, "末尾命中短语")
        assert "末尾命中短语" in tail[0]["passage"]
        assert tail[0]["detail_url"].endswith(str(seed_users["material_a_id"]))


def test_search_index_failure_never_falls_back(app, seed_users):
    with app.app_context():
        user = db.session.get(User, seed_users["student_a_id"])
        db.session.execute(text("DROP TABLE knowledge_fts"))
        db.session.commit()
        with pytest.raises(RetrievalUnavailable):
            search_knowledge(user, "任何有效查询")


def test_search_api_auth_validation_scope_and_unavailable(client, seed_users):
    unauthenticated = client.get("/api/knowledge/search?q=公共检索词")
    assert unauthenticated.status_code == 401
    assert "results" not in unauthenticated.get_json()

    login(client, "student_a", "student-password")
    assert client.get("/api/knowledge/search").get_json() == {"error": "invalid_query"}
    assert client.get("/api/knowledge/search?q=%20%20").status_code == 400

    response = client.get(
        "/api/knowledge/search?q=B班笔记&class_id=2",
        json={"class_id": seed_users["class_b_id"]},
        headers={"X-Class-Id": str(seed_users["class_b_id"])},
    )
    assert response.status_code == 200
    assert response.get_json() == {"results": []}

    with client.application.app_context():
        db.session.execute(text("DROP TABLE knowledge_fts"))
        db.session.commit()
    unavailable = client.get("/api/knowledge/search?q=有效检索词")
    assert unavailable.status_code == 503
    assert unavailable.get_json() == {"error": "retrieval_unavailable"}
    assert "results" not in unavailable.get_json()


def test_result_links_recheck_cross_class_permissions(client, seed_users):
    login(client, "student_a", "student-password")
    detail = client.get(f"/api/materials/{seed_users['material_b_id']}")
    file_response = client.get(f"/api/materials/{seed_users['material_b_id']}/file")
    assert detail.status_code == file_response.status_code == 404
    assert "B班笔记".encode() not in detail.data
    assert b"class-b.txt" not in file_response.data
