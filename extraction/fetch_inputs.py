#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Fetch every declared Phase A input and write the input manifest.

Reads `sources.json`, downloads each file into `inputs/`, and records the URL,
the retrieval date, the byte size and the SHA-256 of what actually arrived.
The manifest it writes is the artifact Phase A depends on; the downloaded
bytes are reproducible from it and are not committed.

Needs network, so it does not run in CI and it does not run on the folder
bridge. `verify_inputs.py` checks its output and needs neither.

    python3 fetch_inputs.py                 # fetch everything declared
    python3 fetch_inputs.py --target ID     # one target only
    python3 fetch_inputs.py --selftest      # planted faults, no network
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = os.path.join(HERE, "sources.json")
MANIFEST = os.path.join(HERE, "INPUT_MANIFEST.json")
INPUTS = os.path.join(HERE, "inputs")
TIMEOUT = 180
SCHEMA = "phaseA-manifest/1"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_entries(entries):
    """Digest of digests, so a manifest edited by hand stops verifying.

    Canonical form is one line per entry, tab separated, sorted by local path.
    Any field that a later step trusts has to be inside this string.
    """
    lines = []
    for e in sorted(entries, key=lambda e: e["local"]):
        lines.append("\t".join([
            e["local"], e["target"], e["class"], str(e["bytes"]),
            e["sha256"], e["url"], e["retrieved_utc"],
        ]))
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def url_for(repos, spec):
    repo = repos[spec["repo"]]
    return repo["raw"].format(commit=repo["commit"], path=spec["path"])


def local_for(spec):
    return os.path.join(spec["repo"], spec["path"]).replace("\\", "/")


def fetch(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "tt-ro-puf-phaseA/1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        if resp.status != 200:
            raise RuntimeError("%s returned HTTP %s" % (url, resp.status))
        body = resp.read()
    with open(dest, "wb") as fh:
        fh.write(body)
    return len(body)


def run(only_target=None):
    with open(SOURCES) as fh:
        src = json.load(fh)
    repos = src["repos"]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries, failures = [], []
    for target in src["targets"]:
        if only_target and target["id"] != only_target:
            continue
        for spec in target["files"]:
            url = url_for(repos, spec)
            local = local_for(spec)
            dest = os.path.join(INPUTS, local)
            try:
                size = fetch(url, dest)
            except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as exc:
                failures.append((local, url, str(exc)))
                print("  MISS %-62s %s" % (local, exc))
                continue
            entries.append({
                "local": local,
                "target": target["id"],
                "class": spec["class"],
                "bytes": size,
                "sha256": sha256_file(dest),
                "url": url,
                "retrieved_utc": stamp,
            })
            print("  ok   %-62s %9d B" % (local, size))

    manifest = {
        "schema": SCHEMA,
        "written_utc": stamp,
        "sources_sha256": sha256_file(SOURCES),
        "targets": [
            {k: t[k] for k in
             ("id", "shuttle", "chip_position", "title", "author", "tiles",
              "page", "role", "why_chosen")}
            for t in src["targets"] if not only_target or t["id"] == only_target
        ],
        "repos": {k: {kk: v[kk] for kk in ("url", "commit", "what")}
                  for k, v in repos.items()},
        "inputs": sorted(entries, key=lambda e: e["local"]),
        "manifest_digest": digest_entries(entries),
    }
    with open(MANIFEST, "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")

    print("\n%d inputs, %d bytes, digest %s"
          % (len(entries), sum(e["bytes"] for e in entries),
             manifest["manifest_digest"][:16]))
    if failures:
        print("%d declared inputs did not arrive:" % len(failures))
        for local, url, exc in failures:
            print("   %s  <- %s  (%s)" % (local, url, exc))
        return 1
    return 0


# --------------------------------------------------------------------------
# selftest: the faults this script exists to avoid, planted and caught


def selftest():
    """Plant the faults, confirm they are caught. No network, no inputs."""
    ok = True

    def check(name, condition):
        nonlocal ok
        print("  %-58s %s" % (name, "pass" if condition else "FAIL"))
        ok = ok and condition

    base = [{
        "local": "a/b.gds", "target": "t", "class": "layout", "bytes": 10,
        "sha256": "ab" * 32, "url": "https://x/y", "retrieved_utc": "2026-08-16T00:00:00Z",
    }, {
        "local": "a/c.spef", "target": "t", "class": "parasitics", "bytes": 20,
        "sha256": "cd" * 32, "url": "https://x/z", "retrieved_utc": "2026-08-16T00:00:00Z",
    }]
    d0 = digest_entries(base)

    # order must not matter, or the digest depends on the order of the walk
    check("digest is order independent", digest_entries(base[::-1]) == d0)

    for field, value in (("sha256", "ef" * 32), ("bytes", 11),
                         ("url", "https://x/other"), ("class", "netlist"),
                         ("retrieved_utc", "2026-08-17T00:00:00Z"),
                         ("target", "u"), ("local", "a/b2.gds")):
        tampered = [dict(base[0]), dict(base[1])]
        tampered[0][field] = value
        check("editing %-14s breaks the digest" % field,
              digest_entries(tampered) != d0)

    dropped = digest_entries(base[:1])
    check("dropping an entry breaks the digest", dropped != d0)

    added = base + [dict(base[0], local="a/d.lef")]
    check("adding an entry breaks the digest", digest_entries(added) != d0)

    # a swap of two entries' hashes is the fault a per-file check would miss
    swapped = [dict(base[0]), dict(base[1])]
    swapped[0]["sha256"], swapped[1]["sha256"] = base[1]["sha256"], base[0]["sha256"]
    check("swapping two hashes breaks the digest", digest_entries(swapped) != d0)

    # sha256_file has to read the file, not the name
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "f.bin")
        with open(p, "wb") as fh:
            fh.write(b"hello")
        want = hashlib.sha256(b"hello").hexdigest()
        check("sha256_file matches hashlib", sha256_file(p) == want)
        with open(p, "ab") as fh:
            fh.write(b"!")
        check("one appended byte changes the hash", sha256_file(p) != want)

    # url templating must use the pinned commit and never a branch name
    repos = {"r": {"raw": "https://raw.githubusercontent.com/o/r/{commit}/{path}",
                   "commit": "0" * 40}}
    u = url_for(repos, {"repo": "r", "path": "src/x.v"})
    check("url pins the commit", "0" * 40 in u and "/main/" not in u)

    print("\nselftest %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", help="fetch only this target id")
    ap.add_argument("--selftest", action="store_true",
                    help="plant the faults and confirm they are caught")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    return run(args.target)


if __name__ == "__main__":
    sys.exit(main())
