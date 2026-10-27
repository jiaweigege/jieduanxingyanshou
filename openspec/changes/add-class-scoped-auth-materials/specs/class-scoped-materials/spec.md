# Spec Delta

## Purpose

Defines class-isolated storage and retrieval of teaching materials in the knowledge base, including upload and listing behavior.

## ADDED Requirements

### Requirement: Teachers can upload materials to their class knowledge base
An authenticated teacher MUST be able to upload a teaching material into the knowledge base for the teacher's class. A successful upload MUST persist a material record that is associated with that class.

#### Scenario: Successful teacher upload
- **WHEN** an authenticated teacher uploads a material for the teacher's class
- **THEN** the system stores the material in the knowledge base with that class association

### Requirement: Class material lists contain persisted uploads
The system MUST return a material list scoped to the requesting user's class. A material successfully uploaded by a teacher in that class MUST appear in that class's material list.

#### Scenario: Uploaded material appears in class list
- **WHEN** a teacher uploads a material and a member of that class requests the class material list
- **THEN** the list includes the uploaded material

### Requirement: Material access is isolated by class
The system MUST treat a class as the data boundary for knowledge-base materials. A user MUST NOT be able to list or directly access another class's materials through normal application interfaces. Filtering and authorization MUST be enforced on the server.

#### Scenario: Class A user requests the material list
- **WHEN** a user associated with Class A requests the material list
- **THEN** the system returns only Class A materials and omits Class B materials

#### Scenario: Class A user directly accesses a Class B material
- **WHEN** a user associated with Class A requests a material that belongs to Class B
- **THEN** the system rejects the request and does not return the Class B material

#### Scenario: Client requests another class
- **WHEN** a user associated with Class A supplies Class B as the requested class or material scope
- **THEN** the system enforces Class A as the authorized boundary and does not return Class B materials
