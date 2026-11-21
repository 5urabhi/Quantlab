# QuantLab GitHub branch hygiene

## What is automated

The repository's `.github/workflows/merged-branch-cleanup.yml` runs on each
push to `main`, on each PR closed with `merged: true`, and by manual
`workflow_dispatch`. It uses GitHub's limited per-workflow `GITHUB_TOKEN`
(`contents: write`) to remove obsolete **remote branch refs**.

Only branch heads satisfying **all** of these checks are deleted:

1. The PR was actually merged into the repository's **current default branch**.
2. The PR head belongs to **this repository**, not a contributor's fork.
3. The branch is still present, not protected, not the default branch, and
   not currently used by an open PR.
4. Its **current exact commit SHA** still equals the head SHA of the merged
   PR. If new work was added after merging, the branch is preserved.
5. The branch head is checked again immediately before attempting deletion.

Closed-but-unmerged PRs, work-in-progress research branches and branches
without a merged PR are **not deleted**. The original PR discussions,
commits, merge history, source files and CI logs remain in GitHub.

## Initial cleanup inventory (November 20, 2026)

At the start of this change, the repository had **76 branches**, including
`main`. 72 had SHA-matched merged PRs and were cleanup candidates.

The three unmerged or otherwise unconfirmed branches were intentionally
preserved:

- `feature/quantlab-local-backup-execution-stress-20261117`
- `research/multi-factor-equity-index` (PR #1 closed, **not merged**)
- `workstation/quant-research-development-20261112`

These counts are a historical snapshot; inspect the workflow logs for actual
deletion counts and errors. Deletion is never inferred solely from the
existence of this workflow.

## Native GitHub setting

GitHub also has **Settings → General → Pull Requests → Automatically delete
head branches**. The connected repository tool does not expose the GitHub
repository-administration mutation for that checkbox. The scheduled/on-merge
workflow is a functional alternative, not a claim that this native repository
setting is enabled.

If a repository administrator chooses to turn on that checkbox separately,
this workflow remains safe and idempotent: it skips branches GitHub already
deleted. The workflow can be removed later if native auto-deletion is
sufficient.

## Testing and manual recovery

Unit tests are in `tests/test_cleanup_merged_branches.py`. The script
defaults to dry-run; `--apply` explicitly deletes eligible refs.

No personal access token is stored in code. A fork's source branch is never
targeted, and protected branches cannot be deleted by this workflow.

If GitHub Actions reports `HTTP 403` when attempting to delete a branch,
check repository Actions permissions and `contents: write` in the workflow.
Do not bypass branch protection or silently mark cleanup complete.
