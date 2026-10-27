# Class Knowledge

A Flask application for authenticated, class-scoped teaching materials and
source-traceable knowledge retrieval.

## Features

- Teacher and student login with short-lived Authorization Bearer JWTs
- Class-scoped material storage
- Teacher-only uploads for `.txt` and `.md`
- Transactional writes to `materials` and `knowledge_entries`
- Authenticated material APIs
- SQLite FTS5 trigram retrieval limited to the signed-in user's class
- Relevant passages with stable chunk IDs, source line ranges, and protected links
- Single-turn, source-cited knowledge Q&A through Zhipu using each user's temporary API Key
- Optional AI application platform: three built-in apps, versioned prompt templates,
  named knowledge bases, uploaded declarative Skills, HTTP/MCP tools and redacted call traces
- Transactional indexing for uploads and an idempotent backfill command
- Safe GitHub-Flavored Markdown rendering
- Light/dark theme
- List/grid view
- Class search
- Command palette
- Upload progress and toast notifications
- Docker Compose startup
- Health endpoint

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export TOKEN_SIGNING_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
flask --app wsgi init-db
flask --app wsgi check-search
flask --app wsgi run
```

`init-db` creates the relational tables and persistent `knowledge_fts` virtual
table. It fails with a clear error when the active SQLite build lacks FTS5 or
the `trigram` tokenizer. The supported local runtime can be checked at any time:

```bash
flask --app wsgi check-search
```

Expected output includes `FTS5 trigram support available`.

## Seed local verification data

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export TOKEN_SIGNING_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export SEED_TEACHER_PASSWORD="your-local-teacher-password"
export SEED_STUDENT_PASSWORD="your-local-student-password"
flask --app wsgi seed
flask --app wsgi backfill-knowledge-index
```

The seed command creates:

- Class A and Class B
- `teacher_a`, `student_a`, `teacher_b`, and `student_b`
- One representative material and knowledge entry per class

`seed` indexes the seed entries immediately. For an existing database, run
`backfill-knowledge-index`; it processes entries in ID order, atomically replaces
one entry at a time, reports success and failure counts, and is safe to repeat.

Passwords are hashed before storage. Do not commit real passwords or secret keys.

## Docker Compose

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export TOKEN_SIGNING_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
docker compose up --build
```

The container runs `init-db` and the idempotent index backfill before starting
the server. The application listens on port `5000` by default. Use
`APP_PORT=5001` if port `5000` is occupied. Verify the container runtime with:

```bash
docker compose exec app flask --app wsgi check-search
```

## Health

```bash
curl http://localhost:5000/health
```

## Tests

```bash
pytest
openspec validate add-class-scoped-knowledge-retrieval --strict
openspec validate migrate-auth-to-bearer-tokens --strict
```

## Bearer authentication

`POST /api/auth/token` accepts JSON credentials and returns a short-lived access
Token. Protected APIs accept credentials only through
`Authorization: Bearer <access_token>`; Session Cookies, query parameters and
request bodies are not authentication sources.

```bash
curl -X POST http://localhost:5000/api/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"username":"student_a","password":"your-local-student-password"}'

curl http://localhost:5000/api/me \
  -H 'Authorization: Bearer <access_token>'

curl -X POST http://localhost:5000/api/auth/logout \
  -H 'Authorization: Bearer <access_token>'
```

The browser stores the access Token only in the current tab's `sessionStorage`.
It is never placed in a Cookie, URL, `localStorage`, HTML, or visible page data.
Because same-origin JavaScript can read `sessionStorage`, untrusted scripts and
unsafe HTML must never be introduced. The application continues to sanitize
Markdown and render retrieval passages as text. Tokens are not refreshed or
silently renewed; after expiry, sign in again.

## Local retrieval verification

After initialization and seeding, sign in as `student_a` or `teacher_a`, open
`/materials`, and use the separate “检索本班知识正文” control. The material list
filter remains independent. A direct API check can be made with a Bearer Token
returned by `/api/auth/token`:

```bash
curl --get \
  -H 'Authorization: Bearer <access_token>' \
  --data-urlencode 'q=数据建模' \
  http://localhost:5000/api/knowledge/search
