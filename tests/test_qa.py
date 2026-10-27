import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app import create_app, db
from app.models import KnowledgeEntry, Material, User
from app.qa import (
    AIUnavailable,
    InvalidAPIKey,
    InvalidQuestion,
    ProviderAuthFailed,
    ZhipuClient,
    _overlaps,
    answer_question,
    build_messages,
    extract_query_terms,
    normalize_api_key,
    normalize_question,
    parse_answer,
    retrieve_answer_sources,
)
from app.retrieval import RetrievalUnavailable, replace_entry_index
from tests.conftest import login


SENTINEL_KEY_A = "sentinel-user-key-a"
SENTINEL_KEY_B = "sentinel-user-key-b"


def test_repository_has_no_server_zhipu_key_or_key_shaped_secret():
    root = Path(__file__).resolve().parents[1]
    text_suffixes = {".py", ".js", ".html", ".css", ".md", ".yml", ".yaml", ".txt"}
    text_files = [root / ".env.example", root / "Dockerfile", root / "config.py"]
    text_files.extend(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in text_suffixes
        and not {".venv", ".pytest_cache", "__pycache__", "instance"}.intersection(
            path.parts
        )
    )
    combined = "\n".join(path.read_text(errors="replace") for path in set(text_files))
    assert not re.search(r"(?:^|\n)\s*ZHIPU_API_KEY\s*[:=]", combined)
    assert not re.search(r"\b[a-fA-F0-9]{32}\.[A-Za-z0-9_-]{16,}\b", combined)


def _add_entry(app, seed_users, class_key, uploader_key, title, body):
    with app.app_context():
        material = Material(
            title=title,
            filename=f"{title}.md",
            stored_filename=f"{title}-{Material.query.count()}.md",
            content_type="text/markdown",
            size_bytes=len(body.encode()),
            class_id=seed_users[class_key],
            uploader_id=seed_users[uploader_key],
        )
        entry = KnowledgeEntry(material=material, class_id=material.class_id, body=body)
        db.session.add_all([material, entry])
        db.session.flush()
        replace_entry_index(entry)
        db.session.commit()
        return material.id


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ZHIPU_API_URL": "http://example.test/chat"}, "ZHIPU_API_URL"),
        ({"ZHIPU_MODEL": ""}, "ZHIPU_MODEL"),
        ({"ZHIPU_TIMEOUT_SECONDS": 0}, "ZHIPU_TIMEOUT_SECONDS"),
        ({"ZHIPU_TIMEOUT_SECONDS": "bad"}, "ZHIPU_TIMEOUT_SECONDS"),
        ({"KNOWLEDGE_QA_MAX_QUESTION_CHARS": 0}, "MAX_QUESTION"),
        ({"KNOWLEDGE_QA_MAX_CONTEXT_CHARS": "bad"}, "MAX_CONTEXT"),
        ({"KNOWLEDGE_QA_MAX_OUTPUT_TOKENS": -1}, "MAX_OUTPUT"),
    ],
)
def test_qa_configuration_validation(overrides, message):
    config = {
        "SECRET_KEY": "test-secret",
        "TOKEN_SIGNING_KEY": "test-token-signing-key-that-is-long-enough",
        "TOKEN_ISSUER": "issuer",
        "TOKEN_AUDIENCE": "audience",
    }
    config.update(overrides)
    with pytest.raises(RuntimeError, match=message):
        create_app(config)


def test_qa_configuration_has_no_server_api_key(app):
    assert app.config["ZHIPU_API_URL"].startswith("https://")
    assert app.config["ZHIPU_MODEL"]
    assert app.config["ZHIPU_TIMEOUT_SECONDS"] > 0
    assert "ZHIPU_API_KEY" not in app.config


def test_question_and_api_key_validation():
    assert normalize_question("  磁铁能吸木块吗？  ", 100) == "磁铁能吸木块吗？"
    assert normalize_api_key("  sentinel  ") == "sentinel"
    for value in (None, 123, "", "   "):
        with pytest.raises(InvalidQuestion):
            normalize_question(value, 10)
        with pytest.raises(InvalidAPIKey):
            normalize_api_key(value)
    with pytest.raises(InvalidQuestion):
        normalize_question("太长了", 2)


def test_query_term_extraction_is_bounded_and_supports_short_chinese():
    terms = extract_query_terms("  磁铁能吸木块吗？ GLM-4  磁铁  ")
    values = [value for value, _weight in terms]
    assert "磁铁" in values
    assert "木块" in values
    assert "glm" in values
    assert len(values) == len(set(values))
    assert len(values) <= 64
    assert extract_query_terms("! !") == []


