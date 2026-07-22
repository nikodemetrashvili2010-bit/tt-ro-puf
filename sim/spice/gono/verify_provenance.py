#!/usr/bin/env python3
"""Bind the archived numerical bundle to its source snapshot in Git history.

This proves only repository-level identity: the listed source and evidence
files coexisted in one reachable commit, and the evidence files have not since
changed. It cannot reconstruct an unrecorded PDK or prove that a particular
tool invocation produced the files.
"""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MANIFEST = Path(__file__).with_name("evidence_manifest.json")


def git(*args):
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def blob_at(commit, path):
    result = subprocess.run(
        ["git", "rev-parse", f"{commit}:{path}"],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = {**manifest["source_files"], **manifest["evidence_files"]}

    matches = []
    for commit in git("rev-list", "--all").splitlines():
        if all(blob_at(commit, path) == blob for path, blob in expected.items()):
            matches.append(commit)

    if not matches:
        raise SystemExit(
            "FAIL: no reachable commit contains the recorded source/evidence bundle"
        )

    changed_evidence = []
    for path, expected_blob in manifest["evidence_files"].items():
        actual_blob = git("hash-object", "--", path)
        if actual_blob != expected_blob:
            changed_evidence.append(path)
    if changed_evidence:
        raise SystemExit(
            "FAIL: archived evidence changed without a new manifest: "
            + ", ".join(changed_evidence)
        )

    current_source = {
        path: git("hash-object", "--", path)
        for path in manifest["source_files"]
    }
    changed_source = [
        path
        for path, blob in current_source.items()
        if blob != manifest["source_files"][path]
    ]
    if not changed_source:
        raise SystemExit(
            "FAIL: manifest expects archived evidence to be older than current source"
        )

    print("PASS: archived source and evidence coexist in reachable history")
    print("PASS: archived evidence blobs still match the manifest")
    print(
        "INFO: evidence is intentionally stale relative to current source; changed: "
        + ", ".join(changed_source)
    )


if __name__ == "__main__":
    main()
