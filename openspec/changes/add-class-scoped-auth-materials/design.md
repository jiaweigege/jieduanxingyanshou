# Design

## Context

The repository currently has no application code or existing OpenSpec capabilities. This is therefore a greenfield implementation. The required behavior is defined in `proposal.md` and the three delta specs under `specs/`.

## Goals / Non-Goals

**Goals:**

- Provide a complete server-rendered web application with authentication, roles, class isolation, and material uploads.
- Keep authorization and class scoping in server-side request handling and data queries.
- Make the service easy to start locally with Docker Compose and easy to verify with `GET /health`.
- Establish automated tests for the security boundaries before implementation is considered complete.

**Non-Goals:**

- Multi-tenant school-wide administration, class membership management, or user invitation workflows.
- Full-text search, versioning, or advanced knowledge-base features beyond storing and listing materials.
- TLS termination inside the application container; production deployment may place Compose behind a reverse proxy.
- Supporting users who belong to multiple classes.

## Decisions

### Use a server-rendered Django application with PostgreSQL

Django provides battle-tested password hashing, session authentication, middleware, ORM queries, migrations, and form handling. A server-rendered application also avoids exposing authorization decisions to browser code and keeps the first implementation compact.

**Alternative considered:** A separate SPA plus API service. This would add a second runtime and make it easier to accidentally treat frontend UI state as an authorization boundary, so it is not chosen for the initial implementation.

### Model roles and one class per account

The account model will extend Django's user model with an enum-like role (`teacher` or `student`) and a required foreign key to a class. Accounts will not be allowed to omit a class. This gives every authenticated request a single authoritative class boundary.

**Alternative considered:** Role and class membership in separate join tables. That is more flexible but unnecessary when the required behavior has one class per user.

### Use server-side sessions and Django's password hashers

Login will use Django sessions with an `HttpOnly` cookie. Passwords will be stored using Django's configured salted password hashers, never plaintext. Protected page views will require an authenticated session and redirect unauthenticated requests to the login page.

**Alternative considered:** Stateless signed tokens. Tokens are useful for third-party API clients but add revocation complexity that is unnecessary for this server-rendered application.

### Centralize authorization and class scoping

The upload interface will first require authentication, then require the `teacher` role, and then use the authenticated teacher's class association. It will not accept a client-supplied class identifier as authorization input. Material list queries will always filter by the authenticated user's class. Direct material access will combine the requested identifier with the user's class in the same server-side query.

A small shared query/helper layer should be used for class-scoped access so page handlers do not each reimplement filtering. Tests will call the interfaces directly, without relying on hidden or disabled browser controls.

### Represent the knowledge base with a material table and persistent file storage

A material record will store metadata, the owning class, and the uploading teacher. Uploaded files will be kept on a persistent Docker volume while PostgreSQL stores the queryable record. The class material list will be served from the material table.

**Alternative considered:** Store file bytes in PostgreSQL. That simplifies volume management but increases database size and backup cost, so it is not chosen for the initial implementation.

### Configure runtime through server-side environment variables

Django's secret key, PostgreSQL credentials, and other deployment-specific settings will be read from environment variables supplied by the deployment environment. Compose will reference an environment file or host environment without committing real secret values. A non-secret `.env.example` may document required variable names.

### Provide an unauthenticated health endpoint

`GET /health` will return a successful response when the application can serve requests. It should also perform a lightweight database check so Compose and operators do not consider the stack healthy before PostgreSQL is usable. The endpoint will not reveal secrets or detailed internal diagnostics.

### Run the application with Docker Compose

Compose will define the application and PostgreSQL services, persistent volumes, and healthchecks. The application service will wait for a healthy database before accepting traffic.

## Risks / Trade-offs

- [Risk] A future handler bypasses the shared class-scoped helper. → Mitigation: keep class filtering centralized, review new query paths, and include direct cross-class access tests.
- [Risk] Uploaded files on a local volume are not captured by PostgreSQL backups. → Mitigation: document that the material volume must be backed up with the database; a future change can move files to object storage.
- [Risk] Health checks that depend on PostgreSQL report failure during temporary database restarts. → Mitigation: keep the check lightweight and treat a reachable datastore as part of service readiness.
- [Risk] Weak deployment secrets undermine session security. → Mitigation: fail startup when required secrets are missing and generate strong values in deployment instructions.
- [Risk] One-class-per-user prevents future multi-class teachers. → Mitigation: isolate this assumption in the account model and revisit it in a separate spec change if needed.

## Migration Plan

1. Add the greenfield application, database models, migrations, authentication views, material interfaces, tests, and Compose configuration.
2. Apply migrations during container startup or deployment.
3. Seed the initial classes and accounts through an explicit, non-secret provisioning mechanism; no default production password should be committed.
4. Rollback is removal of the new application services and volumes. Since there is no existing application to preserve, no data migration is required.
