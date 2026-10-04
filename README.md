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
citations); embeddings live in FAISS. Connection defaults match compose
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

## Verify it works

```bash
cd backend && python -m pytest          # all tests, with the offline guard
curl http://127.0.0.1:8000/api/v1/health
curl -X POST http://127.0.0.1:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the minimum attendance required to sit exams?","user_id":"S102"}'
curl http://127.0.0.1:8000/api/v1/resource-status
```

### Measure it

Two harnesses turn the numbers in this README from claims into measurements:

```bash
cd backend
python -m app.retrieval            # retrieval ablation: dense / bm25 / hybrid / rerank
python -m app.eval.answer_eval     # end to end: coverage, citations, abstention
python -m app.eval.answer_eval --model   # same, through the real local model
```

With the deterministic extractive fallback (no model pulled), the answer harness
currently reports roughly 143/145 answerable questions answered with a citation,
89/107 numeric agreement, and 11/23 unanswerable questions correctly abstained.
The remaining unanswerable misses are cases where an unrelated passage shares a
word with the question; the real generation path is expected to abstain on them.

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
  placement/  eligibility, suitability, skill gaps
  eval/       benchmark harness
  db/         SQLAlchemy + PyMySQL connection and migration runner
db/           MySQL schema.sql, migrations, my.cnf, image Dockerfile
frontend/     Next.js 14 chat product
data/         raw, synthetic, eval, sim
docs/         architecture, evaluation reports, model card
```

The backend and the tests need MySQL running. `python -m pytest` bootstraps a
throwaway `amypo_test` schema so it never disturbs the seeded `amypo` database.

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
