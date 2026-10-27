from app import db
from app.models import ClassRoom, Material, User


def test_seed_creates_expected_data(app, monkeypatch):
    monkeypatch.setenv("SEED_TEACHER_PASSWORD", "teacher-secret")
    monkeypatch.setenv("SEED_STUDENT_PASSWORD", "student-secret")

    result = app.test_cli_runner().invoke(args=["seed"])
    assert result.exit_code == 0, result.output

    with app.app_context():
        assert ClassRoom.query.count() == 2
        assert User.query.count() == 4
        assert Material.query.count() == 2

        teacher = User.query.filter_by(username="teacher_a").one()
        student = User.query.filter_by(username="student_a").one()
        assert teacher.role == "teacher"
        assert student.role == "student"
        assert teacher.class_room.name == "A班"
        assert student.class_room.name == "A班"
        assert teacher.password_hash != "teacher-secret"
        assert student.password_hash != "student-secret"
