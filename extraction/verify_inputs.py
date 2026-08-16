#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Check the Phase A input manifest against the source list and the disk.

Written not to share code with `fetch_inputs.py`. The check that matters is the
one that does not need the fetcher to be right: given the files, this re-derives
every size and every SHA-256 itself and compares. Where the files are absent —
in CI, on the folder bridge — it falls back to the manifest's own digest, which
catches a manifest edited by hand but cannot catch a file that changed under it.
Both are reported separately so nobody reads the weaker one as the stronger one.

    python3 verify_inputs.py                  # manifest only
    python3 verify_inputs.py --inputs inputs  # manifest and the bytes
    python3 verify_inputs.py --selftest       # planted faults
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
FIELDS = ("local", "target", "class", "bytes", "sha256", "url", "retrieved_utc")


class Report:
    def __init__(self):
        self.failures = []
        self.checks = 0

    def check(self, ok, message):
        self.checks += 1
        if not ok:
            self.failures.append(message)
        return ok

    def done(self, title, quiet=False):
        if not quiet:
            print("%s: %d checks, %d failed" % (title, self.checks, len(self.failures)))
            for f in self.failures:
                print("   FAIL %s" % f)
        return not self.failures


def canonical_digest(entries):
    """Rebuilt here on purpose. Must agree with the fetcher or one of them is wrong."""
    rows = []
    for e in sorted(entries, key=lambda e: e["local"]):
        rows.append("\t".join(str(e[f]) for f in FIELDS))
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def hash_and_size(path):
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        while True:
            block = fh.read(1 << 20)
            if not block:
                break
            n += len(block)
            h.update(block)
    return h.hexdigest(), n


def declared_paths(sources):
    """Every file the source list declares, as the local path the fetcher uses."""
    out = {}
    for target in sources["targets"]:
        for spec in target["files"]:
            local = os.path.join(spec["repo"], spec["path"]).replace("\\", "/")
            out[local] = (target["id"], spec["class"], spec["repo"])
    return out


def verify(manifest, sources, inputs_dir=None, rep=None, census=None):
    rep = rep or Report()
    entries = manifest.get("inputs", [])

    rep.check(manifest.get("schema") == "phaseA-manifest/1",
              "unexpected manifest schema %r" % manifest.get("schema"))
    rep.check(canonical_digest(entries) == manifest.get("manifest_digest"),
              "manifest_digest does not match the entries it covers")

    seen = set()
    for e in entries:
        loc = e.get("local", "?")
        rep.check(all(f in e for f in FIELDS), "%s is missing a field" % loc)
        rep.check(loc not in seen, "%s appears more than once" % loc)
        seen.add(loc)
        rep.check(bool(HEX64.match(str(e.get("sha256", "")))),
                  "%s has a malformed sha256" % loc)
        rep.check(isinstance(e.get("bytes"), int) and e["bytes"] > 0,
                  "%s has a non-positive size" % loc)
        rep.check(bool(STAMP.match(str(e.get("retrieved_utc", "")))),
                  "%s has a malformed retrieval stamp" % loc)
        rep.check(str(e.get("url", "")).startswith("https://"),
                  "%s was not fetched over https" % loc)
        # an input pinned to a branch is not an input, it is a subscription
        commits = [p for p in str(e.get("url", "")).split("/") if HEX40.match(p)]
        rep.check(bool(commits), "%s is not pinned to a commit" % loc)
        repo_key = loc.split("/", 1)[0]
        pinned = manifest.get("repos", {}).get(repo_key, {}).get("commit")
        rep.check(pinned is not None and pinned in commits,
                  "%s url does not carry the commit pinned for %s" % (loc, repo_key))

    want = declared_paths(sources)
    for loc, (tid, cls, _repo) in want.items():
        e = next((x for x in entries if x.get("local") == loc), None)
        if rep.check(e is not None, "%s is declared but not in the manifest" % loc):
            rep.check(e["target"] == tid, "%s is filed under the wrong target" % loc)
            rep.check(e["class"] == cls, "%s has the wrong class" % loc)
    for e in entries:
        rep.check(e.get("local") in want,
                  "%s is in the manifest but not declared" % e.get("local"))

    if inputs_dir:
        for e in entries:
            path = os.path.join(inputs_dir, e["local"])
            if not rep.check(os.path.isfile(path), "%s is missing on disk" % e["local"]):
                continue
            got_hash, got_size = hash_and_size(path)
            rep.check(got_size == e["bytes"],
                      "%s is %d bytes on disk, manifest says %d"
                      % (e["local"], got_size, e["bytes"]))
            rep.check(got_hash == e["sha256"],
                      "%s hashes to %s, manifest says %s"
                      % (e["local"], got_hash[:16], e["sha256"][:16]))
        on_disk = set()
        for root, _dirs, files in os.walk(inputs_dir):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), inputs_dir)
                on_disk.add(rel.replace("\\", "/"))
        for extra in sorted(on_disk - seen):
            rep.check(False, "%s is on disk but not in the manifest" % extra)

    if census is not None:
        by_name = {}
        for e in entries:
            by_name.setdefault(os.path.basename(e["local"]), []).append(e)
        for n in census.get("netlists", []):
            hits = by_name.get(n.get("netlist"), [])
            if rep.check(len(hits) == 1,
                         "the census names %r, which is not one manifest entry"
                         % n.get("netlist")):
                rep.check(hits[0]["sha256"] == n.get("netlist_sha256"),
                          "the census for %s was taken from a different file "
                          "than the manifest records" % n["netlist"])
                rep.check(hits[0]["class"] == "netlist",
                          "%s was censused but is not filed as a netlist"
                          % n["netlist"])

    return rep


