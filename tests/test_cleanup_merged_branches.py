"""Safe merged-PR branch pruning; runs fully offline with fake GitHub state."""
import unittest

from scripts.cleanup_merged_branches import cleanup, eligible_merged_heads


REPO = "5urabhi/nifty50-momentum-backtest"


def branch(name, sha="abc", protected=False):
    return {"name": name, "commit": {"sha": sha}, "protected": protected}


def pr(number, name, sha="abc", *, merged=True, base="main",
       repo=REPO, open_state=False):
    return {
        "number": number,
        "merged_at": "2026-11-20T00:00:00Z" if merged else None,
        "state": "open" if open_state else "closed",
        "base": {"ref": base},
        "head": {"ref": name, "sha": sha, "repo": {"full_name": repo}},
    }


class FakeGithub:
    repository = REPO
    def __init__(self, branches, closed, opened=(), moved=()):
        self.branches = list(branches)
        self.closed = list(closed)
        self.opened = list(opened)
        self.moved = set(moved)
        self.deleted = []

    def request(self, path, method="GET"):
        if not path:
            return {"default_branch": "main"}
        raise AssertionError("Unexpected API request " + path)

    def pages(self, path):
        if path == "/branches":
            return self.branches
        if path.startswith("/pulls?state=closed"):
            return self.closed
        if path == "/pulls?state=open":
            return self.opened
        raise AssertionError("Unexpected collection " + path)

    def branch(self, name):
        row = next((x for x in self.branches if x["name"] == name), None)
        if row is None:
            return None
        if name in self.moved:
            return {**row, "commit": {"sha": "new-unmerged-head"}}
        return row

    def delete_branch(self, name):
        self.deleted.append(name)


class CleanupBranchesTests(unittest.TestCase):
    def setUp(self):
        self.branches = [
            branch("main", "latest"),
            branch("feature/merged-old"),
            branch("fix/merged-new", "bbb"),
            branch("research/unmerged"),
            branch("hotfix/protected", protected=True),
            branch("feature/reused", "new-sha"),
            branch("feature/has-open-pr"),
        ]
        self.closed = [
            pr(1, "feature/merged-old"),
            pr(2, "fix/merged-new", "bbb"),
            pr(3, "research/unmerged", merged=False),
            pr(4, "hotfix/protected"),
            pr(5, "feature/reused", "old-sha"),
            pr(6, "feature/has-open-pr"),
            pr(7, "main", "latest"),
            pr(8, "feature/merged-old", base="develop"),
            pr(9, "feature/merged-old", repo="somebody/otherrepo"),
        ]
        self.opened = [pr(10, "feature/has-open-pr", open_state=True)]

    def test_merged_sha_and_same_repository_are_required(self):
        candidates = eligible_merged_heads(
            REPO, "main", self.branches, self.closed, self.opened
        )
        self.assertEqual(
            [(name, number) for name, number, _ in candidates],
            [("feature/merged-old", 1), ("fix/merged-new", 2)]
        )

    def test_dry_run_does_not_delete_anything(self):
        api = FakeGithub(self.branches, self.closed, self.opened)
        summary = cleanup(api, apply=False)
        self.assertEqual(summary["merged_head_candidates"], 2)
        self.assertEqual(summary["deleted"], 0)
        self.assertEqual(api.deleted, [])

    def test_apply_deletes_only_exact_merged_heads(self):
        api = FakeGithub(self.branches, self.closed, self.opened)
        summary = cleanup(api, apply=True)
        self.assertEqual(summary["deleted"], 2)
        self.assertEqual(api.deleted,
                         ["feature/merged-old", "fix/merged-new"])
        self.assertNotIn("main", api.deleted)
        self.assertNotIn("research/unmerged", api.deleted)

    def test_changed_head_is_not_deleted(self):
        api = FakeGithub(self.branches, self.closed, self.opened,
                         moved=("feature/merged-old",))
        summary = cleanup(api, apply=True)
        self.assertEqual(api.deleted, ["fix/merged-new"])
        self.assertEqual(summary["deleted"], 1)
        self.assertTrue(summary["changed_during_cleanup"])

    def test_deleted_fork_head_does_not_break_open_pr_scan(self):
        self.opened.append({
            "number": 11, "head": {"ref": "legacy", "repo": None}
        })
        candidates = eligible_merged_heads(
            REPO, "main", self.branches, self.closed, self.opened
        )
        self.assertEqual(len(candidates), 2)


if __name__ == "__main__":
    unittest.main()
