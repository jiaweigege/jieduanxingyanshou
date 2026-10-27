# Proposal

## Why

The classroom application needs a secure baseline before any advanced teaching features are added: teachers and students must log in, only teachers may contribute materials, and every knowledge-base query must respect the user’s class boundary. The project also needs a reproducible local runtime, a health endpoint, and a usable classroom web experience that can grow into the course’s later knowledge features.

## What Changes

- Add username/password login for teacher and student accounts.
- Require authentication for protected pages and redirect unauthenticated visitors to the login page.
- Add role-based authorization so only teachers can upload teaching materials.
- Treat each class as a server-enforced data boundary for material listing, detail, and file access.
- Use `class_id` as the tenant boundary inside one database instance.
- Keep each user in a fixed class; request parameters cannot switch classes.
- Restrict teacher uploads to `.txt` and `.md` files.
- Validate upload extension and size before accepting a file.
- Parse the uploaded body and write `materials` and `knowledge_entries` in one database transaction.
- Ensure failed parsing or database writes leave no rows or uploaded file behind.
- Serve material detail and file content only through authenticated, class-scoped APIs.
- Do not statically expose `/uploads`.
- Provide a web login page and materials page.
- Provide `/api/me`.
- Return `401` for unauthenticated API requests and redirect unauthenticated pages to login.
- Render uploaded Markdown safely with GitHub-Flavored Markdown support.
- Provide a 品牌红色中文界面ed interface with light/dark mode, list/grid views, class search, command palette, upload progress, and toast notifications.
- Provide deterministic local seed data for two classes and representative teacher/student accounts.
- Store passwords only as salted hashes and keep runtime secrets in server-side environment variables.
- Provide Docker Compose startup and an unauthenticated `GET /health` endpoint.

## Capabilities

### New Capabilities

- `class-knowledge`: Account login, role-based upload authority, class-isolated knowledge-base storage, knowledge-entry indexing, authenticated material APIs, safe Markdown rendering, and the classroom web experience.

### Modified Capabilities

- None. This is the first capability for the project.

## Non-goals

This course iteration does **not** include:

- 检索问答（retrieval QA）或语义搜索。
- 对话助手（conversational assistant）。
- 作业提交与批改（submission / grading / feedback）。
- SSO/OAuth 等外部身份登录。
- 生产 HA、多区域部署或水平扩展。
- 班级管理、邀请或成员维护流程。

## Impact

- Adds the initial web application, account and class models, material storage, knowledge-entry indexing, and authentication/authorization behavior.
- Adds local seed data for verification without committing real passwords.
- Adds Docker Compose configuration, a health endpoint, and environment-based secret handling.
- Requires every material query to be filtered by the authenticated user’s class on the server.
- Adds a richer classroom UI with safe Markdown rendering, search, command palette, upload progress, and theme/view controls.
