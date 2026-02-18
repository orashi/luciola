# Codex Autopilot Workflow (Bangumi Automation)

This repo now uses a git-first maintenance flow.

## Prerequisites
- `codex` CLI installed
- `OPENAI_API_KEY` available in environment
- Run from repo root (`bangumi-automation/`)

## Fast path (autopilot patch loop)

```bash
# 1) Create a feature branch
BRANCH="codex/$(date +%Y%m%d-%H%M)-short-task"
git switch -c "$BRANCH"

# 2) Ask Codex to implement task
codex exec --full-auto -C . "<task description + acceptance criteria>"

# 3) Validate
pytest -q

# 4) Commit
git add -A
git commit -m "feat: <what changed>"
```

## Guidance
- Keep each Codex run focused on one outcome.
- Prefer small diffs and testable changes.
- Never commit `.env` or `data/` runtime files.
- If tests fail, run another Codex iteration with concrete failing output.

## Suggested prompt template

```text
Task: <what to change>
Context: Python app in bangumi-automation/
Constraints:
- keep API behavior backward compatible unless explicitly stated
- no secrets in code
- preserve existing cron/operator behavior
Done when:
- tests pass
- brief changelog in commit message body
```