```

An empty query returns `400` with `invalid_query`; a healthy query with no
matches returns `200` and an empty `results` array; an unavailable index returns
`503` with `retrieval_unavailable` and no partial results.

## Knowledge Q&A with a personal Zhipu API Key

After signing in, open `/materials`, select “知识问答”, enter your own
Zhipu API Key in the password field, and ask one question. The server retrieves
at most four passages from the signed-in user's class, sends the question,
passages, and the current request's Key to Zhipu, and returns a plain-text answer
with numbered sources. A no-match result is produced locally and does not call
Zhipu.

The Key is never configured as a server-wide credential and is not written to
the database, logs, HTML, cookies, URLs, `localStorage`, or `sessionStorage`. It
exists only in the current page's password field and the current request; logout
clears it, and refreshing or closing the page discards it. Each user must enter
their own Key again. The question and answer are also single-page, single-turn
state and are not restored or replayed.

This is a third-party data flow: the Key, question, and retrieved class passages
pass through this application to Zhipu. Production deployments must use HTTPS
so these values are encrypted in transit between the browser and this service;
the configured provider URL is also required to use HTTPS. Do not enter a Key on
an untrusted deployment.

Only non-secret provider behavior is configurable:

- `ZHIPU_API_URL` (default: official Chat Completions HTTPS endpoint)
- `ZHIPU_MODEL` (default: `glm-4-flash`)
- `ZHIPU_TIMEOUT_SECONDS` (default: `20`)
- `KNOWLEDGE_QA_MAX_QUESTION_CHARS` (default: `500`)
- `KNOWLEDGE_QA_MAX_CONTEXT_CHARS` (default: `6000`)
- `KNOWLEDGE_QA_MAX_OUTPUT_TOKENS` (default: `512`)

For a direct API check, substitute placeholders locally; never commit or paste a
real Key into source files or shell history:

```bash
curl -X POST http://localhost:5000/api/knowledge/answer \
  -H 'Authorization: Bearer <access_token>' \
  -H 'Content-Type: application/json' \
  -d '{"question":"磁铁能吸木块吗？","api_key":"<your-personal-zhipu-key>"}'
