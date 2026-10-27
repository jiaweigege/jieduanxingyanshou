"""Run an isolated, offline UI demonstration; never reads the user's database."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app, db
from app.models import ClassRoom, User
from app.platform_resources import initialize_platform
from app.retrieval import initialize_search_index


def fake_model(_url, _body, _headers, _timeout):
    return 200, json.dumps({"id": "offline-demo", "model": "offline-demo",
                           "choices": [{"message": {"role": "assistant", "content": "这是离线演示回答。你可以展开本次调用，查看实际组装的请求、模板和响应。"}, "finish_reason": "stop"}],
                           "usage": {"total_tokens": 42}}, ensure_ascii=False).encode()


def main():
    with TemporaryDirectory(prefix="campusclaw-platform-demo-") as folder:
        app = create_app({"SECRET_KEY": "offline-demo", "TOKEN_SIGNING_KEY": "offline-demo-signing-key-32-characters-long",
                          "SQLALCHEMY_DATABASE_URI": f"sqlite:///{folder}/demo.db", "UPLOAD_FOLDER": f"{folder}/uploads",
                          "AI_PLATFORM_ENABLED": True, "AI_MODEL_CAPABILITIES": {"offline-demo": {"tools": True}},
                          "ZHIPU_MODEL": "offline-demo", "AI_LLM_TRANSPORT": fake_model})
        with app.app_context():
            db.create_all(); initialize_search_index()
            classroom = ClassRoom(name="演示班")
            db.session.add(classroom); db.session.flush()
            for username, role in (("demo_teacher", "teacher"), ("demo_student", "student")):
                user = User(username=username, class_id=classroom.id, role=role)
                user.password = "offline-demo-password"
                db.session.add(user)
            db.session.commit(); initialize_platform()
        print("Offline UI demo: http://127.0.0.1:5057/apps")
        print("Accounts: demo_teacher / demo_student; password: offline-demo-password; model key: any placeholder")
        try:
            app.run(host="127.0.0.1", port=5057, debug=False, use_reloader=False)
        finally:
            with app.app_context():
                db.session.remove(); db.engine.dispose()


if __name__ == "__main__":
    main()
