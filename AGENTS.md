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
## Git release control — mandatory CTO gate

- All implementation commits are LOCAL commits on the current feature/development branch by default.
- NEVER `git push`, merge, rebase into stable/main, or otherwise publish/promote changes to the remote repository without an explicit CTO command.
- A local commit does NOT mean the change is stable, approved, tested, or released.
- The CTO alone decides when a feature branch is ready to push and when it becomes stable.
- Testing and validation happen before any requested push/merge; do not treat a local commit as approval.
- Remote GitHub must be treated as release-controlled infrastructure, not as the default destination for commits.
- If the CTO says to commit, commit locally only unless the same instruction explicitly requests a push.
- If the CTO says to make it stable, do not push/merge unless the command explicitly authorizes the push/merge.

## Progress preservation — mandatory

- Treat all existing working code, UI, behavior, configuration, and documentation as protected baseline unless the CTO explicitly approves a change.
- Before modifying code, audit the current implementation and the applicable source-of-truth documents. Never edit first based on assumptions.
- Define the change boundary before implementation: files/components/functions affected, existing behavior that must remain unchanged, and the new behavior being added.
- Before modifying a file, create a dated backup when practical; never overwrite or replace a working file wholesale when a surgical change is sufficient.
- Do not redesign, refactor, rename, remove, or alter unrelated working features as part of an improvement.
- Preserve existing UI/design and hand-built functionality unless the CTO explicitly approves a redesign.
- Never use broad staging such as `git add .` when unrelated working-tree changes exist. Stage only the files and changes belonging to the approved task.
- Before commit, validate the affected code, review the actual diff, and confirm unrelated changes are not included.
- If achieving the requested improvement requires architectural changes or risks existing functionality, stop and ask the CTO for direction rather than deciding unilaterally.
- Every improvement must be additive or surgical by default: preserve current progress first, then implement the approved change.
