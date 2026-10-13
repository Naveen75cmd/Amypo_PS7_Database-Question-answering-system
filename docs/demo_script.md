# Demo script (3–5 minutes)

Phase 10, submission item 8. Every step below is a real interaction against the
running stack — nothing is mocked, and each beat names what the audience should
notice rather than what to click mechanically.

## Before recording

```bash
docker compose up -d --wait mysql     # MySQL on 3306
cd backend && python -m uvicorn app.main:app --port 8000
cd frontend && npm run dev            # http://localhost:3000
ollama serve                          # phi3:mini already pulled
```

Warm the demo's headline moment (optional but recommended, ~2 min with the model
up): answer a few questions in chat, thumbs-up the good ones, then press
**Retrain** on the dashboard so the first run of the script already shows a
delta. Do one manual pass of the click path immediately before recording — it
primes the semantic cache, so beat 3 hits instantly.

---

### 0:00 — The problem (20 s)

Show the chat landing page. Say the constraint out loud: this runs entirely
offline, on one machine, inside 8 GB, with no third-party API — and every answer
must point at the record it came from.

### 0:30 — Grounded answer with citations (45 s)

Type: **"What is the minimum attendance required to sit exams?"**

Point out, in the delivered card:

* each sentence is underlined because it is a *claim*, and clicking it opens the
  evidence sentence and the record id it came from (Phase 8 item 2);
* the citation chips `[S1] [S2]` open the source passage;
* the footer line — route, latency, cost in INR, kWh, and **grounded N/N claims**.

Then ask **"Compare the 2019 attendance policy with the current one."** The
amber banner names both records, the value each one states (75 % vs 60 %), and
which one won by `updated_at` — the disagreement is surfaced instead of silently
resolved (item 6).

### 1:15 — Cache (30 s)

Ask the **same** question again. The route chip flips to **cache**, latency drops
to well under a millisecond, and the cost line reads 0.00 INR. Explain that this
is not luck: historical questions are warmed into the cache at ingest time, per
access scope, so the demo does not depend on someone repeating themselves
(item 5). The dashboard's *Saved INR* and cache-hit rate show the cumulative
effect.

### 1:45 — Resource adaptivity and the three-tier fallback (45 s)

Open **Dashboard**. Under *Scenarios* press **ram crash**, then show the decision
log: every request reroutes and the reasoning column says why. Switch to chat and
ask a question: the card now carries the amber "offline mode" banner and the tier
chip reads **Offline (extractive)** — the answer is quoted from evidence rather
than generated (item 4). Press **reset to stable** on the dashboard.

Meanwhile the *Resource status* tiles (RAM, CPU, bandwidth, quota, Ollama) are
live — if the machine is genuinely short on RAM, say so and point at the chip,
because that is the system making the same honest trade-off unprompted.

### 2:15 — Placement: eligibility, gap, what-if (45 s)

Switch the demo role to **Student** and ask **"Am I eligible for TCS Digital?"**
The answer lists the failing criteria with numbers, and the **Career Readiness**
card opens the placement workspace for that student (item 8). In the placement
page, run the skill gap and the what-if sliders — eligibility is *decided* from
criteria, never generated.

Press **Elevate eligibility report** / download the PDF: the same report as a
self-contained file, with the verdict column, the missing criteria and the
learning path (item 11).

### 3:00 — Cost versus always-cloud (30 s)

Back on **Dashboard**, read *Cumulative cost vs always-cloud baseline*: the
measured INR spent against what the same traffic would have cost with a cloud
call every time (≈ 98.9 % saved in the reference run). This is the sustainability
line item — energy and money, per query, on the same chart (item 9).

### 3:40 — Unanswerable question → abstention (30 s)

Ask something the corpus cannot answer, e.g. **"How many seats does the campus
auditorium have?"**, then a hostel question that retrieves the wrong records.
When the system abstains it says plainly that no record supported an answer,
lists the **closest records** it did find so the question can be narrowed, and
asks a clarifying question (item 3). Point out the alternative: an assistant that
never abstains is an assistant that fabricates.

### 4:15 — Eval numbers and self-optimising router (30 s)

Press **Retrain**. The panel shows the accuracy before and after on the same
held-out questions, plus how many thumbs ratings fed it (`N confirmed, M
corrected`) — item 1's "router improved from 84 % to 89 %" made real and
auditable. Then open **Evaluation** and show the measured headline numbers
(accuracy, groundedness, hallucination rate, abstention on unanswerable,
retrieval MRR, routing agreement, peak RAM, 6/6 resource scenarios, load test) —
or show `docs/eval/report.html` from `make eval`.

### 4:45 — Close (15 s)

Two last screens, quickly: the **Audit trail** page listing every staff cohort
query with who ran it and how many records it touched (item 7), and
`docs/model_card.md` for models, licences, thresholds and known failure modes.
Close on the claim the whole build rests on: it answers from campus records, it
says when it cannot, and nothing it does talks to the internet.
