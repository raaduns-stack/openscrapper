# ADR-0002 — Extraction Engine Benchmark

**Status:** Benchmark complete; GLiNER-Relex primary SERP extraction approved and implemented.
**Date:** 2026-09-20
**Decision owner:** CTO

## 1. Problem

The current extraction layer contains deterministic parsing rules that have grown to cover
specific SERP wording patterns. This is becoming brittle when the same lead evidence is
expressed with different roles, geographies, punctuation, providers, or page layouts.

Example evidence such as:

`D Jaworowski · CRNA in Albany, New York`

can satisfy the Lead contract without matching a growing list of hard-coded keyword forms.
The engineering question is whether a mature information-extraction component can recover
this structure more generally while preserving our existing qualification and persistence
contracts.

## 2. Architectural constraint

The existing Lead acceptance contract remains authoritative and is not changed by this
benchmark:

```text
(first_name OR last_name)
AND
at least ONE of:
position, company_name, phone, city, state, country, website
```

If an email is present it must be personal. Extraction technology must produce evidence;
it does not decide Lead acceptance.

## 3. Proposed boundary

The benchmark evaluates a separation between extraction and qualification:

```text
SERP/page evidence
       ↓
information extraction
       ↓
structured entities / relations
       ↓
candidate reconstruction
       ↓
existing Lead validation
       ↓
existing qualification
       ↓
existing dedupe / persistence
```

Scrapy remains the acquisition/crawl engine. Existing persistence, dedupe, qualification,
and export behavior remain unchanged during the spike.

## 4. Candidate technologies

### Primary benchmark candidates

- **GLiNER2** — schema-driven entity/relation extraction; evaluate for PERSON, LOCATION,
  ORGANIZATION, JOB_ROLE and relevant relations.
- **spaCy** — mature NLP/NER framework; evaluate standard NER plus the minimum custom
  component configuration required for our lead schema.

### Ecosystem references

- Apache UIMA remains a reference architecture for composable unstructured-information
  processing, but is not part of the first benchmark.
- OpenSearch remains a retrieval/ranking option and is not part of the first extraction
  benchmark. Retrieval and extraction are separate concerns.

Official references:
- https://spacy.io/usage/linguistic-features
- https://spacy.io/
- https://github.com/fastino-ai/GLiNER2
- https://uima.apache.org/
- https://docs.opensearch.org/latest/vector-search/ai-search/index/

## 5. Benchmark corpus

Use a fixed corpus of existing SERP evidence already available in the project. The initial
benchmark target is 150 persisted SERP records, including positive cases, false positives,
email-only records, generic-page titles, profile pages, and varied evidence wording. The
first smoke run used the latest 150 persisted `serp_results` records available at execution
time; this is distinct from the earlier 150-record audit used to inspect the existing Lead set.

The corpus must be frozen for each benchmark run so candidate systems receive identical
input. No production records are modified by the benchmark.

## 6. Required extraction schema

The benchmark output should normalize into the fields already consumed by the Lead model:

- first_name
- last_name
- position
- company_name
- phone
- city
- state
- country
- website
- email
- source_url

The extractor must also retain enough provenance to determine which source text supported
each extracted field. No value may be invented or inferred beyond the extractor's evidence.

## 7. Test categories

The corpus must be evaluated across at least these categories:

1. Person + role + location in natural prose.
2. Person + role separated by punctuation such as `·`, `—`, or commas.
3. Person + company without an email.
4. Person + phone/location without an email.
5. Personal email embedded in otherwise weak evidence.
6. Generic mailbox/email-list/database pages.
7. Company-only and name-only pages.
8. Author/profile/LinkedIn-style pages.
9. One-name profiles where the source explicitly identifies a person.
10. Different occupations and geography terms, without extractor-specific keyword templates.

## 8. Measurement

The benchmark must report, at minimum:

- person-field extraction precision
- person-field extraction recall
- supporting-field extraction precision
- supporting-field extraction recall
- accepted-lead precision under the existing Lead contract
- rejected-record false-positive rate
- records missed by the current extractor but recovered by the candidate
- records accepted by the candidate that the current contract correctly rejects
- runtime per record
- dependency/model footprint

No overall score, ranking, or automatic replacement decision is produced by the benchmark.
Results are evidence for the CTO's architecture decision.

## 9. Comparison modes

Run the same frozen corpus through:

A. Current deterministic extractor.
B. spaCy candidate extractor.
C. GLiNER2 candidate extractor.

All three outputs are passed through the same Lead validation and qualification contract.
Where a candidate requires a schema adapter, that adapter is benchmark code only.

## 10. Safety boundary

The spike must not:

- change production extraction behavior;
- change Lead qualification rules;
- change dedupe identity rules;
- change persistence behavior;
- delete or rewrite existing production leads;
- alter production credentials or service configuration;
- commit or push to stable `main`.

The benchmark may add isolated test/benchmark code on the current engineering branch.

## 11. Decision gate

After the benchmark, present measured results and implementation trade-offs to the CTO.
Possible outcomes are:

