# Contributing

## Commit message guardrails

Use neutral, repository-scoped commit messages.

- ✅ `brand: adopt selected luciola logo`
- ✅ `fix(api): handle dict-shaped /api/shows payload`
- ❌ `...from Doctor`
- ❌ chat-style addressing (`dear`, `sir`, etc.)

This repo includes a local `commit-msg` hook under `.githooks/`.
If your clone does not enforce it yet, run:

```bash
git config core.hooksPath .githooks
```
