# Submission checklist — AMYPO (PS7 + PS1)

Phase 10, submission item 10. Every row is evidence, not intent: the column on
the right is the command or request that proves it, run on this machine.

> **Final verification run (2026-10-14).** The command
> `cd backend && python -m pytest tests -q` collects **206 tests** and passes all
> of them — pytest exit 0, no failures, one `StarletteDeprecationWarning` — with
> MySQL 8 healthy from `docker compose up -d mysql` and the seeded `amypo`
> schema in place. That run was on commit `3f4a66c`; the `final` tag sits on the
> docs-only commit that adds these lines, so no application code changed
> afterwards. The commits above it are confined to the container build path —
> `docker-compose.yml`, the two Dockerfiles, two new `.dockerignore` files and this
> checklist (see the A5 note) — and `final` was moved onto them once the
> containerised stack had been verified end to end.

> Note: the repository does not contain the PS7 problem statement itself, so the
> rows below are the "Hard constraints", "Required API contract" and Phase 1–10
> deliverables transcribed from `PS7_PS1_Build_Prompts (1).md`. Tick these
> against the original PS7 document before submitting in case it lists further
> items.

## A. Hard constraints

| # | Requirement | Status | Evidence |
|---|---|---|---|
| A1 | No paid or external third-party API anywhere | ✅ | Autouse socket guard in `backend/tests/conftest.py`; the same guard in `scripts/evaluate.py`. `make eval` raises on a non-loopback connection |
| A2 | `cloud_api` route is a local simulator (quota, pricing, injected latency/failures) | ✅ | `GET /api/v1/resource-status` reports quota; `/api/v1/simulate` replays scenarios; no socket involved |
| A3 | Open-weight local models only, CPU-only, 8 GB total | ✅ | `docs/model_card.md` §4; eval reports peak RSS 177.8 MB (`docs/eval/report.json` → `headline.peak_ram_mb`, 2026-10-15 full run) against the 8 GB budget, and `docker-compose.yml` limits sum to 7.5 GB |
| A4 | Every answer carries citations (record_id + snippet); ungrounded answers refused or flagged | ✅ | `/api/v1/ask` returns `sources[]`; the verifier flags unsupported claims in the UI and abstains when nothing is supportable |
| A5 | Runs offline and starts with one command | ✅ | `docker compose up` (mysql + backend + frontend + ollama); `README.md` has the one-command path and the offline pre-pull notes. The three services that build from this repository were verified as images on 2026-10-15 (see the note below); `ollama` is image-only and was not pulled on this machine |

**Containerised stack, verified 2026-10-15.** `docker compose build` produces all
three images — `amypoprojectfolder-mysql`, `-backend` and `-frontend`. Bringing the
first two up (`docker compose up -d --no-deps mysql backend`) takes the backend to
compose's own `healthy` state, logging `db: mysql:3306/amypo`, and the required
contract answers from inside the container: `/api/v1/health` 200, `/api/v1/resource-status`
with exactly the four keys, `/api/v1/route` with `request_id / routed_to / reasoning /
latency_ms / estimated_cost`, and `/api/v1/ask` returning a cited answer (confidence
0.9558, 5 sources) and abstaining on an off-corpus question. With the frontend
container added, `GET /` serves 200 and `/api/v1/health` through port 3000 resolves
to the *backend container* (it reports `Linux-...-WSL2`, python 3.12.15) — the full
browser path in Docker.

Two real defects in this path were found and fixed while verifying it, both of
which would have broken the one-command demo:

1. **No `.dockerignore` existed anywhere.** The backend service builds with the
   repository root as its context and the frontend's `COPY . .` runs *after*
   `npm ci`, so builds shipped `frontend/node_modules` and the dev `.next`. Measured:
   the root context was **616.71 MB**, now **6.02 kB**; the frontend context was
   **616 MB**, now **797 kB**. It also stopped the Windows-only
   `@next/swc-win32-x64-msvc` from being copied over `npm ci`'s linux packages.
2. **The frontend could not reach the backend.** `next.config.mjs` calls
   `rewrites()`, which Next evaluates at build time, but `docker-compose.yml` passed
   `NEXT_PUBLIC_API_URL` as a runtime `environment:`. The built image therefore kept
   dialling the config's `127.0.0.1:8000` fallback: `GET /api/v1/health` returned
   **500 with `ECONNREFUSED 127.0.0.1:8000`**, reproduced with the variable set on
   the container, so every API call in the UI would have failed. It is now a
   `build.args` value. `frontend/Dockerfile` also takes `--timeout 120 --retries 10`
   on pip, whose 15 s default aborted the build with `ReadTimeoutError` on a slow
   link.

## B. Required API contract

| # | Endpoint | Status | Evidence |
|---|---|---|---|
| B1 | `POST /ask` → `{answer, sources[{record_id,snippet}], confidence}` | ✅ | Live call returns all three; extra fields documented in `openapi.yaml` |
| B2 | `GET /health` | ✅ | `GET /api/v1/health` → `{"status":"ok", ...}` with per-component detail |
| B3 | `POST /route` → `{request_id, routed_to, reasoning, latency_ms, estimated_cost}` | ✅ | `POST /api/v1/route`; response shape pinned by `tests/test_router.py` |
| B4 | `GET /resource-status` → `{ram_available_mb, cpu_load_pct, bandwidth_kbps, api_quota_remaining}` | ✅ | Live call returns exactly those keys |
| B5 | Extra response fields documented in `openapi.yaml` | ✅ | `tests/test_contract.py` + `tests/test_phase8_addons.py::test_contract_yaml_documents_the_new_addon_fields` compare the spec against the response models |

