from app.models import SolverSkill


def run(context):
    context.login("student_a", "test-password")
    response = context.client.get("/api/solver/skills")
    assert response.status_code == 200
    skills = response.get_json()["skills"]
    assert skills and skills[0]["name"] == "解题引导"
    with context.app.app_context():
        db_skill = SolverSkill.query.filter_by(
            id=skills[0]["id"], class_id=context.ids["class_a"]
        ).one()
        assert db_skill.prompt == skills[0]["prompt"]
    denied = context.client.post("/api/solver/skills", json={
        "name": "越权", "prompt": "不可写",
    })
    assert denied.status_code == 403
