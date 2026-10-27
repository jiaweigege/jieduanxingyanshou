# Tasks

## 1. Application Scaffold

- [x] 1.1 Create the Flask application, configuration module, and dependency manifest; verify `flask --app <app> routes` lists the expected routes
- [x] 1.2 Add SQLite connection settings and environment-based `SECRET_KEY` handling; verify startup fails clearly when `SECRET_KEY` is missing
- [x] 1.3 Add the test configuration and an initial smoke test; verify `pytest` runs successfully before feature tests are added

## 2. Data Model and Seed Data

- [x] 2.1 Create the class, user, and material models with required role and class fields; verify model tests reject invalid roles and missing class associations
- [x] 2.2 Add schema initialization for SQLite; verify a clean database can be initialized without errors
- [x] 2.3 Implement the deterministic seed command for Class A, Class B, teacher/student accounts, and representative materials; verify the seed command creates the expected records
- [x] 2.4 Ensure seed passwords are read from environment variables and hashed before storage; verify no plaintext password appears in the database or repository

## 3. Authentication and Password Security

- [x] 3.1 Implement login and logout with signed, `HttpOnly`, `SameSite=Lax` sessions; verify valid teacher, valid student, invalid credential, and logout tests pass
- [x] 3.2 Hash and verify passwords with Werkzeug’s salted password helpers; verify a stored password differs from its plaintext input and still authenticates correctly
- [x] 3.3 Protect pages with an authentication guard that redirects to the login page; verify an unauthenticated request receives the redirect and no protected content

## 4. Role-Based Upload and Class Isolation

- [x] 4.1 Add a teacher-only upload route that returns HTTP `403` for authenticated students; verify the student upload test receives `403` and creates no material
- [x] 4.2 Persist uploaded material metadata and save the file payload to the uploads volume; verify a successful teacher upload creates one class-associated record
- [x] 4.3 Implement class-scoped list queries using the authenticated user’s class; verify a Class A user sees only Class A materials
- [x] 4.4 Implement direct material access with the user’s class included in the query; verify a Class A user receives HTTP `403` for a Class B material
- [x] 4.5 Ignore or reject client-supplied class overrides; verify a Class A user cannot retrieve Class B materials by submitting Class B
- [x] 4.6 Verify an uploaded material is immediately visible in the same class’s material list; add an integration test that uploads and then queries the list

## 5. Runtime and Health

- [x] 5.1 Add `GET /health` with a lightweight database check; verify an unauthenticated request receives a successful response
- [x] 5.2 Add Docker Compose services and persistent volumes for SQLite and uploads; verify `docker compose config` is valid
- [x] 5.3 Add application startup initialization and health-aware Compose configuration; verify the composed application starts and reports healthy

## 6. Final Verification

- [x] 6.1 Run the complete automated test suite; verify all authentication, authorization, isolation, upload, seed, and health tests pass
- [x] 6.2 Start the stack with `docker compose up`, verify `GET /health`, and manually exercise login, student upload rejection, and cross-class rejection
- [x] 6.3 Check the repository for committed secrets and plaintext passwords; verify no real secret or plaintext password is committed
- [x] 6.4 Run `openspec validate --strict`; verify the change reports no validation errors

## 7. Knowledge-Entry Model and Transactional Upload

- [x] 7.1 Create the `knowledge_entries` model with a material foreign key and class association; verify model tests enforce the relationship
- [x] 7.2 Restrict teacher uploads to `.txt` and `.md`; verify unsupported extensions are rejected with no records created
- [x] 7.3 Enforce a configurable upload size limit; verify oversized files are rejected with no records created
- [x] 7.4 Parse the uploaded body and create one knowledge entry per material; verify the body is stored with the material and class
- [x] 7.5 Write `materials` and `knowledge_entries` in one database transaction; verify both records are created together or not at all
- [x] 7.6 Clean up the uploaded file and roll back the transaction on parse or persistence failure; verify no rows or files remain

## 8. Authenticated Material APIs

- [x] 8.1 Implement `/api/me`; verify it returns the current user’s identity, role, and class when authenticated
- [x] 8.2 Return HTTP `401` for unauthenticated API requests; verify API clients receive JSON errors rather than page redirects
- [x] 8.3 Implement class-scoped material list, detail, and file APIs; verify a Class A user cannot access Class B materials
- [x] 8.4 Ensure `/uploads` is not statically exposed; verify direct static upload paths are unavailable

## 9. Web Experience

- [x] 9.1 Implement the login page and materials page with 品牌红色中文界面ing; verify the pages render correctly
- [x] 9.2 Add light/dark mode; verify the theme persists across reloads
- [x] 9.3 Add list/grid view switching; verify the selected view persists across reloads
- [x] 9.4 Add class-scoped search; verify search results are limited to the current class
- [x] 9.5 Add a command palette; verify it can search materials and trigger common actions
- [x] 9.6 Add upload progress and toast notifications; verify successful and failed uploads provide clear feedback
- [x] 9.7 Render Markdown safely with GFM support; verify tables, fenced code, task lists, and autolinks render correctly and untrusted scripts are sanitized

## 10. Final Verification for Extended Scope

- [x] 10.1 Extend the automated test suite for knowledge entries, API behavior, and UI rendering; verify all tests pass
- [x] 10.2 Run `openspec validate --strict`; verify the updated change reports no validation errors
