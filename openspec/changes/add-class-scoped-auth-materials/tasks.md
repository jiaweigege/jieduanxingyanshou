# Tasks

## 1. Application Foundation

- [ ] 1.1 Create the Django project, application module, dependency manifests, and baseline settings; verify the application passes `python manage.py check`
- [ ] 1.2 Configure PostgreSQL-backed persistence and environment-based settings for the secret key and database credentials; verify startup fails cleanly when required server-side variables are missing
- [ ] 1.3 Add the project's automated-test configuration and an initial smoke test; verify the test command runs successfully before feature tests are added

## 2. Accounts, Roles, and Classes

- [ ] 2.1 Implement the class and account models with required teacher/student roles and one required class per account; verify model tests enforce valid roles and reject missing class or role values
- [ ] 2.2 Generate and apply database migrations for the new models; verify migrations run on a clean database without errors
- [ ] 2.3 Verify account creation and password changes use Django's salted password hashers; add a test asserting the stored value is not the plaintext password
- [ ] 2.4 Add an explicit, non-secret development seed mechanism for classes, teachers, and students; verify seeded accounts can be inspected without exposing plaintext passwords

## 3. Authentication and Protected Pages

- [ ] 3.1 Implement login and logout views with server-side sessions and an `HttpOnly` session cookie; verify tests for valid teacher login, valid student login, invalid credentials, and logout all pass
- [ ] 3.2 Require authentication for protected pages and redirect unauthenticated requests to the login page; verify a protected-page test receives the redirect and no protected content
- [ ] 3.3 Add the login and protected-page templates with CSRF protection and error feedback; verify successful and unsuccessful browser flows manually or with template tests

## 4. Class-Scoped Knowledge Base Materials

- [ ] 4.1 Implement the material model with class ownership, uploader, metadata, and persistent file storage; verify model and migration tests pass on a clean database
- [ ] 4.2 Implement teacher-only material upload using the authenticated teacher's class rather than a client-supplied class; verify a teacher upload succeeds and creates one class-associated record
- [ ] 4.3 Reject authenticated student upload requests at the upload interface; verify the test receives an authorization failure and no material is created
- [ ] 4.4 Implement class-scoped material listing and direct material access through shared server-side query helpers; verify Class A users cannot list or directly access Class B materials even when Class B is supplied by the client
- [ ] 4.5 Add the material list, detail, and upload interfaces with CSRF protection and teacher-only upload affordances; verify a teacher can upload and a student cannot upload through the interface

## 5. Runtime, Health, and Deployment

- [ ] 5.1 Add `GET /health` with a lightweight database readiness check; verify an unauthenticated request receives a successful health response and does not reveal secret values
- [ ] 5.2 Add Docker Compose services, persistent volumes, healthchecks, and environment-variable documentation without committing real secrets; verify `docker compose config` is valid
- [ ] 5.3 Configure migration application and readiness behavior for container startup; verify the composed application starts only after PostgreSQL is ready

## 6. Verification and Documentation

- [ ] 6.1 Add end-to-end or integration tests covering login, role rejection, upload, same-class listing, and cross-class denial; verify the full automated test suite passes
- [ ] 6.2 Start the complete stack with `docker compose up`, verify `GET /health` succeeds, and verify the required teacher/student/class isolation scenarios through the running application
- [ ] 6.3 Document local startup, required environment variables, account provisioning, backups for the database and upload volume, and rollback; verify the documented commands match the repository
- [ ] 6.4 Run static/security checks for committed secrets and plaintext passwords; verify no secret value or plaintext password is committed