```

The automated test suite uses injected transports and sentinel values only; it
never calls Zhipu. A real provider check should be performed only by a user who
explicitly chooses to enter a temporary test Key in the page.

## Retrieval design and invariants

SQLite FTS5 was chosen instead of a vector database because this iteration needs
deterministic offline text retrieval, exact source tracing, and a single local
persistence boundary. A vector service would add model downloads, versioning,
and cross-system synchronization without being required for the course scope.

A future vector index may replace or complement ranking, but it must preserve:

- stable chunks linked to the source knowledge entry, material, and line range;
- server-side class filtering derived only from the authenticated user;
- the current result fields and independently protected detail/file links;
- atomic upload indexing and explicit unavailable-index behavior.

## Troubleshooting

- `SQLite FTS5 with the trigram tokenizer is required`: run `flask --app wsgi
  check-search` with the same Python runtime. Use a Python/SQLite build that
  includes FTS5 and trigram support; do not silently fall back to an unscoped SQL
  scan.
- `retrieval_unavailable`: run `flask --app wsgi init-db`, then
  `flask --app wsgi backfill-knowledge-index`. Review the reported entry IDs if
  the command exits unsuccessfully.
- `invalid_api_key`: enter a non-empty personal Key in the password field.
- `provider_auth_failed`: Zhipu rejected the current user's Key; verify or
  replace it and submit again.
- `ai_unavailable`: Zhipu timed out, rate-limited the request, returned an
  invalid answer, or was otherwise unavailable. No partial answer is shown.
- Upload fails while indexing: the upload file and all database rows from that
  attempt are removed. Fix the index/runtime issue and upload again.
- `missing_token`: add exactly one `Authorization: Bearer <access_token>` Header.
- `invalid_token`: the Token is malformed, expired, revoked, has invalid claims,
  or no longer maps to an active local authorization record. Sign in again.
- `TOKEN_SIGNING_KEY` startup error: generate a new random key of at least 32
  characters. Do not use the placeholder from `.env.example` in a running app.

## Public repository submission checklist

- Initialize and seed using local placeholder passwords from `.env.example`;
  never commit `.env`, real credentials, SQLite files, or uploaded materials.
- Run `pytest` and the strict OpenSpec validation command shown above.
- Demonstrate with locally created teacher/student accounts and a query such as
  `数据建模`; do not publish real course content.
- State the implemented scope as authenticated class-scoped retrieval with
  source tracing. This repository does not claim that a remote publication or
  deployment has already occurred.

## Notes

- Material access is filtered by the signed-in user's class on the server.
- Only teachers may upload materials.
- Uploaded files are stored in a persistent volume, while metadata and knowledge entries are stored in SQLite.
- `/uploads` is not statically exposed; files are served through authenticated APIs.
- `/materials` is a public HTML shell with no user or material data; its script
  loads identity and content only after a successful Bearer-authenticated API call.
- The original knowledge Q&A remains single-turn. Solver and platform conversations
  save successful messages for viewing; they do not replay previous turns to the model.
  Personal model credentials are request-only. Assignment submission, grading and
  feedback workflows are outside the application scope.

## AI application platform

The optional `/apps` workspace provides general chat, knowledge Q&A and guided
problem solving. Teachers manage versioned templates, knowledge collections,
declarative Skill packages and approved tools; both teachers and students own
their individual application conversations and call traces.

After installing `requirements.txt` in the project virtual environment and setting
the existing secret/signing keys, enable and initialize the platform:

```bash
export AI_PLATFORM_ENABLED=true
flask --app wsgi init-platform
flask --app wsgi run
```

The platform is disabled by default. `init-platform` only adds tables and
idempotent built-ins, preserving existing accounts, materials, SolverSkills and
solver sessions. It creates one default knowledge base per class; new successful
uploads join that default base automatically while the feature is enabled.
Run initialization again after creating new classes or importing existing data.

Tool-enabled apps require an explicit model capability declaration. For example,
replace the example model with one your provider actually supports:

```bash
export AI_MODEL_CAPABILITIES='{"your-tool-capable-model":{"tools":true}}'
```

Use the teacher configuration form to select this model, a template version,
knowledge bases, Skill versions and tools, then save the draft and publish.
The server rejects unsupported model capabilities and unavailable bindings.
The old non-streaming knowledge API and streaming solver API retain their formats.

Skill uploads accept a UTF-8 `SKILL.md`, or a ZIP with root `SKILL.md` and text
files under `references/`. Front matter requires `name` and `description`, with
optional `allowed-tools` as a YAML list. Packages are instructions and reference
text; tool execution uses registered adapters. Scripts and executables are rejected.

For external HTTP tools and MCP, configure exact allowed hostnames and optional
credential references at deployment time. Example values below are placeholders:

```bash
export AI_TOOL_ALLOWED_HOSTS='["tools.your-domain.example"]'
export AI_CREDENTIAL_REFERENCES='{"class-mcp":{"env":"CLASS_MCP_TOKEN","class_ids":[1]}}'
```

Set the referenced environment variable securely on the server. The teacher
chooses the reference name, never pastes its value into application configuration.
Connections support HTTPS on port 443, public approved addresses and MCP protocol
2025-11-25 through the official SDK. Connect/discover tools, then bind specific
definitions to an application. Changed schemas invalidate old bindings.

Each completed or failed message has a run. “本次调用” shows the actual serialized
model request, redacted headers, bounded original response, parsed response and
context/tool events. It also explains local zero-call results. Trace detail,
export and deletion are restricted to the conversation owner; teacher management
permissions do not grant access to student conversations. Default retention is
seven days; expired evidence is hidden even before cleanup runs.

```bash
flask --app wsgi cleanup-platform-traces
flask --app wsgi recover-platform-runs
```

The second command marks runs older than the configured run timeout as interrupted
and releases their conversation locks. It does not replay external calls.

For an entirely offline UI demonstration with disposable temporary data:

```bash
.venv/bin/python scripts/platform_demo.py
```

Open `http://127.0.0.1:5057/apps`. The script prints demo-only teacher/student
credentials, accepts any placeholder model key, and generates simulated responses
without contacting a provider. Stop the process to remove its temporary database.

See [the five-question verification guide](docs/ai-platform-verification.md) for
request/response examples, exact checks, limits, tests and deployment rollback.