# --------------------------------------------------------------------------
# selftest


def selftest():
    """Plant each fault this file exists to catch and confirm it is caught."""
    entry = {
        "local": "r/src/a.v", "target": "t", "class": "netlist", "bytes": 5,
        "sha256": hashlib.sha256(b"hello").hexdigest(),
        "url": "https://raw.githubusercontent.com/o/r/" + "a" * 40 + "/src/a.v",
        "retrieved_utc": "2026-08-16T12:00:00Z",
    }
    sources = {"targets": [{"id": "t", "files": [
        {"repo": "r", "path": "src/a.v", "class": "netlist"}]}]}

    def manifest(entries):
        # copy, or a case that edits m["inputs"][0] in place poisons every case
        # after it and the ones that "pass" are passing for the wrong reason
        entries = [dict(e) for e in entries]
        return {"schema": "phaseA-manifest/1",
                "repos": {"r": {"commit": "a" * 40}},
                "inputs": entries,
                "manifest_digest": canonical_digest(entries)}

    ok = True

    def expect(name, m, src=sources, inputs=None, should_pass=False, census=None):
        nonlocal ok
        clean = not verify(m, src, inputs, Report(), census).failures
        good = clean if should_pass else not clean
        print("  %-58s %s" % (name, "pass" if good else "FAIL"))
        ok = ok and good

    expect("a correct manifest verifies", manifest([entry]), should_pass=True)

    bad = dict(entry, sha256="f" * 64)
    m = manifest([entry]); m["inputs"] = [bad]
    expect("a hash edited after the fact is caught", m)

    m = manifest([entry]); m["inputs"][0]["bytes"] = 6
    expect("a size edited after the fact is caught", m)

    m = manifest([dict(entry, sha256="zz" + "0" * 62)])
    expect("a malformed hash is caught", m)

    m = manifest([dict(entry, bytes=0)])
    expect("a zero-length input is caught", m)

    m = manifest([dict(entry, retrieved_utc="yesterday")])
    expect("a malformed retrieval stamp is caught", m)

    m = manifest([dict(entry, url="https://raw.githubusercontent.com/o/r/main/src/a.v")])
    expect("an input pinned to a branch is caught", m)

    m = manifest([dict(entry, url="https://raw.githubusercontent.com/o/r/"
                                  + "b" * 40 + "/src/a.v")])
    expect("a url on the wrong commit is caught", m)

    m = manifest([entry, dict(entry)])
    expect("a duplicated entry is caught", m)

    expect("a declared file absent from the manifest is caught", manifest([]))

    two = {"targets": [{"id": "t", "files": [
        {"repo": "r", "path": "src/a.v", "class": "netlist"}]}]}
    m = manifest([entry, dict(entry, local="r/src/b.v")])
    expect("an undeclared entry in the manifest is caught", m, src=two)

    m = manifest([dict(entry, **{"class": "layout"})])
    expect("an entry filed under the wrong class is caught", m)

    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "r", "src"))
        p = os.path.join(tmp, "r", "src", "a.v")
        with open(p, "wb") as fh:
            fh.write(b"hello")
        expect("matching bytes on disk verify", manifest([entry]),
               inputs=tmp, should_pass=True)

        with open(p, "wb") as fh:
            fh.write(b"hellp")          # same length, one byte different
        expect("a same-length byte flip on disk is caught", manifest([entry]),
               inputs=tmp)

        with open(p, "wb") as fh:
            fh.write(b"hell")
        expect("a truncated file on disk is caught", manifest([entry]), inputs=tmp)

        with open(p, "wb") as fh:
            fh.write(b"hello")
        with open(os.path.join(tmp, "r", "src", "stray.v"), "wb") as fh:
            fh.write(b"x")
        expect("an undeclared file on disk is caught", manifest([entry]), inputs=tmp)
        os.remove(os.path.join(tmp, "r", "src", "stray.v"))

        os.remove(p)
        expect("a missing file on disk is caught", manifest([entry]), inputs=tmp)

    good_census = {"netlists": [{"netlist": "a.v", "netlist_sha256": entry["sha256"]}]}
    expect("a census taken from the recorded file verifies",
           manifest([entry]), census=good_census, should_pass=True)

    stale = {"netlists": [{"netlist": "a.v", "netlist_sha256": "0" * 64}]}
    expect("a census taken from a different file is caught",
           manifest([entry]), census=stale)

    unknown = {"netlists": [{"netlist": "elsewhere.v", "netlist_sha256": "0" * 64}]}
    expect("a census of a file not in the manifest is caught",
           manifest([entry]), census=unknown)

    print("\nselftest %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", default=os.path.join(HERE, "INPUT_MANIFEST.json"))
    ap.add_argument("--sources", default=os.path.join(HERE, "sources.json"))
    ap.add_argument("--inputs", help="also re-derive size and hash from these files")
    ap.add_argument("--census", default=os.path.join(HERE, "RING_CENSUS.json"),
                    help="cross-check this ring census against the manifest")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    with open(args.manifest) as fh:
        manifest = json.load(fh)
    with open(args.sources) as fh:
        sources = json.load(fh)

    census = None
    if args.census and os.path.isfile(args.census):
        with open(args.census) as fh:
            census = json.load(fh)

    rep = verify(manifest, sources, args.inputs, None, census)
    where = "manifest and bytes" if args.inputs else "manifest only (bytes not present)"
    if census:
        where += ", census cross-checked"
    return 0 if rep.done("Phase A inputs, %s" % where) else 1


if __name__ == "__main__":
    sys.exit(main())
