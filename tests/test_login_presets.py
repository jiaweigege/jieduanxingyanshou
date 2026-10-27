def test_login_presets_only_on_loopback_when_configured(app, client):
    app.config.update(
        DEMO_TEACHER_PASSWORD="teacher-demo-secret",
        DEMO_STUDENT_PASSWORD="student-demo-secret",
    )

    local = client.get("/login")
    assert local.status_code == 200
    assert b'teacher_a' in local.data
    assert b'student_a' in local.data
    assert b'teacher-demo-secret' in local.data

    remote = client.get("/login", environ_overrides={"REMOTE_ADDR": "192.0.2.10"})
    assert remote.status_code == 200
    assert b'login-preset' not in remote.data
    assert b'teacher-demo-secret' not in remote.data


def test_login_has_no_presets_without_both_passwords(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b'login-preset' not in response.data
