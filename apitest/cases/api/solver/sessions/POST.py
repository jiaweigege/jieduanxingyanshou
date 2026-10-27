from app.models import SolverSession


def run(context):
    context.login("student_a", "test-password")
    skill_id = context.client.get("/api/solver/skills").get_json()["skills"][0]["id"]
    response = context.client.post("/api/solver/sessions", json={
        "skill_id": skill_id, "class_id": context.ids["class_b"],
        "student_id": context.ids["student_b"],
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data["skill_id"] == skill_id
    with context.app.app_context():
        session = SolverSession.query.filter_by(id=data["id"]).one()
        assert session.class_id == context.ids["class_a"]
        assert session.student_id == context.ids["student_a"]
    own = context.client.get("/api/solver/sessions").get_json()["sessions"]
    assert [item["id"] for item in own] == [data["id"]]
    context.login("student_b", "test-password")
    other = context.client.get("/api/solver/sessions/" + str(data["id"]))
    absent = context.client.get("/api/solver/sessions/999999")
    assert other.status_code == absent.status_code == 404
    assert other.get_json() == absent.get_json() == {"error": "not_found"}
