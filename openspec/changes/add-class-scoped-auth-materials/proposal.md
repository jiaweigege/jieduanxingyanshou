# Proposal

## Why

The project needs a secure baseline for classroom use: authenticated teachers and students, role-based material contribution, and reliable class-level data isolation. Without these controls, protected pages and knowledge-base materials cannot be exposed safely.

## What Changes

- Add account/password login for both teacher and student users.
- Require authentication for protected pages and redirect unauthenticated visitors to the login page.
- Add role-based authorization so only teachers may upload teaching materials.
- Make the class a server-enforced data boundary for material access and listing.
- Store teacher uploads in the knowledge base so they are visible in the same class's material list.
- Store passwords only as salted hashes and keep secrets in server-side environment variables.
- Provide Docker Compose startup and a `GET /health` endpoint for the application.

## Capabilities

### New Capabilities

- `account-access`: Account authentication, protected-page access, and role-based upload authorization.
- `class-scoped-materials`: Class-isolated teaching-material storage, upload, and listing through the knowledge base.
- `service-runtime`: Secure application configuration, Docker Compose startup, and health reporting.

### Modified Capabilities

- None. The project has no existing OpenSpec capabilities.

## Impact

- Adds user, role, class, and knowledge-base material behavior to the application.
- Adds login/session handling, authorization middleware, and server-side class filtering.
- Adds persistence for accounts and materials.
- Adds health checking and Docker Compose deployment configuration.
- Requires secrets to be supplied through server-side environment variables; no plaintext passwords or client-exposed keys are acceptable.

No existing application code or specifications were found in the repository, so this change defines the initial behavioral contract for a greenfield implementation.
