---
name: review-change
description: Review a change in this repository before it is committed or merged - your own work, a branch, or a pull request. Use when asked to review, check, or sign off on changes, or before reporting a task as done.
---

# Review a change

Review against this repository's own rules in `AGENTS.md`; this skill is the checklist.
Report findings as: file:line, what is wrong, a concrete failure scenario, and the fix.
Do not report style preferences the linters do not enforce.

## 1. Gather the change

- Local work: `git status` and `git diff` (staged and unstaged).
- A branch: `git log --oneline <base>..HEAD` and `git diff <base>...HEAD`.

## 2. Verify, do not trust

Run `python scripts/verify.py`. A change is not done while it fails or prints "NOT COMPLETE"
for a check the change touches. Quote failures exactly.

## 3. Correctness

- Does every behavior change come with a test in `packages/engine/tests/` that fails without it?
- Error paths: subprocess failures, timeouts, missing executables, empty output.
- Windows: paths, `.cmd` shims (`CMD_METACHARS`), CRLF.
- Concurrency in the server and dispatcher: shared state touched from threads or tasks.

## 4. Repository invariants

- **Protocol**: `packages/protocol/types.ts` and `models.py` changed together (see the `change-protocol` skill).
- **Port 8765**: changed in all six places listed in `AGENTS.md` or none.
- **Browser origins**: new WebSocket origins added to `DEFAULT_ALLOWED_ORIGINS` in `server/security.py`.
- **Harness prompts** never placed on argv when the CLI can read stdin or a file.
- **Secrets**: no `.env`, API keys, tokens or credential files in the diff, logs or error messages.

## 5. Commits

- Format `<type>(<scope>): <subject>` with the types and scopes in `AGENTS.md`.
- Atomic: refactor, then fix/feat, then test; at most 5 staged files per commit (lockfiles and docs excluded); config not mixed with source.
- Each commit builds and passes tests on its own.
- No mention of AI tools in commit messages.

## 6. Verdict

End with one line: `ready`, `ready after fixes listed above`, or `not ready: <reason>`.
