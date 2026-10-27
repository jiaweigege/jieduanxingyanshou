from app.models import SolverSkill


def run(context):
    context.login("teacher_a", "test-password")
    response = context.client.post("/api/solver/skills", json={
        "name": "苏格拉底式引导", "prompt": "逐步追问已知条件",
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data["version"] == 1 and data["prompt"] == "逐步追问已知条件"
    with context.app.app_context():
        skill = SolverSkill.query.filter_by(id=data["id"]).one()
        assert skill.class_id == context.ids["class_a"]
        assert skill.name == data["name"]
    invalid = context.client.post("/api/solver/skills", json={
        "name": "空提示", "prompt": " ",
    })
    assert invalid.status_code == 400
    assert invalid.get_json() == {"error": "invalid_skill"}
