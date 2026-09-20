# ADR-0002 — Extraction Engine Benchmark

**Status:** Proposed benchmark; no production architecture change approved.
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
benchmark target is the previously audited 150 SERP records, including positive cases,
false positives, email-only records, generic-page titles, profile pages, and varied evidence
wording.

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
