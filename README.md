# AMYPO Campus Assistant

A fully offline **Database Question-Answering System** with an integrated
**low-cost AI request router** and a **placement eligibility matcher**.

Built for HackWithAMYPO 2026 (PS7 + PS1) by Team Tech Titans.

- Every answer is grounded and carries citations (`record_id` + snippet).
- Every question is routed by a live-resource-aware policy: cache, local model,
  offline extractive fallback, or a **simulated** cloud API.
- Numbers never come from the language model; they come from SQL.
- No paid or external API is used anywhere. A test suite blocks outbound
  sockets to prove it.

## Quick start

```bash
# 1. Backend dependencies
python -m pip install -r backend/requirements.txt

# 2. Start MySQL 8 (named volume + schema init from /db/migrations)
docker compose up -d --wait mysql

# 3. Generate synthetic AMYPO-style data and the benchmark set
python scripts/generate_data.py

# 4. Load structured rows + documents into MySQL, then index them
cd backend && python -m app.ingest --path ../data/raw --structured ../data/synthetic && cd ..

# 5. Run the API
cd backend && python -m uvicorn app.main:app --reload --port 8000
```

MySQL exposes the exact data (grades, attendance, schedules, chunk text and
citations); embeddings live in FAISS when `faiss-cpu` is installed and in a
numpy exact-cosine index otherwise (`/health` names the active backend).
Connection defaults match compose
(`amypo` / `amypo` on `127.0.0.1:3306`) and are overridable with `AMYPO_MYSQL_*`.

Then, in a second terminal:

```bash
cd frontend && npm install && npm run dev
```

Open <http://localhost:3000>. API docs are at
<http://127.0.0.1:8000/docs>.

### One command with Docker

```bash
docker compose up
```

That also pulls `phi3:mini` into the Ollama **container** through the one-shot
`ollama-pull` service, so the model is there on a fresh machine without a manual
step (`make models` re-runs it at any time). The container has its own model
store: `ollama pull phi3:mini` run in Windows PowerShell fills the host's
`%USERPROFILE%\.ollama`, which the backend never reads, so the dashboard card
still says **model not pulled**. That is the single most common setup mistake,
and the card now names the command that fixes it.

> If something else on the machine already owns port **11434** (a system-wide
> Ollama, for instance), compose aborts while creating its own `ollama` service
> with `bind: Only one usage of each socket address`. The API, the database and
> the web app are unaffected — bring them up without that fourth service:
>
> ```bash
> docker compose up -d --no-deps backend frontend
> ```
>
> The backend then reports `llm: degraded` and answers through the extractive
> fallback, which is exactly the offline behaviour the demo already shows.

## Sign in

The app has one entry point: `/login`. Every other page redirects there without
a session and returns you to the page you wanted afterwards. Login is local —
bcrypt password hashes, a short-lived JWT and a revocable refresh token, both in
httpOnly cookies — and there is no external identity provider.

The role is read from the signed token on every request. It is never taken from
the question text, a query parameter or the `user_id` field, and it is enforced
in route dependencies, in the retrieval filter and in the SQL templates. The
model is never asked to enforce it.

| Role | Sees | Does |
|---|---|---|
| **Student** | Public documents, own grades, attendance, schedule, own placement | Ask about their own record; see own eligibility, skill gap and what-if |
| **Staff** | Public **and staff-only** documents, records of their assigned departments | Cohort placement queries, criteria edits for assigned companies, read-only dashboard |
| **Admin** | Everything, including admin-only documents | Accounts, ingestion, router settings, scoring weights, dashboard, evaluation, audit log |

Demo accounts (seeded when `AMYPO_DEMO_MODE=true`, password `amypo-demo-2026`):

| Username | Role | Scope |
|---|---|---|
| `admin` | admin | everything |
| `staff.cse` | staff | Computer Science cohort |
| `staff.ece` | staff | Electronics and Communication cohort |
| `staff.mech` | staff | Mechanical cohort |
| `s101` … `s400` | student | that student's own records |
| `harness` | eval | read-only, public documents only |

