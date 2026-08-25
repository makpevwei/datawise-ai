# DataWise AI — Agent Accuracy Evaluation

Real-LLM evaluation of the agentic layer, run against the actual configured
provider (no mocks). This is a measured result, not a target — see
[Known issues found](#known-issues-found) for the specific failures behind the
number, including two that were investigated and diagnosed live.

## Methodology

- **Harness**: `backend/scripts/eval_agent.py`. Boots the real FastAPI app in-process
  (`TestClient`), with the dataset/document stores pointed at a throwaway temp
  directory (so the run never mixes with or pollutes real persisted data) — the LLM
  dependency is **not** overridden, so every question hits the real provider. As of
  Phase 4, `/ask` routes through the LangGraph router (`app/agent/graph.py`) before
  the agent loop, so each question now costs one additional real LLM call versus
  the Phase 3 baseline.
- **Provider/model**: `openai` / `gpt-4o-mini`. Per Phase 3A/4 instructions, Gemini/
  Groq/OpenRouter currently have unrelated account issues (invalid key, stale
  model, no credits/quota) documented in the Phase 3A report — OpenAI is the only
  reliable real provider, so it is what this evaluation uses.
- **Data**: the real sample datasets — `products.csv` (59 rows), `orders.csv`
  (1,259 rows), `customers.csv` (1,037 rows) — plus one synthetic document,
  `backend/tests/eval_fixtures/management_commentary.md`, created solely to exercise
  document retrieval and cross-data/document reasoning. It is not real business data.
- **Session isolation**: 22 of 25 questions run in their own fresh session so a
  category's result isn't contaminated by unrelated prior context. Questions 23–25
  are a deliberately chained mini-conversation to test conversational memory.
- **Grading**: manual, by a person (well, Claude) reading every returned answer
  against the actual known-correct figures (independently computed in Phase 2 for
  several of these exact aggregates) and against whether the agent used the
  deterministic engine correctly.
- **Runs**: two full, independent 25-question runs plus four small targeted
  retests used to diagnose specific results (see below). All real, all reported.
  - Baseline (Phase 3, pre-4): 2026-08-23, `scripts/eval_results_phase3_baseline.json`.
  - Phase 4 run 1 (before two targeted fixes described below):
    `scripts/eval_results_phase4_run1.json`.
  - Phase 4 run 2 (after fixes, clean re-run) — **the primary reported number**:
    `scripts/eval_results.json`.
  - Targeted retests (diagnostic only, not part of either scored run):
    `scripts/eval_retest_7_9.py`, `eval_retest_19.py`, `eval_retest_21_22.py`,
    `eval_retest_10_debug.py`.
- **Run date**: 2026-08-24.

## What changed between run 1 and run 2

Run 1 (19/25 = 76%, *below* the Phase 3 baseline) surfaced two categories of
problem, and both were investigated rather than left as an unexplained number:

1. **Q19's known mislabeling bug (Phase 3 known-issue #3) was still present** —
   expected, since the code fix (see below) was written *after* run 1 started.
   A live retest of Q19 alone, after the fix, confirmed it: the real LLM still
   mislabels the claim as `VERIFIED_FROM_DATA` (same as before — this is an LLM
   habit, not something a prompt reliably stops), but `app/agent/planner.
   _build_finding` now mechanically reclassifies any non-numeric claim that
   carries a real citation to `DOCUMENT_EVIDENCE` regardless of what label the
   model chose, with a `verification_note` explaining the reclassification. This
   is a code-level fix, not a prompt hope, so it doesn't depend on the model
   getting it right.
2. **Q8 and Q9 failed in run 1** where the Phase 3 baseline succeeded on the same
   questions. A clean targeted retest of Q7–Q9 (`eval_retest_7_9.py`) reproduced
   *success* on all three, with Q9's numbers matching the baseline's
   independently-verified figures exactly ($1,625.64 → $2,098.92, +29.11%). This
   confirms run 1's Q8/Q9 failures were one-off real-LLM flakiness in that
   specific run, not a Phase 4 regression — and run 2 confirms it: both pass.
3. **The flagship cross-data/document structured comparison (`claim_comparisons`,
   Phase 3 known-issue #2)** was empty (0/2) in both the baseline and run 1's raw
   output. The synthesis prompt was strengthened with a mandatory-population rule,
   a worked few-shot example, and an explicit "call search_documents yourself even
   if the question already states the claim" instruction. A targeted retest of
   Q21/Q22 after this change got Q22 fully right (real citation,
   `CONTRADICTED_BY_DATA`, correct numbers) but Q21 reverted to empty — LLM
   instruction-following remains imperfect. Run 2 reproduced the same split:
   Q22 passes, Q21 doesn't (the model skips `search_documents` because the
   question already states the claim in its own words).

Run 2 is the clean, single, unmodified 25-question run reported below as the
primary score — it already includes both fixes, run once, no cherry-picking.

## Question set and results (run 2 — primary reported score)

| # | Category | Question | Result |
|---|----------|----------|--------|
| 1 | simple_aggregation | Total price across all orders? | ✅ $69,788.81 |
| 2 | simple_aggregation | Average order price? | ✅ $55.43 |
| 3 | filtering | Total price for CASH orders? | ✅ $21,767.21 |
| 4 | filtering | Orders with late delivery risk? | ✅ 625 |
| 5 | ranking | Region with most total price? | ✅ North Africa, $18,050.80 (25.86%) |
| 6 | ranking | Most-used shipping mode? | ✅ First Class 28.12%, all four modes' percentages correct (Phase 3's spurious-100% bug not observed in either Phase 4 run) |
| 7 | joins | Product category, most revenue (join)? | ✅ Electronics, $13,264.13 (19.01%) |
| 8 | joins | Customer segment, most orders (join)? | ✅ Consumer 678 (53.85%), Corporate 358 (28.44%), Home Office 223 (17.71%) — correct; failed in run 1, confirmed one-off (see above) |
| 9 | time_comparison | Compare 2023-01 vs 2023-02. | ✅ $1,625.64 → $2,098.92, +29.11% — matches baseline exactly |
| 10 | time_comparison | Monthly trend of order price? | ❌ Agent guessed a wrong `dataset_id` ("orders.csv" instead of the real id) and a wrong column name ("order_price" instead of "price"), got clear tool errors both times, but exhausted its 8-tool-call budget recovering before finding `list_datasets`/the right column. **Diagnosed live**: a clean debug retest of the identical question self-corrected within budget (`list_datasets` → `inspect_schema` → correct `generate_chart` call) and produced a fully correct chart. Real LLM tool-use variance, not a broken tool — see below. |
| 11 | anomaly_detection | Unusual values in price? | ✅ None found |
| 12 | anomaly_detection | Anomalies in cost column? | ✅ None found |
| 13 | multi_dataset | Relationships between datasets? | ✅ Correct |
| 14 | multi_dataset | List datasets and row counts. | ✅ Correct (5 datasets — 3 uploaded + 2 joined, from Q7 and Q8) |
| 15 | chart_generation | Chart of total price by region. | ❌ Same failure mode as Q10 (wrong `dataset_id` guessed, budget exhausted before recovery) |
| 16 | chart_generation | Small dashboard for orders. | ✅ Total price/cost/quantity/order count all correct |
| 17 | insufficient_data | Profit margin in yen last decade? | ✅ Correctly refused, zero tool calls |
| 18 | insufficient_data | Customers churned last year? | ✅ Correctly refused after checking |
| 19 | document_retrieval | Why did West Africa underperform (commentary)? | ✅ Correct citation; **label now `DOCUMENT_EVIDENCE`** (was `VERIFIED_FROM_DATA` in the baseline — known-issue #3, now fixed at the code level, confirmed on this live run) |
| 20 | document_retrieval | Shipping risk flagged by management? | ✅ Correct citation and label (`DOCUMENT_EVIDENCE`) |
| 21 | cross_data_document | Does data support the West Africa explanation? | ❌ `claim_comparisons` still empty — the model computed the right data (303 total orders, 84 Standard Class) but never called `search_documents`, so no citation exists to build a comparison from. Correctly *not* asserting an uncited verdict; still an instruction-following gap. |
| 22 | cross_data_document | Does data support "Footwear is strongest by volume"? | ✅ **Full pass**: real citation via `search_documents`, `claim_comparisons` populated, `CONTRADICTED_BY_DATA`, correct numbers (Electronics 234 vs. Men's Footwear 22) — this is the flagship worked example from the Phase 4 spec, working end-to-end on a real LLM |
| 23 | conversational_memory | Show total price by region. | ✅ Correct (sets up follow-ups) |
| 24 | conversational_memory | Now show only the top 2. | ❌ Same bug as the Phase 3 baseline: switched dimension to "top 2 customers/products" instead of "top 2 regions" — unfixed, not attempted this phase (out of Phase 4's scope; documented for a future pass) |
| 25 | conversational_memory | What about by shipping mode instead? | ✅ Correct, tool-verified numbers throughout (framing shifted from price to quantity/count vs. the baseline's price-only framing — not wrong, just a different but still-verified cut) |

## Measured accuracy

| Metric | Baseline (Phase 3) | Run 1 (raw, before fixes) | **Run 2 (primary, after fixes)** |
|---|---|---|---|
| **Overall accuracy** | 20/25 = 80% | 19/25 = 76% | **21/25 = 84%** |
| Cross-data/document (IDs 21–22) | 0/2 = 0% | 0/2 = 0% (structurally populated for the first time, but both `INSUFFICIENT_EVIDENCE`) | **1/2 = 50%** (Q22 full pass; Q21 still empty) |
| Document-label correctness (IDs 19–20) | 1/2 (Q19 mislabeled) | not re-verified until fix landed | **2/2 = 100%** (code-level fix, confirmed live) |
| Chart generation (IDs 10, 15) | 2/2 | 2/2 | 0/2 (real LLM tool-use variance, diagnosed as recoverable — see below) |
| Conversational memory (IDs 23–25) | 2/3 | not separately isolated | 2/3 (same known bug, unfixed) |

**84% is the honest, measured number for the primary run** — an improvement over
the 80% baseline, but not because everything got better: the flagship cross-data/
document feature and the label-mislabeling bug both genuinely improved (with real
code changes, not just favorable variance), while a new class of failure
(chart-generation tool-parameter guessing) appeared that didn't show up in either
prior baseline run. Never claim more than this — 84% is what was measured once,
cleanly, and it comes with an explicit list of what's still broken.

## Diagnosis: chart-generation failures (Q10, Q15)

Both failures follow an identical pattern, confirmed by inspecting the actual
tool `output_summary` text (not just tool names) via a debug retest:

1. The model calls `generate_chart` with a guessed `dataset_id` (the filename,
   e.g. `"orders.csv"`) instead of the real id — the tool correctly rejects this
   with `Error: Dataset 'orders.csv' not found.`
2. It then calls `inspect_schema` with the *same wrong id*, gets the same error.
3. Eventually (in the failing run, too late — the 8-tool-call budget ran out
   first) it would call `list_datasets`, discover the real id, retry with a
   guessed column name (`"order_price"`), get `Error: Column 'order_price' not
   found`, call `inspect_schema` with the *correct* id, see the real column name
   (`"price"`), and succeed.

A clean debug retest of the exact same question, same clean dataset state,
completed this exact recovery sequence *within* budget and produced a correct
chart. So the tool, its error messages, and the underlying deterministic engine
are all working correctly — this is real-LLM behavioral variance in how
efficiently the model recovers from a wrong first guess, not a Phase 4 code
regression. A worthwhile follow-up (not attempted this phase, to avoid
open-ended prompt-tuning against a single eval run): explicitly instruct the
model to call `inspect_schema` before any tool call that needs a specific column
name, the same way the join-safety instruction already tells it to check
cardinality before `join_datasets`.

## Known issues found

1. ~~**Spurious "100%" statistic (baseline IDs 6, 8).**~~ Not observed in either
   Phase 4 run (both runs' Q6 and Q8 report correct percentages across all
   categories). No code change targeted this directly; it may be an incidental
   effect of the "only call tools that are actually relevant" instruction added
   for tool-scoping, or simply run-to-run LLM variance. Not claimed as a
   deliberate fix.

2. ~~**`claim_comparisons` not populated for either cross-data/document question
   (baseline IDs 21, 22).**~~ **Improved, not fully fixed.** The synthesis prompt
   now mandates population with a worked few-shot example and an explicit
   "retrieve it yourself, even if the question states the claim" rule. Result:
   1/2 full passes with a real citation and correct verdict (Q22); Q21 still
   skips `search_documents` and leaves the comparison empty. Root cause remains
   prompt-adherence on a case-by-case basis, not architecture — the mechanism
   itself (verified by `test_run_agent_resolves_document_citation_from_real_chunk`,
   `verify_claim_comparison`, and the live Q22 result) works correctly end-to-end
   when the model does call the tool.

3. ~~**Verifier doesn't catch category-mislabeled non-numeric claims (baseline ID
   19).**~~ **Fixed at the code level.** `app/agent/planner._build_finding` now
   reclassifies any claim with a real attached citation and no digits to check
   (i.e. it can't be a calculated fact) to `DOCUMENT_EVIDENCE`/`VERIFIED_FROM_WEB`
   regardless of the label the LLM claimed, with an explicit
   `verification_note`. Confirmed on a live retest: the model still mislabels the
   claim as `VERIFIED_FROM_DATA` (an LLM habit unaffected by prompting), but the
   final answer now correctly shows `DOCUMENT_EVIDENCE` every time, because the
   fix doesn't depend on the model getting it right.

4. **Conversational memory carried context inconsistently (ID 24 vs. 25).**
   Unfixed, unchanged from baseline, not attempted this phase — "now show only
   the top 2" still drops the region dimension from the prior turn. A minor new
   side effect was also observed: the mandatory-`claim_comparisons` instruction
   (added for issue #2) sometimes fires on a plain data-only follow-up with no
   real document claim in play (ID 24 and 25 in run 2 both show a spurious
   `claim_comparisons` entry whose "document_claim" is just the model's own
   calculated finding restated). Verification correctly gates these to
   `INSUFFICIENT_EVIDENCE` (never a false `SUPPORTED`/`CONTRADICTED`), so this is
   noise, not a safety issue, but it's worth tightening in a future pass (e.g.
   only populate `claim_comparisons` when a `search_documents`/
   `retrieve_document_evidence` call actually happened this turn).

5. **NEW: chart-generation tool-parameter guessing under budget pressure (IDs
   10, 15).** See the diagnosis above. Not present in the baseline; introduced
   risk is real-LLM variance exposed by these two specific questions, not a
   broken tool (confirmed recoverable on retest, and `generate_dashboard`, which
   exercises the same KPI-discovery-to-chart path, succeeded in every run).

## Real embeddings, real document types, real large-dataset test (Phase 4 additions)

Separately from the 25-question LLM evaluation (which reuses the Phase 3 sample
set + synthetic fixture), Phase 4 added:

- **Real document ingestion**, 9 actual files from `data/samples/` covering
  every newly/previously-supported type (PDF ×3, DOCX, PY ×2, TXT ×2, MD): zero
  errors, 8.87s total ingest time, 345 chunks. A real retrieval query
  ("retrieval augmented generation embeddings") correctly surfaced the RAG paper
  (both its PDF and DOCX copies) as the top 3 results with correct page/heading
  metadata, confirming the free local HuggingFace embedding path works on real
  content, not just synthetic test fixtures.
- **Large-dataset performance**, the real 43.5MB `online_retail_II.xlsx`
  (1,067,371 rows across 2 sheets): 483.6s to ingest+profile (an existing,
  unmodified Phase 2 characteristic of openpyxl-based XLSX parsing at this
  scale, not a Phase 4 regression), then 0.019s for a `calculate_metric` call and
  0.001s for a repeat of the same call — confirming the existing architecture
  already avoids re-parsing on every tool call, as required.
- See `docs/embeddings.md` for the embedding model choice/rationale and the
  measured first-query embedding cost for a fresh document corpus (~189s for
  345 chunks, one-time and cached thereafter).

## Latency

Run 2: 25 questions total (exact wall time not separately isolated from the
harness's own overhead in this run, unlike the baseline's 6.1-minute figure).
Per-question range: 3.8s (immediate abstention, zero tool calls) to 59.9s (a
document-retrieval question — includes the LangGraph router's extra LLM call
plus tool-calling iterations). Every question now pays one additional real LLM
call versus the Phase 3 baseline for the router's classification step.

## Overall assessment

The deterministic engine, join-safety refusal, and document-retrieval/citation
mechanisms are all solid — every number that *was* correctly routed through a
tool matched ground truth in both Phase 4 runs, and the two targeted code fixes
(finding reclassification, strengthened cross-document instruction) each showed
real, reproducible improvement on live retests. The honest gap is concentrated
in the same place it was in the baseline: real-LLM instruction-following at the
edges — sometimes skipping a retrieval step it was told to always take (Q21),
sometimes guessing a tool parameter instead of inspecting schema first (Q10,
Q15), sometimes dropping context across a conversational follow-up (Q24). None
of these are architecture problems; all are addressable through further prompt
iteration, which was intentionally not pursued indefinitely against a single
eval run to avoid overfitting the prompt to this exact question set.