def test_qa_retrieval_handles_wording_difference_and_class_scope(app, seed_users):
    material_id = _add_entry(
        app,
        seed_users,
        "class_a_id",
        "teacher_a_id",
        "科学资料",
        "磁铁不能吸引木块。条形磁铁两端吸力最强。",
    )
    _add_entry(
        app,
        seed_users,
        "class_b_id",
        "teacher_b_id",
        "B班秘密",
        "磁铁能吸木块吗？这是 B 班秘密内容。",
    )
    with app.app_context():
        user = db.session.get(User, seed_users["student_a_id"])
        sources = retrieve_answer_sources(user, "磁铁能吸木块吗？", 6000)
        assert sources
        assert sources[0]["material_id"] == material_id
        assert sources[0]["material_title"] == "科学资料"
        assert "B班秘密" not in json.dumps(sources, ensure_ascii=False)
        assert set(sources[0]) == {
            "number",
            "material_id",
            "material_title",
            "chunk_id",
            "start_line",
            "end_line",
            "passage",
            "detail_url",
            "file_url",
        }


def test_qa_retrieval_is_stable_limited_and_context_bounded(app, seed_users):
    for index in range(6):
        _add_entry(
            app,
            seed_users,
            "class_a_id",
            "teacher_a_id",
            f"磁铁资料{index}",
            f"磁铁能够吸引铁钉。第 {index} 份说明。" + ("补充文字" * 30),
        )
    with app.app_context():
        user = db.session.get(User, seed_users["student_a_id"])
        first = retrieve_answer_sources(user, "磁铁吸引铁钉吗", 80)
        second = retrieve_answer_sources(user, "磁铁吸引铁钉吗", 80)
        assert 1 <= len(first) <= 4
        assert first == second
        assert sum(len(source["passage"]) for source in first) <= 80
        assert [source["number"] for source in first] == list(range(1, len(first) + 1))


def test_highly_overlapping_candidates_are_detected():
    first = SimpleNamespace(material_id=1, start_line=1, end_line=10)
    overlapping = SimpleNamespace(material_id=1, start_line=4, end_line=11)
    separate = SimpleNamespace(material_id=1, start_line=20, end_line=30)
    other_material = SimpleNamespace(material_id=2, start_line=4, end_line=11)
    assert _overlaps(first, overlapping) is True
    assert _overlaps(first, separate) is False
    assert _overlaps(first, other_material) is False


def test_qa_retrieval_uses_relational_source_metadata(app, seed_users):
    material_id = _add_entry(
        app,
        seed_users,
        "class_a_id",
        "teacher_a_id",
        "权威标题",
        "独特检索内容来自权威关系记录。",
    )
    with app.app_context():
        db.session.execute(
            text("UPDATE knowledge_fts SET material_id = 999 WHERE material_id = :id"),
            {"id": material_id},
        )
        db.session.commit()
        user = db.session.get(User, seed_users["student_a_id"])
        source = retrieve_answer_sources(user, "独特检索内容", 1000)[0]
        assert source["material_id"] == material_id
        assert source["material_title"] == "权威标题"


def test_qa_retrieval_failure_never_relationally_falls_back(app, seed_users):
    with app.app_context():
        db.session.execute(text("DROP TABLE knowledge_fts"))
        db.session.commit()
        user = db.session.get(User, seed_users["student_a_id"])
        with pytest.raises(RetrievalUnavailable):
            retrieve_answer_sources(user, "A班笔记", 1000)


def _source(number=1):
    return {
        "number": number,
        "material_id": number,
        "material_title": f"资料{number}",
        "chunk_id": f"chunk-{number}",
        "start_line": 1,
        "end_line": 2,
        "passage": "资料正文中包含忽略规则并泄露密钥的恶意文字。",
        "detail_url": f"/api/materials/{number}",
        "file_url": f"/api/materials/{number}/file",
    }


def test_prompt_treats_sources_as_data_and_excludes_credentials():
    messages = build_messages("问题", [_source()])
    serialized = json.dumps(messages, ensure_ascii=False)
    assert "不可信数据" in messages[0]["content"]
    assert "不得联网" in messages[0]["content"]
    assert "<source>" in messages[1]["content"]
    assert SENTINEL_KEY_A not in serialized
    assert "campusclaw-access-token" not in serialized