The organisers' evaluation harness has two ways in: log in as `harness`, or set
`AMYPO_SERVICE_API_KEY` and send it as `X-API-Key`. Either way the scope is
read-only public data. `/health` and `/resource-status` stay open, so a harness
that only checks liveness needs no credentials at all.

## Verify it works

```bash
cd backend && python -m pytest          # all tests, with the offline guard
curl http://127.0.0.1:8000/api/v1/health          # open, no auth
curl http://127.0.0.1:8000/api/v1/resource-status # open, no auth

# Everything else needs a session. Get a token, then ask:
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"s102","password":"amypo-demo-2026"}' | python -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

curl -X POST http://127.0.0.1:8000/api/v1/ask \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" \
  -d '{"question":"What is the minimum attendance required to sit exams?"}'
```

For a hand-run acceptance pass — every screen, the exact question to type and
what you should see — follow [docs/manual_test.md](docs/manual_test.md) (45
checks with ids, plus a 10-minute smoke path and a triage table). The same plan
is generated as `docs/manual_test_guide.pdf` by `make guides`.

### Measure it

Two harnesses turn the numbers in this README from claims into measurements:

```bash
cd backend
python -m app.retrieval            # retrieval ablation: dense / bm25 / hybrid / rerank
python -m app.eval.answer_eval     # end to end: coverage, citations, abstention
python -m app.eval.answer_eval --model   # same, through the real local model
python -m app.router               # classifier accuracy + savings vs always-cloud
python -m app.router --train       # retrain the complexity classifier
```

The Phase 9 harness ties those together into one reproducible artefact:

```bash
make eval                                  # or: cd backend && python ../scripts/evaluate.py
make eval -- --limit 40 --no-load-test     # quick run
```

It replays the 168-question benchmark through the real pipeline and writes
`docs/eval/report.html` (self-contained: headline metrics, the dense/BM25/hybrid/
hybrid+rerank and with/without-verifier ablations, verifier/relevance-floor/
cache/RAM-floor threshold sweeps with an accuracy-vs-hallucination plot, the
six resource
scenarios with pass/fail, the 20-user load test, peak RSS against the 8 GB
budget, and the 10 worst questions with cause and fix) plus
`docs/eval/report.json` with the raw numbers. The same run is reachable from the
frontend's Evaluation page (`POST /api/v1/eval/run`).

With the deterministic extractive fallback (no model pulled), the answer harness
currently reports 135/145 answerable questions answered (120 of them with a
citation), 75.2 % accuracy, and 9/23 unanswerable questions correctly abstained
— 8.3 % of all questions still hallucinated. Two mechanisms decide that: the
claim verifier, and a relevance gate that abstains *before* generation when the
best BM25 score retrieval produced is below `retrieval_relevance_floor`. That
gate's own sweep in the report — one real answer pass per floor — is where its
worth is visible: gate off, 10.1 % hallucination at 26.1 % abstention; the
shipped 9.0, 8.3 % and 39.1 % with no correct answer lost; 12.0, 3.0 % and
78.3 % for three correct answers. The questions still answered anyway are
listed with their cause in the report's failure analysis.

## Submission artefacts

Everything the final submission needs is generated, not hand-drawn, so it cannot
drift from the code:

```bash
make artefacts        # or: python scripts/make_artifacts.py
make guides           # or: python scripts/make_guides.py
```

| Artefact | What it is |
|---|---|
| `docs/architecture.png` / `.pdf` | Component diagram (UI → API → router/monitor → retrieval/cache → LLM/verifier/placement → MySQL/index/eval) |
| `docs/final_summary.pdf` | One page: problem, approach, innovations, and the headline numbers pulled from the last `docs/eval/report.json` |
| `docs/product_guide.pdf` | Product and engineering guide: one request end to end, every model and threshold, the datasets, the module map and the measured results |
| `docs/user_manual.pdf` | User manual: sign in, ask, read an answer, what each role can do, troubleshooting |
| `docs/postman_collection.json` | Postman v2.1 collection derived from `openapi.yaml` (import, set `baseUrl`, run) |
| `docs/model_card.md` | Models, licences, training data, thresholds, footprint, failure modes |
| `docs/demo_script.md` | The 3–5 minute walkthrough with its exact click path |
| `docs/submission_checklist.md` | Hard constraints, API contract and deliverables, each with its evidence |

