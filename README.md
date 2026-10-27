# CampusClaw AI 应用平台

面向教学场景的课程项目，基于 Flask、SQLAlchemy、SQLite 和 JavaScript 构建，支持教师、学生登录及班级资料隔离。

## 主要功能

- 内置通用对话、知识问答、解题引导三个 AI 应用。
- 支持提示词模板、变量替换和版本管理。
- 检索知识库相关片段，生成带来源引用的回答。
- 提供内置 Skill，支持上传技能指令及参考文件。
- 支持 HTTP 和 MCP 工具接入、调用及结果回填。

## 本地运行

使用支持 SQLite FTS5 trigram 的 Python 环境，在项目目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export TOKEN_SIGNING_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export AI_PLATFORM_ENABLED=true

flask --app wsgi init-db
```

首次运行时，创建演示账号和资料：

```bash
export SEED_TEACHER_PASSWORD="自行设置教师密码"
export SEED_STUDENT_PASSWORD="自行设置学生密码"
flask --app wsgi seed
flask --app wsgi init-platform
```

演示账号为 `teacher_a`、`student_a`、`teacher_b`、`student_b`，密码为上面设置的对应值。`seed` 会重置演示账号密码和资料，已有数据时不要重复执行。

启动服务：

```bash
flask --app wsgi run --port 5001
```

打开 [AI 应用平台](http://127.0.0.1:5001/apps)，登录后在页面输入个人智谱 API Key 即可使用。

Skill 和 MCP 需要配置支持工具调用的模型（`AI_MODEL_CAPABILITIES`）；外部工具需配置允许访问的域名（`AI_TOOL_ALLOWED_HOSTS`）。

## 测试与报告

```bash
pytest
```

- [项目介绍与功能验证报告](output/pdf/campusclaw-verification-report.pdf)
- [详细验证文档](docs/ai-platform-verification.md)
