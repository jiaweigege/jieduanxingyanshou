# Spec Delta

## Purpose

Defines how teachers and students authenticate, how protected pages are guarded, and how upload authority is assigned by account role.

## ADDED Requirements

### Requirement: Account login for teachers and students
The system SHALL allow teacher and student accounts to authenticate with an account identifier and password. A successful login MUST establish an authenticated session; a failed login MUST NOT establish one.

#### Scenario: Valid teacher login
- **WHEN** a teacher submits a valid account identifier and password
- **THEN** the system establishes an authenticated session for that teacher

#### Scenario: Valid student login
- **WHEN** a student submits a valid account identifier and password
- **THEN** the system establishes an authenticated session for that student

#### Scenario: Invalid credentials
- **WHEN** a user submits an invalid account identifier or password
- **THEN** the system does not establish an authenticated session and does not return protected content

### Requirement: Protected pages require authentication
The system MUST deny direct access to protected pages for unauthenticated visitors and MUST redirect them to the login page.

#### Scenario: Unauthenticated protected-page request
- **WHEN** an unauthenticated visitor requests a protected page
- **THEN** the system redirects the visitor to the login page and does not return protected content in that response

### Requirement: Only teachers may upload materials
The system MUST reject material-upload requests from authenticated students. Authorization MUST be enforced by the upload interface, not by hiding or disabling user-interface controls alone.

#### Scenario: Student upload is rejected
- **WHEN** an authenticated student calls the material-upload interface
- **THEN** the system rejects the request with an authorization failure and does not create a material

### Requirement: Passwords are stored as salted hashes
The system MUST store password verifiers as salted hashes. It MUST NOT store plaintext passwords or reversibly encrypted passwords.

#### Scenario: Password storage
- **WHEN** an account with a password is created or its password is changed
- **THEN** the stored password verifier is a salted hash rather than the plaintext password
