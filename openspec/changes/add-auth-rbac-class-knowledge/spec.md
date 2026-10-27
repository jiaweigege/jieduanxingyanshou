# Spec Delta

## Purpose

Defines the minimum secure behavior for classroom authentication, role-based material contribution, class-isolated knowledge-base access, preset verification data, and local runtime health.

## ADDED Requirements

### Requirement: Teachers and students can log in
The system SHALL allow teacher and student accounts to authenticate with a username and password. A successful login MUST establish an authenticated session; a failed login MUST NOT establish one.

#### Scenario: Valid teacher login
- **WHEN** a teacher submits a valid username and password
- **THEN** the system establishes an authenticated session for that teacher

#### Scenario: Valid student login
- **WHEN** a student submits a valid username and password
- **THEN** the system establishes an authenticated session for that student

#### Scenario: Invalid credentials
- **WHEN** a user submits an unknown username or wrong password
- **THEN** the system does not establish a session and does not return protected content

### Requirement: Protected pages require authentication
The system MUST redirect unauthenticated requests for protected pages to the login page and MUST NOT return protected content in that response.

#### Scenario: Unauthenticated protected-page request
- **WHEN** an unauthenticated visitor requests a protected page
- **THEN** the system redirects the visitor to the login page and returns no protected content

### Requirement: Only teachers may upload materials
The material-upload interface MUST reject authenticated student requests with HTTP `403`. Authorization MUST be enforced on the server, not only by hiding or disabling a button in the browser.

#### Scenario: Student upload is forbidden
- **WHEN** an authenticated student calls the material-upload interface
- **THEN** the system returns HTTP `403` and does not create a material record

### Requirement: Materials are isolated by class
A class MUST be the data boundary for knowledge-base materials. The server MUST filter list queries by the authenticated user’s class and MUST reject direct cross-class access.

#### Scenario: Class A material list
- **WHEN** a Class A user requests the material list
- **THEN** the system returns only Class A materials and omits Class B materials

#### Scenario: Cross-class direct access is rejected
- **WHEN** a Class A user requests a material that belongs to Class B
- **THEN** the system returns HTTP `403` and does not return the Class B material

#### Scenario: Client-supplied class cannot override the boundary
- **WHEN** a Class A user submits Class B as the requested class or material scope
- **THEN** the system enforces Class A as the authorized boundary and does not return Class B materials

### Requirement: Teacher uploads persist to the class knowledge base
An authenticated teacher MUST be able to upload a teaching material into the knowledge base for the teacher’s own class. A successful upload MUST persist a material record associated with that class and uploader.

#### Scenario: Successful teacher upload
- **WHEN** an authenticated teacher uploads a material
- **THEN** the system persists the material with the teacher’s class and account identity

#### Scenario: Uploaded material appears in the class list
- **WHEN** a teacher uploads a material and a member of that class requests the class material list
- **THEN** the list includes the newly uploaded material

### Requirement: Preset data supports local verification
The system SHALL provide a deterministic local seed command that creates at least two classes, one teacher account and one student account per class, and representative materials for isolation testing. Seed passwords MUST be supplied outside committed source and stored as salted hashes.

#### Scenario: Seed data is available
- **WHEN** the operator runs the local seed command with password values supplied through the environment
- **THEN** the system creates the preset classes, accounts, and representative materials without storing plaintext passwords

### Requirement: Passwords use salted hashes
The system MUST store password verifiers as salted hashes. It MUST NOT store plaintext or reversibly encrypted passwords.

#### Scenario: Password storage
- **WHEN** an account is created or its password is changed
- **THEN** the stored password verifier is a salted hash rather than the plaintext password

### Requirement: Runtime exposes a health endpoint
The application MUST provide `GET /health`. When the application and its datastore are available, the endpoint MUST return a successful response without requiring authentication.

#### Scenario: Health check succeeds
- **WHEN** a client sends `GET /health` to a running application
- **THEN** the application returns a successful health response

### Requirement: Application starts with Docker Compose
The application MUST be startable with Docker Compose, including persistent storage for the database and uploaded files.

#### Scenario: Compose startup
- **WHEN** the operator starts the application with Docker Compose
- **THEN** the application starts with its required storage and becomes available for requests

### Requirement: Runtime secrets stay server-side
Runtime secrets MUST be supplied through server-side environment variables. The system MUST NOT expose secret values to browsers or hardcode them in committed source.

#### Scenario: Secret configuration
- **WHEN** the application is configured with its session-signing secret or seed passwords
- **THEN** the values are read from server-side environment variables and are not exposed to the browser
