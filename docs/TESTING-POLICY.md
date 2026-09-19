# Scrappee Testing Policy

## Designated test user

**TEST USER: `raadunssoftwares@gmail.com`**

This is the ONLY persistent user account permitted for testing, debugging, code review, UI validation, and acceptance testing.

## Mandatory rules

1. Never create another test user.
2. Never create users in bulk to test pagination, deletion, billing, authentication, or any other feature.
3. Reuse the designated account for authenticated UI/API testing.
4. Prefer mocked/in-process identities for automated tests where possible.
5. Never use real customer accounts for testing.
6. Test data created under the designated account must be cleaned up after the test when practical.
7. If a test appears to require another account, stop and ask the CTO instead of creating one.

## Review requirement

Every coding/review agent must read this file before running tests or creating test data.
