import json

from app.models import SolverMessage


def run(context):
    context.login("student_a", "test-password")
    skill_id = context.client.get("/api/solver/skills").get_json()["skills"][0]["id"]
    session_id = context.client.post(
        "/api/solver/sessions", json={"skill_id": skill_id}
    ).get_json()["id"]
    response = context.client.post(
        "/api/solver/sessions/" + str(session_id) + "/messages",
        json={"content": "三角形面积公式怎么用？", "api_key": "test-sentinel-key"},
    )
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    events = context.events(response)
    assert events[0][0] == "sources"
    assert events[-1][0] == "done"
    assert sum(name == "delta" for name, _ in events) >= 2
    sources = events[0][1]["sources"]
    assert sources and sources[0]["material_id"] == context.ids["material_a"]
    assert events[-1][1]["citations"] == [1]
    history = context.client.get("/api/solver/sessions/" + str(session_id)).get_json()
    assert len(history["messages"]) == 2
    assistant = history["messages"][-1]
    assert assistant["id"] == events[-1][1]["message_id"]
    assert assistant["sources"] == sources
    assert "test-sentinel-key" not in str(history)
    with context.app.app_context():
        rows = SolverMessage.query.filter_by(session_id=session_id).order_by(SolverMessage.id).all()
        assert [row.role for row in rows] == ["student", "assistant"]
        assert rows[-1].content == assistant["content"]
        assert json.loads(rows[-1].sources_json) == sources
        assert all(row.class_id == context.ids["class_a"] for row in rows)
