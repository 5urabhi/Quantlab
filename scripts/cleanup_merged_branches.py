#!/usr/bin/env python3
"""Prune only same-repository branches whose exact head was merged into main.

Run with --apply and a GH_TOKEN with repository contents:write permissions.
Dry-run is the default. The script never deletes main, protected branches,
branches with open PRs, or branches with unmerged/changed head commits.

GitHub's built-in delete_branch_on_merge setting is administrative; this
workflow provides equivalent automatic cleanup without modifying that setting.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


MAX_PAGES = 50
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def eligible_merged_heads(
    repository: str,
    default_branch: str,
    branches: list[dict],
    closed_prs: list[dict],
    open_prs: list[dict],
) -> list[tuple[str, int, str]]:
    """Return (name, merged PR number, SHA) only for unchanged, merged heads."""
    by_name = {b["name"]: b for b in branches}
    open_heads = {
        p["head"]["ref"]
        for p in open_prs
        if (p.get("head") or {}).get("repo", {}).get("full_name") == repository
    }
    result: dict[str, tuple[str, int, str]] = {}
    for pr in closed_prs:
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        head_repo = (head.get("repo") or {}).get("full_name")
        name = head.get("ref")
        sha = head.get("sha")
        if (not pr.get("merged_at") or base.get("ref") != default_branch
                or head_repo != repository or not name or not sha
                or name == default_branch or name in open_heads):
            continue
        branch = by_name.get(name)
        if not branch or branch.get("protected"):
            continue
        if (branch.get("commit") or {}).get("sha") != sha:
            # The branch was reused or gained new commits after the PR merged.
            continue
        result[name] = (name, int(pr["number"]), sha)
    return sorted(result.values())


class Github:
    def __init__(self, repository: str, token: str, api_url: str):
        if not REPO_PATTERN.fullmatch(repository):
            raise ValueError("Invalid repository name")
        if not token:
            raise ValueError("GH_TOKEN required to inspect/delete GitHub refs")
        self.repository = repository
        self.base = api_url.rstrip("/") + "/repos/" + repository
        self.token = token

    def request(self, path: str, method: str = "GET"):
        url = self.base + path
        req = Request(url, method=method, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "quantlab-safe-branch-hygiene",
        })
        try:
            with urlopen(req, timeout=25) as response:
                payload = response.read()
                return json.loads(payload) if payload else None
        except HTTPError as exc:
            if exc.code == 404 and path.startswith(("/branches/", "/git/refs/")):
                # Race/idempotent cleanup: already deleted on another run.
                return None
            raise RuntimeError(
                f"GitHub API {method} failed with HTTP {exc.code} "
                f"for {path.split('?')[0]}"
            ) from exc

    def pages(self, path: str) -> list[dict]:
        records: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            suffix = "&" if "?" in path else "?"
            batch = self.request(f"{path}{suffix}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise ValueError("Unexpected GitHub collection response")
            records.extend(batch)
            if len(batch) < 100:
                return records
        raise RuntimeError("GitHub pagination safety limit reached")

    def branch(self, name: str):
        return self.request("/branches/" + quote(name, safe=""))

    def delete_branch(self, name: str):
        # Explicit refs/heads namespace only; never touch tags.
        return self.request("/git/refs/heads/" + quote(name, safe="/"),
                            method="DELETE")


def cleanup(api: Github, *, apply: bool = False) -> dict:
    metadata = api.request("")
    default = metadata["default_branch"]
    branches = api.pages("/branches")
    closed = api.pages("/pulls?state=closed&sort=updated&direction=desc")
    open_prs = api.pages("/pulls?state=open")
    candidates = eligible_merged_heads(
        api.repository, default, branches, closed, open_prs
    )
    deleted, changed = [], []
    for name, pr_number, sha in candidates:
        # Just-in-time read prevents deletion when a branch moved after listing.
        current = api.branch(name)
        if not current:
            changed.append(name + " (already deleted)")
            continue
        if current.get("protected") or current["commit"]["sha"] != sha:
            changed.append(name + " (protected or head moved)")
            continue
        if apply:
            api.delete_branch(name)
            deleted.append(name)
            print(f"DELETED {name} (merged PR #{pr_number})")
        else:
            print(f"DRY RUN {name} (merged PR #{pr_number})")
    summary = {
        "repository": api.repository,
        "default_branch": default,
        "total_branches_before": len(branches),
        "merged_head_candidates": len(candidates),
        "deleted": len(deleted),
        "preserved_unmerged_or_active": (
            len(branches) - len(candidates) - 1
        ),
        "changed_during_cleanup": changed,
        "dry_run": not apply,
    }
    print("BRANCH_CLEANUP_SUMMARY " + json.dumps(summary, sort_keys=True))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Delete eligible merged PR head branches")
    args = parser.parse_args()
    api = Github(
        os.environ.get("GH_REPO", ""),
        os.environ.get("GH_TOKEN", ""),
        os.environ.get("GH_API_URL", "https://api.github.com"),
    )
    cleanup(api, apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
