# Pantry — Recipe Agent

A Next.js website and Python FastAPI backend built around LangGraph and Groq.
The original CLI is also available and shares the web workflow.

## Start locally (Windows PowerShell)

Requires Python 3.13+ and Node.js 22.18+ (for the frontend test runner).

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Set `GROQ_API_KEY` in the root `.env`. The existing `.env` is preserved.
`GROQ_MODEL` defaults to `openai/gpt-oss-120b`. The analysis model must support
Groq structured outputs; recipe generation uses ordinary text streaming.
Your API key stays on the backend. Never put it in a `NEXT_PUBLIC_` variable.

In the first terminal, from the root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

In a second terminal:

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

Open http://127.0.0.1:3000. API docs: http://127.0.0.1:8000/docs.
If the backend uses a different address, copy `frontend/.env.example` to
`frontend/.env.local`, set `NEXT_PUBLIC_API_URL`, and restart Next.js.
The browser uses same-origin `/api` requests by default. Next.js proxies these
to port 8000 during development; `API_PROXY_URL` overrides that local target.
On Vercel, the service router sends these requests directly to FastAPI.
Set `FRONTEND_ORIGINS` only when using a frontend on a separate origin.

## Deploy on Vercel

Import [burhansandhu/pantry](https://github.com/burhansandhu/pantry) into Vercel
with **Root Directory `.`**. Keep build/install/framework settings automatic:
the root `vercel.json` defines the Next.js and FastAPI services and their routes.
Both services deploy together under one domain. Do not select `frontend` as
the project root: that would omit the Python backend.

In the Vercel project's **Storage** tab, connect a dedicated PostgreSQL database
through the Neon integration. Its `DATABASE_URL` is used by FastAPI, and
`DATABASE_URL_UNPOOLED` is used for schema initialization. Use a
separate database or database branch for preview deployments when available.
Pantry creates its session and LangGraph checkpoint tables automatically.

Set these server-side environment variables in Production and Preview:

| Variable | Value |
| --- | --- |
| `GROQ_API_KEY` | Your Groq API key |
| `DATABASE_URL` | PostgreSQL connection string from the integration |
| `DATABASE_URL_UNPOOLED` | Direct connection string (required with a transaction pooler) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` (optional; this is the default) |
| `RECIPE_STARTS_PER_HOUR` | `30` (optional; per client IP) |

Leave `NEXT_PUBLIC_API_URL` unset. API keys and database credentials must never
use `NEXT_PUBLIC_` names. Redeploy after configuring environment variables.
Verify `/health` and create a recipe, approve it, then refresh the completed recipe.

**Continuous integration:** `.github/workflows/ci.yml` runs Python lint/tests,
real PostgreSQL session tests, frontend tests/type checks, and a production build
on pushes and pull requests. Model calls are mocked; GitHub needs no Groq secret.

**Continuous deployment:** Vercel's GitHub integration deploys pushes to `main`
to production and other branches/PRs to previews. No Vercel token is needed in
GitHub Actions for this native integration. CI and Vercel builds run separately;
if you want CI to gate promotion, configure Vercel Deployment Checks for the two
CI jobs. Updating code means committing and pushing to `main`:

```powershell
git add .
git commit -m "Describe the change"
git push
```

References: [Vercel Services](https://vercel.com/docs/services),
[FastAPI deployment](https://vercel.com/docs/frameworks/backend/fastapi),
[PostgreSQL integrations](https://vercel.com/docs/postgres), and
[GitHub deployments](https://vercel.com/docs/git/vercel-for-github).

## Workflow

1. Enter ingredients, optional preferences, and optional known allergies.
   In **Find substitutes**, select any ingredient you want to replace. The model
   chooses alternatives; no substitution instructions need to go in the ingredient
   text. Leave this section unselected to use automatic suggestions. You can also
   use **Edit ingredients** during review to request a swap before generation.
2. The LLM assesses culinary compatibility, allergy/diet conflicts and useful
   substitutions using a validated JSON schema. There are no ingredient maps or
   hardcoded unusual pairings in application code.
3. An unusual pairing pauses for approval or ingredient edits. Unsafe/non-food
   ingredients require edits.
4. Review every proposed replacement. Each accepted replacement requires a
   separate confirmation of no known allergy and ingredient-label checks. A
   required replacement cannot be skipped; edit the input to seek another option.
   Optional replacements can be declined.
5. Replacements are applied and the whole ingredient list is assessed again.
   New unusual combinations or required replacements pause again.
6. A final summary always pauses for explicit approval. Only then does the chef
   generate the recipe. Provider chunks reach the browser through SSE immediately,
   and Markdown renders incrementally. The completed recipe can be copied or downloaded.

The model generates substitution suggestions from its knowledge; this version
does not perform external web/product searches or verify product labels.
Allergy suitability depends on the actual product and cross-contact information.
The model is instructed to use approved ingredients, with optional water, salt
and pepper where appropriate, and never to claim guaranteed allergy safety.

## API

- `GET /health`: service status and whether a key is configured (no secret returned).
- `POST /api/sessions`: `{ingredients: string[], preferences?: string, allergies?: string[], substitution_requests?: string[]}`.
  Every requested substitution must match a submitted ingredient entry.
- `GET /api/sessions/{id}`: retrieve a paused review or completed recipe after refresh.
- `POST /api/sessions/{id}/respond`: `{review_id, action, revision?, decisions?}`.
  Actions are `keep`, `edit`, `substitutions`, and `generate`.
  `revision` uses the start request shape. Each decision is
  `{ingredient, accept, allergy_confirmed}`.

Both POST endpoints return `text/event-stream` with JSON `data:` frames:
`session`, `status`, `review`, `token`, `done`, or `error`. These use streaming
`fetch`, since browser `EventSource` does not support POST bodies. The response
validator prevents skipping steps, replaying old reviews, omitting decisions,
and accepting substitutes without allergy confirmation. Concurrent requests
on the same session return 409. Stream failures expose a readable error, with
diagnostic details confined to server logs.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pip install pytest ruff httpx
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check recipe_agent backend tests
cd frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

Tests mock the provider, so they run without paid model calls. They exercise
approval gates, replacement/allergy checks, ingredient edits, session isolation,
stale responses, errors, chunk forwarding and fragmented UTF-8 SSE parsing.
For the CLI: `.\.venv\Scripts\python.exe -m recipe_agent.main` from the root.

For a manual live integration check with synthetic ingredients (requires the
backend to be running and makes real Groq calls):
`.\.venv\Scripts\python.exe scripts/smoke_live.py`.

Provider references: [Groq structured outputs](https://console.groq.com/docs/structured-outputs)
and [LangGraph streaming](https://docs.langchain.com/oss/python/langgraph/streaming).
Ingredient assessment uses strict structured output with original names limited
to the submitted ingredient entries, including quantities. It retries once for
malformed responses or inconsistent substitutions (unknown originals,
duplicate suggestions, empty replacements, or unchanged ingredients).
Pasted bullet lists are supported; commas inside parentheses or quoted entries
remain part of the same item. Recipe text uses a separate streaming request.
The browser distinguishes invalid suggestions from provider rate limits,
authentication errors, connection failures and timeouts.

## Current scope

With `DATABASE_URL`, sessions and LangGraph checkpoints live in shared PostgreSQL
storage, so reviews and completed recipes survive cold starts and can be resumed
by another Vercel instance. Atomic request leases prevent concurrent approvals;
interrupted requests become recoverable errors after four minutes. Sessions
expire after six hours and expired checkpoints are removed when new sessions
start. The PostgreSQL store limits new sessions to 30 per client IP per hour
by default. Vercel deployments require this shared store.

Without `DATABASE_URL`, local development uses separate in-memory checkpointers;
restarting Python clears those sessions. Run one worker in this local mode.
The browser remembers only the current session ID in session storage.
The original `recipe_memory.db` is preserved but is not reused by the web app.
There are no user accounts yet. Session IDs grant access to their recipe;
treat them as private. There is a cap of 200 active sessions per store.
Monitor Groq/Vercel usage and set provider spending limits for a public site.
The interface uses optional Google Fonts with local font fallbacks.

For local database integration tests, point `TEST_DATABASE_URL` at a disposable
PostgreSQL database before running pytest. These tests clear Pantry session and
rate-limit tables; never point them at a production database. CI supplies its
own disposable PostgreSQL service. On Windows with a local `DATABASE_URL`, run
Uvicorn with a Selector event loop (psycopg async connections require it), or
run the backend in WSL/Linux.
