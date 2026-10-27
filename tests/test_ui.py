from pathlib import Path
import re

from tests.conftest import login


def test_login_page_renders_brand(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "课堂知识库".encode() in response.data
    assert b"PKU" not in response.data


def test_materials_page_renders_controls(client, seed_users):
    login(client, "teacher_a", "teacher-password")
    response = client.get("/materials")
    assert response.status_code == 200
    assert b"material-search" in response.data
    assert b"open-command-palette" in response.data
    assert b"upload-form" in response.data
    assert b"theme-toggle" in response.data
    assert b"view-toggle" in response.data
    assert b"knowledge-search-form" in response.data
    assert b"knowledge-search-results" in response.data
    assert b'role="status"' in response.data
    assert "A班".encode() not in response.data
    assert b"teacher_a" not in response.data


def test_knowledge_search_frontend_uses_safe_text_dom(app):
    javascript = (Path(app.root_path) / "static" / "js" / "app.js").read_text()
    function_body = javascript.split("function appendHighlightedText", 1)[1].split(
        "function setKnowledgeStatus", 1
    )[0]
    assert "createTextNode" in function_body
    assert "textContent" in function_body
    assert "innerHTML" not in function_body
    assert 'event.key === "Enter"' in javascript


def test_knowledge_qa_shell_is_hidden_accessible_and_has_no_prefilled_key(
    client, seed_users
):
    response = client.get("/materials")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'role="tablist"' in html
    assert 'id="knowledge-search-tab"' in html
    assert 'aria-controls="knowledge-search-panel"' in html
    assert 'id="knowledge-qa-tab"' in html
    assert 'aria-controls="knowledge-qa-panel"' in html
    assert re.search(
        r'id="knowledge-qa-panel"[^>]*role="tabpanel"[^>]*'
        r'aria-labelledby="knowledge-qa-tab"[^>]*hidden',
        html,
        re.DOTALL,
    )
    key_input = re.search(r'<input\s+[^>]*id="knowledge-qa-key"[^>]*>', html, re.DOTALL)
    assert key_input is not None
    assert 'type="password"' in key_input.group(0)
    assert 'autocomplete="off"' in key_input.group(0)
    assert not re.search(r'\svalue\s*=', key_input.group(0))
    assert "teacher_a" not in html
    assert "student_a" not in html
    assert "sentinel-user-key" not in html


def test_knowledge_qa_frontend_keeps_request_data_ephemeral(app):
    javascript = (Path(app.root_path) / "static" / "js" / "app.js").read_text()
    function_body = javascript.split("async function askKnowledgeQuestion", 1)[1].split(
        "function toast", 1
    )[0]
    assert "CampusAuth.authenticatedFetch" in function_body
    assert 'method: "POST"' in function_body
    assert 'cache: "no-store"' in function_body
    assert "JSON.stringify({ question, api_key: apiKey })" in function_body
    assert 'setAttribute("aria-busy", "true")' in function_body
    assert "knowledgeQaSubmit.disabled = true" in function_body
    assert "knowledgeQaSubmit.disabled = false" in function_body
    assert "sessionStorage" not in function_body
    assert "localStorage" not in function_body
    assert "document.cookie" not in function_body
    assert "URLSearchParams" not in function_body
    assert "state." not in function_body


def test_knowledge_qa_frontend_renders_untrusted_values_as_text(app):
    javascript = (Path(app.root_path) / "static" / "js" / "app.js").read_text()
    actions_body = javascript.split("function appendSourceActions", 1)[1].split(
        "function renderKnowledgeAnswer", 1
    )[0]
    render_body = javascript.split("function renderKnowledgeAnswer", 1)[1].split(
        "async function askKnowledgeQuestion", 1
    )[0]
    assert "document.createElement" in render_body
    assert "textContent" in render_body
    assert "innerHTML" not in render_body
    assert "openMaterial(source.material_id)" in actions_body
    assert "downloadMaterial(source.file_url, source.material_title)" in actions_body


def test_knowledge_qa_frontend_handles_errors_and_clears_on_logout(app):
    javascript = (Path(app.root_path) / "static" / "js" / "app.js").read_text()
    for error in (
        "invalid_question",
        "invalid_api_key",
        "provider_auth_failed",
        "retrieval_unavailable",
        "ai_unavailable",
    ):
        assert error in javascript
    assert 'event.key === "ArrowLeft"' not in javascript
    assert '["ArrowLeft", "ArrowRight"]' in javascript
    assert 'knowledgeQaKey.value = ""' in javascript
    assert 'knowledgeQaQuestion.value = ""' in javascript
    assert "knowledgeQaResults.replaceChildren()" in javascript
    bootstrap_body = javascript.split("async function bootstrap", 1)[1].split(
        "function init", 1
    )[0]
    assert '"/api/knowledge/answer"' not in bootstrap_body