Beyond `TestClient`, B1–B4 were replayed against the genuinely running stack on
2026-10-15 (`docker compose up -d --wait mysql` + `uvicorn app.main:app` on
`127.0.0.1:8000`, driven with `curl`): `/api/v1/health` → 200 with per-component
detail; `/api/v1/resource-status` → 200 returning exactly the four required keys;
`POST /api/v1/route` with `{"query": ...}` → 200 returning
`{request_id, routed_to, reasoning, latency_ms, estimated_cost}` (it degraded to
`offline_fallback` with the reason `RAM < floor`, which is the intended
adaptivity); `POST /api/v1/ask` → 200 returning `answer`, `sources[{record_id,
snippet}]` and `confidence`, answering with per-claim citations on an answerable
question and abstaining with a clarifying question on an off-corpus one. The same
four endpoints were also reached through the frontend's `/api/v1` rewrite
(`next dev -p 3000`), i.e. the path the browser actually uses.

## C. Phase 10 deliverables

| # | Deliverable | Status | Evidence |
|---|---|---|---|
| C1 | `docker-compose.yml` with mysql (volume, healthcheck, init scripts), backend, frontend, ollama, `mem_limit`s | ✅ | All three buildable images build and their containers reach healthy (see the A5 note); limits sum to 7.5 GB |
| C2 | `README.md`: prerequisites, one-command start, offline setup, seed data, eval, ports, troubleshooting, structure | ✅ | See `README.md` |
| C3 | `openapi.yaml` complete + Postman collection | ✅ | 16 documented paths; `python scripts/make_artifacts.py --only postman` → `docs/postman_collection.json` (16 items derived from the spec) |
| C4 | Architecture diagram (PNG + PDF) | ✅ | `docs/architecture.png` (1746×1167), `docs/architecture.pdf` — regenerate with `make artefacts` |
| C5 | Model / technique card | ✅ | `docs/model_card.md` |
| C6 | Evaluation report | ✅ | `make eval` → `docs/eval/report.html` + `report.json` (Phase 9). Both are generated artefacts and git-ignored (they embed a run id, timestamps and this machine's RAM), so a fresh clone regenerates them with `make eval` (or `cd backend && python ../scripts/evaluate.py` where `make` is not installed); the numbers quoted in section D come from that same full run, replayed 2026-10-15 (`run_id 20261015-111443-ae1c44`, 168 items, 77.9 s wall) |
| C7 | One-page final summary (PDF) | ✅ | `docs/final_summary.pdf`, built from the eval report by `make artefacts` |
| C8 | Demo video script (3–5 min) with click path | ✅ | `docs/demo_script.md` |
| C9 | Clean git history, conventional commits, tagged milestones | ✅ | Phases 8–10 land in conventional commits (`feat: complete the Phase 8 add-ons…`, `feat(eval): add the Phase 9 harness…`, `docs: add the Phase 10 submission pack…`, `feat: abstain before generation…`, `test: check the eval CLI in-process…`); `git tag -n1` → `stage1`, `stage2-mvp`, `final`. Published to `https://github.com/Naveen75cmd/Amypo_PS7_Database-Question-answering-system.git` (branch `master`, all three tags) |
| C10 | Final checklist + "no external network call" proof | ✅ | This file, plus the guards in A1 |

## D. Judging criteria sanity check

| Criterion | Where it is proved |
|---|---|
| Answer accuracy / groundedness (PS7) | `docs/eval/report.json` → `answers.accuracy`, `answers.groundedness` |
| Retrieval precision@k / recall / MRR | `docs/eval/report.json` → `retrieval`, plus the dense/BM25/hybrid ablation |
| Hallucination rate | `docs/eval/report.json` → `answers.hallucination_rate` (5.4 %), `failure_analysis` |
| Abstention on unanswerable questions | `answers.abstention_rate_unanswerable` (60.9 %, 14/23) with `retrieval_relevance_floor` swept in model card §3 |
| Cost/latency reduction vs always-cloud (PS1) | `routing.cumulative_cost_inr` vs `routing.always_cloud_cost_inr` (≈ 98.9 % saved) |
| Routing accuracy | `docs/eval/report.json` → `routing.agreement` against oracle labels — 100.0 % on the last full run (2026-10-15) |
| Resource adaptivity | `scenarios` (ram crash, bandwidth drop, quota exhausted, Ollama down) 6/6 |
| Engineering quality | Typed contracts, `tests/test_contract.py`, module-level tests, `docs/model_card.md` limitations section |

## E. Known gaps at submission time

1. **`make` is not on PATH on the machine these runs were made on**, so the
   `make eval` / `make test` targets were exercised through the direct commands
   `README.md` documents for Windows (`cd backend && python ../scripts/evaluate.py`
   and `cd backend && python -m pytest tests -q`). The Makefile is a thin wrapper
   around exactly those commands.
2. **Item 5's tier 2 is inert**: `tinyllama` is not pulled, so degradation jumps
   from `phi3:mini` to the extractive path (see model card §5).
3. **Abstention on unanswerable questions is 60.9 %** (14/23) in the extractive
   configuration, and 5.4 % of all questions are still hallucinated. The fix
   that got it there is `retrieval_relevance_floor`: abstaining *before*
   generation when the best BM25 score retrieval produced is too low took
   hallucination from 7.7 % to 5.4 % without losing a single correct answer. The
   nine questions still answered anyway are named with their cause and their
   fix in the report's failure analysis; closing them needs a sentence embedder
   to separate "the corpus never mentions this" from "the corpus words it
   differently".
4. **Dense retrieval is effectively off** without `sentence-transformers`, so the
   reported hybrid numbers equal BM25.
5. **The `ollama` service is unverified.** It is image-only in
   `docker-compose.yml` and the image was never pulled on the verification machine
   (a multi-GB download), so the fourth service is untested and every run above
   used the extractive fallback. That is also why gaps 2–4 still apply.