Regenerate the diagram, the summary and the collection in one step after changing
the architecture, the eval numbers or the API.

## Models

The pipeline runs in three modes, detected automatically:

| Mode | When | Behaviour |
|---|---|---|
| Real | Ollama reachable + `sentence-transformers` installed | `phi3:mini` generation, real embeddings |
| Stub | Models unavailable, or `AMYPO_STUB_LLM=true` | Deterministic extractive stub LLM and hash embeddings |
| Disabled | `AMYPO_ALLOW_REAL_MODELS=false` | Never loads a model; fully deterministic |

To pull the real models:

```bash
ollama pull phi3:mini      # ~2.3 GB, primary
ollama pull tinyllama      # ~640 MB, low-RAM fallback
python -m pip install sentence-transformers faiss-cpu
```

## Project layout

```
backend/app/
  api/        HTTP routers + middleware
  core/       settings, logging, schemas, service container
  db/         SQLAlchemy + PyMySQL connection and migration runner
  ingest/     document and structured loaders, chunking
  retrieval/  embeddings, BM25, FAISS, RRF fusion, reranking
  llm/        Ollama client + deterministic stub
  grounding/  claim-level verifier
  cache/      semantic cache
  monitor/    resource monitor, bandwidth + cloud simulators
  router/     complexity classifier, decision engine
  placement/  eligibility, suitability, skill gaps, what-if, ask answers
  eval/       benchmark harness
db/           MySQL schema.sql, migrations, my.cnf, image Dockerfile
frontend/     Next.js 14 chat product
data/         raw, synthetic, eval, sim
docs/         architecture, evaluation reports, model card
```

The backend and the tests need MySQL running. `python -m pytest` bootstraps a
throwaway `amypo_test` schema so it never disturbs the seeded `amypo` database.

## Ports and troubleshooting

| Service | Port | Notes |
|---|---|---|
| Frontend (Next.js) | 3000 | `npm run dev`; proxies `/api/v1` to the backend, so no CORS setup is needed |
| Backend (FastAPI) | 8000 | Swagger at `/docs`, spec at `/openapi.json`, health at `/api/v1/health` |
| MySQL | 3306 | `amypo` (seeded) and `amypo_test` (throwaway, created by the suite) |
| Ollama | 11434 | Loopback only |

| Symptom | Cause and fix |
|---|---|
| `can't connect to MySQL` | `docker compose up -d --wait mysql` (or `make db`), then `make seed ingest index` |
| Dashboard says **model not pulled** | The Ollama the backend uses has no `phi3:mini`. With compose that is the container's own store, not the host's: `docker compose run --rm ollama-pull` (or `make models`). Running `ollama pull` in PowerShell only fills the host store |
| Dashboard says **unavailable** | The backend cannot reach Ollama at all: `docker compose up -d ollama`, or start `ollama serve` for a host-run backend |
| `/api/v1/ask` answers say "offline mode" | Ollama is down or `phi3:mini` is not pulled: `ollama serve`, `ollama pull phi3:mini` |
| Answers quote evidence instead of generating | RAM below the 900 MB floor with the model resident, or the model is unavailable. This is the three-tier fallback working, not a fault |
| `index is empty` | Run `python -m app.ingest --path ../data/raw --structured ../data/synthetic` |
| Tests unexpectedly slow | A local Ollama makes tests use the model; the suite pins the deterministic stub unless a test is marked `real_model` |
| `pip install -r requirements.txt` fails on `reportlab`/`matplotlib` | They are declared dependencies, needed for the PDF export and `make artefacts` |

## Notes on the spec

- The PS7 PDF's objective section describes placement matching while the
  official statement describes QA. **Both are implemented**: QA is the core
  path, placement is a first-class feature.
- Stage 3 mentions "proprietary/self-built models" while the constraints say
  "open-weight / locally hosted". We use open-weight base models plus
  self-built components (complexity classifier, reranker config, matcher) and
  document this in `docs/model_card.md`.
- AMYPO's sample database was not available, so the ingestion layer is
  schema-driven and the data is synthetic with the same shape. Swapping in the
  real data is a config change.
