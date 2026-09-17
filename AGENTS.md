# LLM Engineering Rules

## Test-user policy — mandatory

- NEVER create a new user account for testing, debugging, review, screenshots, or validation.
- Use ONLY the single designated test user documented in `docs/TESTING-POLICY.md`.
- If the designated test user is unavailable, STOP and ask the CTO. Do not create a replacement account.
- Do not seed, mass-create, loop-create, or generate test users in code, scripts, fixtures, migrations, or manual commands.
- Existing production/customer users must never be used for testing.
- Tests that need authentication must reuse the designated test identity or use mocked/in-process authentication; they must not create additional persistent accounts.
- Before any test/review that creates persistent data, clean up the data afterward without deleting the designated test account.
- This rule overrides convenience. A failing test is not permission to create another test user.

## Source of truth

- Product behavior: `docs/V1.3-SOURCE-OF-TRUTH.md`
- API contract: `docs/SCRAPPEE-V1.3-API-HANDOFF.md`
- Test-user identity: `docs/TESTING-POLICY.md`


## Extension source of truth — mandatory

- Scrappee Browser Extension behavior: `docs/SCRAPPEE-BROWSER-EXTENSION-SOURCE-OF-TRUTH.md`
- This document is canonical for extension UX, authentication persistence, SERP capture, and Scrappee handoff.
- Do not change the agreed extension workflow without explicit CTO approval and a corresponding source-of-truth update.
