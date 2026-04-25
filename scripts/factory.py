#!/usr/bin/env python3
"""Factory script to create LLM toolkit repos via GitHub API.

Usage:
    python scripts/factory.py --repo llmtrace --token $GITHUB_TOKEN
    python scripts/factory.py --all --token $GITHUB_TOKEN
"""
import argparse
import json
import sys
import time
from base64 import b64encode
from typing import Any, Dict, Optional

try:
    import urllib.request as req
except ImportError:
    raise SystemExit("Python 3.9+ required")

REPOS = {
    "llmtrace": "LLM call tracer with span recording",
    "promptvault": "Versioned prompt template storage with history tracking",
    "modelrouter": "Route LLM requests to appropriate models based on configurable rules",
    "contextpacker": "Pack and truncate context windows for LLM prompts",
    "evalframe": "Lightweight evaluation framework for LLM outputs",
}


class GitHubClient:
    BASE = "https://api.github.com"

    def __init__(self, token: str, owner: str):
        self.token = token
        self.owner = owner

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }

    def request(self, path: str, method: str = "GET", body: Optional[Dict] = None):
        url = self.BASE + path
        data = json.dumps(body).encode() if body else None
        request = req.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with req.urlopen(request) as resp:
                return resp.status, json.loads(resp.read())
        except Exception as e:
            return getattr(e, "code", 0), {}

    def repo_exists(self, repo: str) -> bool:
        status, _ = self.request(f"/repos/{self.owner}/{repo}")
        return status == 200

    def create_repo(self, repo: str, description: str) -> bool:
        status, _ = self.request(
            "/user/repos", "POST",
            {"name": repo, "description": description, "private": False, "auto_init": True}
        )
        return status == 201

    def get_head(self, repo: str):
        _, ref = self.request(f"/repos/{self.owner}/{repo}/git/refs/heads/main")
        head = ref["object"]["sha"]
        _, commit = self.request(f"/repos/{self.owner}/{repo}/git/commits/{head}")
        base_tree = commit["tree"]["sha"]
        return head, base_tree

    def create_blob(self, repo: str, content: str) -> str:
        encoded = b64encode(content.encode()).decode()
        _, blob = self.request(
            f"/repos/{self.owner}/{repo}/git/blobs", "POST",
            {"content": encoded, "encoding": "base64"}
        )
        return blob["sha"]

    def create_tree(self, repo: str, base_tree: str, files: Dict[str, str]) -> str:
        items = []
        for path, content in files.items():
            blob_sha = self.create_blob(repo, content)
            items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})
        _, tree = self.request(
            f"/repos/{self.owner}/{repo}/git/trees", "POST",
            {"base_tree": base_tree, "tree": items}
        )
        return tree["sha"]

    def create_commit(self, repo: str, tree_sha: str, parent_sha: str, message: str) -> str:
        _, commit = self.request(
            f"/repos/{self.owner}/{repo}/git/commits", "POST",
            {"message": message, "tree": tree_sha, "parents": [parent_sha]}
        )
        return commit["sha"]

    def update_ref(self, repo: str, sha: str) -> None:
        self.request(f"/repos/{self.owner}/{repo}/git/refs/heads/main", "PATCH", {"sha": sha})

    def create_tag(self, repo: str, sha: str, tag: str = "v0.1.0") -> None:
        self.request(
            f"/repos/{self.owner}/{repo}/git/refs", "POST",
            {"ref": f"refs/tags/{tag}", "sha": sha}
        )

    def set_topics(self, repo: str, topics: list) -> None:
        self.request(f"/repos/{self.owner}/{repo}/topics", "PUT", {"names": topics})


def ensure_repo(client: GitHubClient, repo: str, description: str) -> bool:
    if client.repo_exists(repo):
        print(f"  [skip] {repo} already exists")
        return True
    print(f"  [create] {repo}...")
    if not client.create_repo(repo, description):
        print(f"  [error] failed to create {repo}")
        return False
    time.sleep(4)
    return True


def main():
    parser = argparse.ArgumentParser(description="Create LLM toolkit repos")
    parser.add_argument("--token", required=True, help="GitHub PAT")
    parser.add_argument("--owner", default="vdeshmukh203", help="GitHub username")
    parser.add_argument("--repo", help="Single repo to create")
    parser.add_argument("--all", action="store_true", help="Create all repos")
    args = parser.parse_args()

    client = GitHubClient(args.token, args.owner)
    targets = {}

    if args.repo:
        if args.repo not in REPOS:
            print(f"Unknown repo: {args.repo}. Available: {list(REPOS.keys())}")
            sys.exit(1)
        targets = {args.repo: REPOS[args.repo]}
    elif args.all:
        targets = REPOS
    else:
        parser.print_help()
        sys.exit(1)

    for repo, desc in targets.items():
        print(f"\nProcessing {repo}...")
        ensure_repo(client, repo, desc)
        print(f"  [done] {repo}")

    print("\nAll done.")


if __name__ == "__main__":
    main()
