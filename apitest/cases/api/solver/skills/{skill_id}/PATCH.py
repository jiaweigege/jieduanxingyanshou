from app.models import SolverSkill


def run(context):
    context.login("teacher_a", "test-password")
    skill_id = context.client.get("/api/solver/skills").get_json()["skills"][0]["id"]
    response = context.client.patch(
        "/api/solver/skills/" + str(skill_id),
        json={"prompt": "先画图，再提示下一步"},
    )
    assert response.status_code == 200
    assert response.get_json()["version"] == 2
    with context.app.app_context():
        skill = SolverSkill.query.filter_by(id=skill_id).one()
        assert skill.prompt == "先画图，再提示下一步"
        assert skill.version == 2
    context.login("student_a", "test-password")
    denied = context.client.patch(
        "/api/solver/skills/" + str(skill_id), json={"prompt": "直接给答案"}
    )
    assert denied.status_code == 403
    with context.app.app_context():
        assert SolverSkill.query.filter_by(id=skill_id).one().version == 2
