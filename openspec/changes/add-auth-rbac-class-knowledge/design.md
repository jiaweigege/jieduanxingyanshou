# Design

## Context

The repository has no existing application code, so this change defines the initial implementation. The behavioral contract is in `specs/class-knowledge/spec.md`; this document records the technical approach needed to satisfy it without adding the course’s out-of-scope assistant or grading features.

## Goals / Non-Goals

**Goals:**

- Implement a compact server-rendered web application with login, role checks, class isolation, material uploads, and knowledge-entry indexing.
- Keep authorization and data-boundary enforcement entirely on the server.
- Use one SQLite database instance with `class_id` as the tenant boundary.
- Provide authenticated material detail and file APIs without exposing `/uploads` statically.
- Provide a usable classroom UI with safe Markdown rendering, search, command palette, upload progress, and theme/view controls.
- Use a simple, reproducible local stack that can run with Docker Compose.
- Provide deterministic seed data and automated verification for the security boundaries.

**Non-Goals:**

- Retrieval question answering, chat assistants, assignment workflows, SSO, production HA, and class-management features are excluded.
- The initial data store does not need multi-region replication or enterprise backup tooling.

## Decisions

### Use Flask with SQLite

Use Flask, Flask-SQLAlchemy, and SQLite for the initial implementation. SQLite keeps the local stack simple while still providing relational constraints for users, classes, materials, and knowledge entries. The database file is stored on a persistent Docker volume.

**Alternative considered:** Django with PostgreSQL. That stack is strong for larger applications but adds more moving parts than this course-sized baseline requires.

### Use server-side sessions and salted password hashes

Use Flask’s signed session cookie with `HttpOnly` and `SameSite=Lax`, backed by a `SECRET_KEY` read only from a server-side environment variable. Passwords are hashed with Werkzeug’s password hashing helpers, which generate salted verifiers; login uses the corresponding verification helper.

The login view validates credentials, establishes the session, and redirects to the requested protected page when safe. Logout clears the session. Protected views require an authenticated user before rendering any protected content.

### Centralize class filtering on the server

Every material and knowledge-entry query is derived from the authenticated user’s `class_id`. A shared query helper returns only records whose class matches that user’s class. Direct material access combines the requested material identifier with the user’s class in the same query, so a mismatch yields `403` rather than leaking another class’s record.

The upload route first requires authentication, then requires the `teacher` role, and finally associates the new material and knowledge entry with the teacher’s class. A client-supplied class value is never trusted as an authorization boundary.

### Store material metadata and files separately

A material row stores the class, uploader, title, filename, content type, size, and creation time. The uploaded file is saved to a persistent uploads volume. The class list is rendered from the material table, so a successful upload is immediately queryable by members of the same class.

**Alternative considered:** Store file bytes directly in SQLite. That simplifies volume layout but increases database size and makes backup/restore less efficient.

### Parse uploads into knowledge entries in one transaction

Teacher uploads are restricted to `.txt` and `.md` files and to a configured maximum size. The upload flow is:

1. Validate the teacher role.
2. Validate the file extension.
3. Validate the file size.
4. Save the file to a non-public upload directory.
5. Read and parse the body.
6. Create the `materials` row and corresponding `knowledge_entries` row.
7. Commit both rows in one database transaction.
8. On any failure, roll back the transaction and delete the uploaded file.

This ensures that a failed upload leaves no partial database rows and no orphaned file.

**Alternative considered:** Store only the raw file and parse later. That would delay indexing and make failure cleanup harder to reason about, so it is not chosen.

### Serve detail and file content through authenticated APIs

Material detail and file content are exposed only through authenticated, class-scoped API endpoints. The file endpoint reads from the non-public upload directory and returns the file with the correct download name. `/uploads` is not mapped as a static route.

### Use a safe Markdown renderer

Uploaded Markdown is rendered server-side with a GitHub-Flavored Markdown-compatible renderer, then sanitized before being returned to the browser. The renderer supports common GFM features such as tables, fenced code, task lists, and autolinks, while the sanitizer removes scripts and untrusted HTML.

### Provide a classroom web experience

The web UI includes:

- A login page.
- A materials page with list/grid view.
- A class-scoped search box.
- A command palette.
- Upload progress.
- Toast notifications.
- 品牌红色中文界面ing.
- Light/dark mode.
- Safe Markdown rendering.

The UI is implemented with plain HTML, CSS, and JavaScript so it remains easy to inspect and does not require a build step.

### Seed two classes and representative users

Provide a deterministic local seed command that creates Class A and Class B, one teacher and one student in each, and one material per class. Password values come from environment variables and are hashed before insertion. The command is intended for local verification, not production provisioning.

### Run with Docker Compose and expose `/health`

Compose defines one application service, a SQLite volume, and an uploads volume. `GET /health` performs a lightweight `SELECT 1` database check and returns a successful response without authentication. The health endpoint does not reveal secrets or detailed diagnostics.

## Risks / Trade-offs

- [Risk] SQLite is not ideal for high write concurrency. → Mitigation: keep the course scope small and document PostgreSQL as a future upgrade.
- [Risk] A future view bypasses the shared class query helper. → Mitigation: centralize filtering and cover list, detail, and file-access paths in tests.
- [Risk] Local seed passwords could be accidentally committed. → Mitigation: read them from environment variables and document example variable names only.
- [Risk] Health checks fail during brief SQLite locks. → Mitigation: keep the health query lightweight and retry only at the orchestrator level.
- [Risk] Rich UI features increase client-side complexity. → Mitigation: keep the UI dependency-free and cover the core flows with integration tests.

## Migration Plan

1. Add the greenfield Flask application, models, seed command, and tests.
2. Add Compose configuration and persistent volumes.
3. Run migrations or schema initialization on startup.
4. Roll back by stopping Compose and removing the newly created volumes; there is no legacy data to preserve.