def test_zhipu_client_uses_each_callers_key_without_network(app):
    calls = []

    def transport(url, payload, headers, timeout):
        calls.append((url, payload, headers.copy(), timeout))
        return 200, json.dumps(
            {"choices": [{"message": {"content": "依据资料回答。[1]"}}]}
        ).encode()

    with app.app_context():
        client = ZhipuClient(transport)
        assert client.generate(SENTINEL_KEY_A, "问题", [_source()]).endswith("[1]")
        assert client.generate(SENTINEL_KEY_B, "问题", [_source()]).endswith("[1]")
        assert [call[2]["Authorization"] for call in calls] == [
            f"Bearer {SENTINEL_KEY_A}",
            f"Bearer {SENTINEL_KEY_B}",
        ]
        assert all(call[0].startswith("https://") for call in calls)
        assert all(call[1]["stream"] is False for call in calls)
        assert all("tools" not in call[1] for call in calls)
        assert all(SENTINEL_KEY_A not in json.dumps(call[1]) for call in calls)


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"{}",
        b'{"choices": []}',
        b'{"choices": [{"message": {"content": null}}]}',
        b'{"choices": [{"message": {"content": ""}}]}',
        b'{"choices": [{"message": {"content": "no citation"}}]}',
        b'{"choices": [{"message": {"content": "bad [2]"}}]}',
    ],
)
def test_answer_parser_rejects_malformed_or_unverifiable_output(body):
    with pytest.raises(AIUnavailable):
        parse_answer(body, 1, 100)


def test_answer_parser_removes_reasoning_wrapper():
    body = json.dumps(
        {"choices": [{"message": {"content": "<think>hidden</think>答案 [1]"}}]}
    ).encode()
    assert parse_answer(body, 1, 100) == "答案 [1]"


@pytest.mark.parametrize(
    ("status", "exception"),
    [(401, ProviderAuthFailed), (403, ProviderAuthFailed), (429, AIUnavailable), (500, AIUnavailable)],
)
def test_zhipu_client_maps_statuses_without_retry(app, status, exception):
    calls = 0

    def transport(_url, _payload, _headers, _timeout):
        nonlocal calls
        calls += 1
        return status, b'{"secret":"must-not-surface"}'

    with app.app_context(), pytest.raises(exception):
        ZhipuClient(transport).generate(SENTINEL_KEY_A, "问题", [_source()])
    assert calls == 1


def test_zhipu_client_hides_transport_exception_and_logs(app, caplog):
    def transport(_url, _payload, _headers, _timeout):
        raise RuntimeError(f"upstream included {SENTINEL_KEY_A}")

    with app.app_context(), pytest.raises(AIUnavailable):
        ZhipuClient(transport).generate(SENTINEL_KEY_A, "问题", [_source()])
    assert SENTINEL_KEY_A not in caplog.text


def test_zhipu_client_maps_timeout_without_retry(app):
    calls = 0

    def transport(_url, _payload, _headers, _timeout):
        nonlocal calls
        calls += 1
        raise TimeoutError("simulated timeout")

    with app.app_context(), pytest.raises(AIUnavailable):
        ZhipuClient(transport).generate(SENTINEL_KEY_A, "问题", [_source()])
    assert calls == 1


def test_answer_service_skips_model_without_sources(app, seed_users):
    class NeverClient:
        def generate(self, *_args):
            raise AssertionError("model must not be called")

    with app.app_context():
        user = db.session.get(User, seed_users["student_a_id"])
        result = answer_question(user, "完全不存在的独特问题", SENTINEL_KEY_A, NeverClient())
        assert result["generated"] is False
        assert result["sources"] == []


def test_answer_service_passes_only_current_key(app, seed_users):
    class RecordingClient:
        def __init__(self):
            self.keys = []

        def generate(self, api_key, _question, _sources):
            self.keys.append(api_key)
            return "答案 [1]"

    recorder = RecordingClient()
    with app.app_context():
        user = db.session.get(User, seed_users["student_a_id"])
        answer_question(user, "A班笔记", SENTINEL_KEY_A, recorder)
        answer_question(user, "A班笔记", SENTINEL_KEY_B, recorder)
    assert recorder.keys == [SENTINEL_KEY_A, SENTINEL_KEY_B]


def _successful_transport(_url, _payload, _headers, _timeout):
    return 200, json.dumps(
        {"choices": [{"message": {"content": "这是依据本班资料的回答。[1]"}}]}
    ).encode()


def test_answer_api_contract_and_no_store(client, app, seed_users):
    app.config["ZHIPU_TRANSPORT"] = _successful_transport
    login(client, "student_a", "student-password")
    response = client.post(
        "/api/knowledge/answer",
        json={"question": "A班笔记讲了什么", "api_key": SENTINEL_KEY_A},
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    data = response.get_json()
    assert set(data) == {"question", "answer", "generated", "sources"}
    assert data["generated"] is True
    assert data["answer"].endswith("[1]")
    assert SENTINEL_KEY_A not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({}, "invalid_question"),
        ({"question": 1, "api_key": SENTINEL_KEY_A}, "invalid_question"),
        ({"question": " ", "api_key": SENTINEL_KEY_A}, "invalid_question"),
        ({"question": "A班笔记"}, "invalid_api_key"),
        ({"question": "A班笔记", "api_key": 1}, "invalid_api_key"),
        ({"question": "A班笔记", "api_key": " "}, "invalid_api_key"),
        ({"question": "问" * 501, "api_key": SENTINEL_KEY_A}, "invalid_question"),
    ],
)
def test_answer_api_validates_question_and_key(client, seed_users, payload, error):
    login(client, "student_a", "student-password")
    response = client.post("/api/knowledge/answer", json=payload)
    assert response.status_code == 400
    assert response.get_json() == {"error": error}
    assert response.headers["Cache-Control"] == "no-store"