1. Keep the current extractor and selectively improve it.
2. Augment the current extractor with a mature IE layer.
3. Replace the deterministic extraction layer with a mature IE-based implementation.

No outcome is preselected by this ADR.

## 12. Implementation order

1. Freeze and load the benchmark corpus.
2. Implement candidate adapters outside the production pipeline.
3. Run identical inputs through all candidates.
4. Normalize outputs to the existing Lead schema.
5. Apply the unchanged validation/qualification contract.
6. Generate an auditable comparison report.
7. CTO reviews results and chooses the integration direction.

**This ADR authorizes the benchmark spike only. It does not authorize production integration.**
## 13. Initial smoke-benchmark result — 2026-09-20

A read-only smoke benchmark was executed against a frozen 150-record SERP corpus. The
production database was not modified. The comparison used the current deterministic parser,
spaCy `en_core_web_sm`, and GLiNER2.5 small on CPU.

Observed output:

| Engine | Person records | Supporting-evidence records | Existing Lead contract accepted |
|---|---:|---:|---:|
| Current deterministic | 29 | 7 | 7 |
| spaCy `en_core_web_sm` | 91 | 91 | 86 |
| GLiNER2.5 small | 96 | 95 | 70 |

These are **not precision/recall measurements** because the 150 records do not yet have a
manually verified gold label set. They must not be interpreted as accuracy scores.

The smoke test demonstrates two important engineering facts:

1. Mature NER/IE components recover substantially more person and supporting-field mentions
   than the current deterministic parser on this corpus.
2. Naively accepting any extracted person plus any extracted supporting field creates clear
   false associations. For example, GLiNER2 can associate organization/page-title entities
   with a person candidate that is not a real individual lead.

A direct replacement with raw NER output is therefore not approved. The next benchmark step
must test person-to-role/company/location association using schema/relations/context and a
manually reviewed gold subset before any production integration decision.

The current benchmark used the CPU-oriented `fastino/gliner2.5-small-v1` checkpoint. The
GLiNER2 project documents `fastino/gliner2.5-base-v1` as its default English multi-task
checkpoint and the small checkpoint as the fast CPU/edge option.

## 10. Approved implementation: deterministic SERP discovery with contextual enrichment

The CTO selected Option B after the live SERP attribution defect: deterministic extraction is the candidate-discovery layer; GLiNER-Relex is an enrichment layer. The production extraction boundary remains authoritative:

1. Run the deterministic SERP extractor first for each SERP record.
2. A personal email may form a complete candidate even when no person name is present.
3. Run GLiNER-Relex only to enrich a deterministic candidate with missing person-specific fields.
4. Never promote a contextual-only title/category guess into an accepted SERP lead.
5. Relation confidence remains at or above the configured threshold for contextual fields.
6. Validate the final merged candidate through the authoritative `Lead` contract before qualification and persistence.
7. If contextual extraction fails, the deterministic candidate remains valid and the scrape continues.

The deterministic layer also requires explicit person evidence for name-based candidates; generic title/category text without person evidence is rejected.

Configuration:
- `CLAW_CONTEXTUAL_EXTRACTION=1` enables contextual enrichment (default).
- `CLAW_CONTEXTUAL_EXTRACTION=0` disables contextual enrichment and retains deterministic-only SERP extraction.
- `CLAW_CONTEXTUAL_MODEL` selects the GLiNER-Relex model.
- `CLAW_CONTEXTUAL_RELATION_THRESHOLD` controls the minimum relation confidence; default `0.80`.

GLiNER-Relex is not the authoritative candidate-discovery layer or qualification layer. No raw NER/relationship output may bypass the existing `Lead` contract.

## 14. Integration boundary: first-level extraction vs enrichment

The CTO-approved operating model treats SERP extraction as first-level candidate recovery rather than final-field verification.

## 15. Approved SERP extraction mode: deterministic discovery + GLiNER-Relex enrichment

The CTO selected Option B after the live SERP attribution defect. For each SERP record, the deterministic parser runs first and establishes the candidate. GLiNER-Relex then enriches only that candidate with missing contextual fields. There is no contextual-only promotion path.

Personal email is a complete acceptance path. Deterministic name-based candidates require explicit person evidence; generic title/category text is rejected. The final merged record must pass the authoritative Lead contract before qualification and persistence.

The general LLM extractor is not invoked by this SERP path. GLiNER-Relex is an enrichment component, not the authority for candidate discovery or lead correctness.

Enrichment remains responsible for deeper correction and completion. The controlled Scrapy enrichment engine revisits the persisted lead's source URL and related bounded pages, applies the page extraction stack, validates extracted candidates, and persists supported field corrections/additions through the same authoritative persistence path. It may also discover additional qualifying people.

This separation keeps first-level SERP discovery deterministic and evidence-gated while allowing contextual extraction to improve completeness without turning page titles or category text into false leads.

No separate qualification contract, persistence path, or dedupe path is permitted for contextual extraction or enrichment.
