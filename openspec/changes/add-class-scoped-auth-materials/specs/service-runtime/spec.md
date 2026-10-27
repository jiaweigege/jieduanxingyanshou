# Spec Delta

## Purpose

Defines secure runtime configuration, repeatable Docker Compose startup, and an application health endpoint.

## ADDED Requirements

### Requirement: Application exposes a health endpoint
The application MUST provide `GET /health` and return a successful health response when its runtime is available.

#### Scenario: Health check
- **WHEN** a client sends `GET /health` to a running application
- **THEN** the application returns a successful health response

### Requirement: Application starts with Docker Compose
The application MUST be startable with Docker Compose, including the services required for its normal operation.

#### Scenario: Compose startup
- **WHEN** the operator starts the application with Docker Compose
- **THEN** the application and its required services start and the application becomes available

### Requirement: Secrets remain server-side
Runtime secrets MUST be supplied through server-side environment variables. The system MUST NOT expose secret values to browsers or require them to be hardcoded in application source or committed configuration.

#### Scenario: Secret configuration
- **WHEN** the application is configured with a secret such as a session-signing key or datastore credential
- **THEN** the secret is read from a server-side environment variable and is not exposed to the browser