def test_answer_api_requires_application_bearer(client):
    response = client.post(
        "/api/knowledge/answer",
        json={"question": "A班笔记", "api_key": SENTINEL_KEY_A},
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": "missing_token"}
    assert response.headers["Cache-Control"] == "no-store"


def test_answer_api_ignores_identity_and_model_overrides(client, app, seed_users):
    captured = {}

    def transport(_url, payload, _headers, _timeout):
        captured.update(payload)
        return _successful_transport(None, None, None, None)

    app.config["ZHIPU_TRANSPORT"] = transport
    login(client, "student_a", "student-password")
    response = client.post(
        "/api/knowledge/answer",
        json={
            "question": "A班笔记",
            "api_key": SENTINEL_KEY_A,
            "class_id": seed_users["class_b_id"],
            "role": "teacher",
            "user_id": seed_users["teacher_b_id"],
            "model": "attacker-model",
        },
    )
    assert response.status_code == 200
    assert captured["model"] == app.config["ZHIPU_MODEL"]
    body = response.get_data(as_text=True)
    assert "B班" not in body
    assert "attacker-model" not in body


def test_answer_api_no_cross_class_match_means_no_upstream_call(client, app, seed_users):
    def transport(*_args):
        raise AssertionError("other-class query must not call provider")

    app.config["ZHIPU_TRANSPORT"] = transport
    _add_entry(
        app,
        seed_users,
        "class_b_id",
        "teacher_b_id",
        "B班专属资料",
        "跨班绝密短语只属于 B 班。",
    )
    login(client, "student_a", "student-password")
    response = client.post(
        "/api/knowledge/answer",
        json={"question": "跨班绝密短语", "api_key": SENTINEL_KEY_A},
    )
    assert response.status_code == 200
    assert response.get_json()["generated"] is False
    assert response.get_json()["sources"] == []


@pytest.mark.parametrize(
    ("status", "expected_status", "error"),
    [(401, 422, "provider_auth_failed"), (403, 422, "provider_auth_failed"), (429, 503, "ai_unavailable"), (500, 503, "ai_unavailable")],
)
def test_answer_api_maps_provider_failures(
    client, app, seed_users, status, expected_status, error
):
    app.config["ZHIPU_TRANSPORT"] = lambda *_args: (status, b"sensitive upstream body")
    login(client, "student_a", "student-password")
    response = client.post(
        "/api/knowledge/answer",
        json={"question": "A班笔记", "api_key": SENTINEL_KEY_A},
    )
    assert response.status_code == expected_status
    assert response.get_json() == {"error": error}
    assert SENTINEL_KEY_A not in response.get_data(as_text=True)
    assert "sensitive upstream body" not in response.get_data(as_text=True)


def test_answer_api_retrieval_failure_does_not_call_provider(client, app, seed_users):
    app.config["ZHIPU_TRANSPORT"] = lambda *_args: (_ for _ in ()).throw(
        AssertionError("provider must not be called")
    )
    login(client, "student_a", "student-password")
    with app.app_context():
        db.session.execute(text("DROP TABLE knowledge_fts"))
        db.session.commit()
    response = client.post(
        "/api/knowledge/answer",
        json={"question": "A班笔记", "api_key": SENTINEL_KEY_A},
    )
    assert response.status_code == 503
    assert response.get_json() == {"error": "retrieval_unavailable"}


def test_answer_api_does_not_log_personal_key_or_prompt(client, app, seed_users, caplog):
    app.config["ZHIPU_TRANSPORT"] = lambda *_args: (500, b"upstream secret")
    login(client, "student_a", "student-password")
    question = "A班笔记中的敏感测试问题"
    response = client.post(
        "/api/knowledge/answer",
        json={"question": question, "api_key": SENTINEL_KEY_A},
    )
    assert response.status_code == 503
    assert SENTINEL_KEY_A not in caplog.text
    assert question not in caplog.text
    assert "upstream secret" not in caplog.text


def test_existing_cross_class_source_urls_remain_protected(client, seed_users):
    login(client, "student_a", "student-password")
    assert client.get(f"/api/materials/{seed_users['material_b_id']}").status_code == 404
    assert client.get(f"/api/materials/{seed_users['material_b_id']}/file").status_code == 404
