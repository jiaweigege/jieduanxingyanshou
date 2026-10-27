import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    AI_PLATFORM_ENABLED = os.environ.get("AI_PLATFORM_ENABLED", "false")
    AI_MODEL_CAPABILITIES = os.environ.get("AI_MODEL_CAPABILITIES", "{}")
    AI_INPUT_BUDGET = os.environ.get("AI_INPUT_BUDGET", "64000")
    AI_MAX_MODEL_CALLS = os.environ.get("AI_MAX_MODEL_CALLS", "6")
    AI_MAX_TOOL_CALLS = os.environ.get("AI_MAX_TOOL_CALLS", "8")
    AI_TOOL_TIMEOUT = os.environ.get("AI_TOOL_TIMEOUT", "10")
    AI_RUN_TIMEOUT = os.environ.get("AI_RUN_TIMEOUT", "120")
    AI_TOOL_RESULT_CHARS = os.environ.get("AI_TOOL_RESULT_CHARS", "16000")
    AI_TRACE_BYTES = os.environ.get("AI_TRACE_BYTES", "262144")
    AI_TRACE_DAYS = os.environ.get("AI_TRACE_DAYS", "7")
    AI_SKILL_UPLOAD_BYTES = os.environ.get("AI_SKILL_UPLOAD_BYTES", "2097152")
    AI_SKILL_EXPANDED_BYTES = os.environ.get("AI_SKILL_EXPANDED_BYTES", "8388608")
    AI_SKILL_FILES = os.environ.get("AI_SKILL_FILES", "32")
    AI_SKILL_BODY_CHARS = os.environ.get("AI_SKILL_BODY_CHARS", "16000")
    AI_SKILL_REFERENCE_CHARS = os.environ.get("AI_SKILL_REFERENCE_CHARS", "64000")
    AI_TOOL_ALLOWED_HOSTS = os.environ.get("AI_TOOL_ALLOWED_HOSTS", "[]")
    AI_CREDENTIAL_REFERENCES = os.environ.get("AI_CREDENTIAL_REFERENCES", "{}")
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'instance' / 'app.db'}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get(
        "UPLOAD_FOLDER", str(BASE_DIR / "instance" / "uploads")
    )
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024
    ALLOWED_UPLOAD_EXTENSIONS = {".txt", ".md"}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    TOKEN_SIGNING_KEY = os.environ.get("TOKEN_SIGNING_KEY")
    DEMO_TEACHER_PASSWORD = os.environ.get("DEMO_TEACHER_PASSWORD")
    DEMO_STUDENT_PASSWORD = os.environ.get("DEMO_STUDENT_PASSWORD")
    TOKEN_ISSUER = os.environ.get("TOKEN_ISSUER", "campusclaw")
    TOKEN_AUDIENCE = os.environ.get("TOKEN_AUDIENCE", "campusclaw-web")
    ACCESS_TOKEN_TTL_SECONDS = os.environ.get("ACCESS_TOKEN_TTL_SECONDS", "1800")
    ZHIPU_API_URL = os.environ.get(
        "ZHIPU_API_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    )
    ZHIPU_MODEL = os.environ.get("ZHIPU_MODEL", "glm-4-flash")
    ZHIPU_TIMEOUT_SECONDS = os.environ.get("ZHIPU_TIMEOUT_SECONDS", "20")
    KNOWLEDGE_QA_MAX_QUESTION_CHARS = os.environ.get(
        "KNOWLEDGE_QA_MAX_QUESTION_CHARS", "500"
    )
    KNOWLEDGE_QA_MAX_CONTEXT_CHARS = os.environ.get(
        "KNOWLEDGE_QA_MAX_CONTEXT_CHARS", "6000"
    )
    KNOWLEDGE_QA_MAX_OUTPUT_TOKENS = os.environ.get(
        "KNOWLEDGE_QA_MAX_OUTPUT_TOKENS", "512"
    )
