#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Every hash this repo records has to be of the bytes a checkout produces,
not the bytes on the machine that recorded them.

The two are not the same. `.gitattributes` opens with `* text=auto`, so git
rewrites CRLF to LF on the way into a commit, and a file that is CRLF on a
Windows disk is LF in every checkout of it. Hash the disk copy and the number
recorded is one CI can never reproduce.

Not hypothetical. `dualarm/src/ro_macro_hard.lef` is CRLF here and LF after a
checkout, 1387 bytes against 1325, and `chip/tile_budget.py` hashed the raw
bytes. `TILE_BUDGET.json` has carried the Windows hash since 31 August. The
evidence gate went red on the first push after that and stayed red for five
pushes, and since the gate had only ever been run on this machine and inside
the local clone, which hold the same CRLF file, nothing here disagreed with
anything.

So the question is asked from the other side. This script does not recompute
what a producer computed. It takes every SHA-256 written into a chip artefact
and asks which file that number belongs to, hashing each file three ways: as
it sits on disk, as a checkout would store it, and as it would look if
somebody stripped carriage returns from it without asking whether it was
text. Which of the three matches says what happened.

Checks:

  H01  every recorded hash is of the bytes a checkout produces
  H02  every recorded hash belongs to a file in the tree
  H03  every recorded file's extension is declared in .gitattributes
  H04  every explicit .gitattributes rule agrees with the bytes it covers
  H05  no recorded file sits somewhere .gitignore excludes

H01 carries two faults rather than one. A hash of the disk copy and a hash of
a binary file with its carriage returns stripped are the same property seen
twice, they resolve through different indexes and they want different fixes,
so the check names which of the two it found instead of splitting in half.

What "binary" means here is git's, not mine, and the first version of this
script got it wrong. A NUL in the first 8000 bytes is only half the rule: git
also refuses the conversion on a file carrying a carriage return that no line
feed follows, because stripping CRLF out of something that uses bare CR as a
separator would eat data. `sim/spice/gono/ctrl2.txt` and `par2.txt` are ngspice
logs with 1521 and 1644 bare carriage returns and no NUL at all, so git has
always stored them verbatim. Declaring `*.txt text eol=lf` without noticing
that told git to convert them, which moved two archived evidence blobs, and
`verify_provenance.py` said so. H04 knows both halves now and those two files
carry a `-text` line of their own.

The invariant that lets a producer get away with the heuristic. A producer
hashing a file cannot read .gitattributes, so it applies git's heuristic and
nothing else. That is only correct while no explicit rule contradicts the
heuristic, which is exactly what H04 requires. H03 and H04 together are what
make the short rule inside `sha256_file` the right one.

Scope. `extraction/INPUT_MANIFEST.json` is deliberately out. It pins 25
third-party files under `extraction/inputs/`, gitignored on purpose and never
mirrored, so H02 and H05 would both fire on it for a reason that is not a
fault. `spef_census.py --verify-archive` holds that side.

H05 reads `.gitignore` as plain names and directory names only. Wildcards,
negations and anchored paths are counted and printed rather than silently
treated as harmless, because a pattern this script cannot judge is a gap in
the check and should look like one.

Usage:
    python3 hash_stability.py --selftest
    python3 hash_stability.py
"""

import argparse
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Directory names never walked, all for one reason: CI will not have them, so
# a hash that resolves only in here is a hash CI cannot reproduce. `runs` and
# `inputs` are build output and third-party downloads, `tt` is the vendored
# Tiny Tapeout tooling the clone gitignores, and anything starting with an
# underscore is this machine's audit and staging scratch.
SKIP_DIRS = {".git", "runs", "inputs", "tt", "tt_submission", "node_modules",
             "sim_build"}

HEXHASH = re.compile(r"\b[0-9a-f]{64}\b")

# git reads the first 8000 bytes looking for a NUL before deciding a file is
# binary. Match that rather than inventing a rule.
SNIFF = 8000


def sha256_bytes(blob):
    return hashlib.sha256(blob).hexdigest()


def to_lf(blob):
    return blob.replace(b"\r\n", b"\n")


def looks_binary(blob):
    """git's own reading of the bytes, both halves of it. A NUL in the sniff
    window, or any carriage return with no line feed behind it."""
    if b"\x00" in blob[:SNIFF]:
        return True
    return blob.count(b"\r") != blob.count(b"\r\n")


def checkout_bytes(blob, declared):
    """The bytes a checkout of this file would hold.

    `declared` is "text", "binary", or None for a file .gitattributes has no
    explicit rule for, in which case `* text=auto` decides and the NUL sniff
    is what decides it."""
    if declared == "binary":
        return blob
    if declared is None and looks_binary(blob):
        return blob
    return to_lf(blob)


# --------------------------------------------------------------- attributes

def parse_gitattributes(text):
    """Return [(pattern, kind)] for the explicit rules, kind text or binary.

    `* text=auto` is not a rule in this sense. It says let git guess, and what
    H03 exists for is to stop anything important resting on the guess."""
    rules = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern, attrs = parts[0], parts[1:]
        if pattern == "*" and "text=auto" in attrs:
            continue
        if "binary" in attrs or "-text" in attrs:
            rules.append((pattern, "binary"))
        elif any(a == "text" or a.startswith("text=") for a in attrs):
            rules.append((pattern, "text"))
    return rules


def declared_kind(relpath, rules):
    """Last matching rule wins, which is git's own precedence."""
    base = os.path.basename(relpath)
    kind = None
    for pattern, k in rules:
        if pattern.startswith("*.") and base.endswith(pattern[1:]):
            kind = k
        elif pattern == base:
            kind = k
    return kind


def extension_key(relpath):
    """What H03 names. A file with a suffix is judged by the suffix and one
    without by its own name, because that is how .gitattributes can speak
    about it at all."""
    base = os.path.basename(relpath)
    ext = os.path.splitext(base)[1]
    return ext if ext else base


# ------------------------------------------------------------------ ignores

def parse_gitignore(text):
    """Plain names and directory names only. Everything else goes into the
    second list so the caller can report what it could not judge."""
    plain, skipped = [], []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        if line.startswith("!") or "*" in line or "?" in line or "[" in line:
            skipped.append(line)
            continue
        plain.append(line.strip("/"))
    return plain, skipped


def ignored(relpath, plain):
    segments = relpath.split("/")
    for pat in plain:
        if "/" in pat:
            if relpath == pat or relpath.startswith(pat + "/"):
                return pat
        elif pat in segments:
            return pat
    return None


# -------------------------------------------------------------------- trees

def walk_tree(root):
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in sorted(dirs)
                   if x not in SKIP_DIRS and not x.startswith("_")]
        for f in sorted(files):
            p = os.path.join(d, f)
            if os.path.islink(p):
                continue
            out.append(os.path.relpath(p, root).replace(os.sep, "/"))
    return out


def artefact_paths(root):
    """The files whose recorded hashes this script answers for."""
    out = []
    chip = os.path.join(root, "chip")
    if os.path.isdir(chip):
        for f in sorted(os.listdir(chip)):
            if f.endswith(".json"):
                out.append("chip/" + f)
    frozen = "dualarm/build_2arm_frozen/MANIFEST.txt"
    if os.path.exists(os.path.join(root, frozen)):
        out.append(frozen)
    return out


def collect_recorded(root, artefacts):
    """hash -> set of artefacts that write it.

    Read as text, not as JSON. A hash is a hash wherever in the structure it
    sits, and a reader that walks the schema has to be taught every new shape
    a producer invents."""
    rec = {}
    for rel in artefacts:
        with open(os.path.join(root, rel), "r", encoding="utf-8",
                  errors="replace") as fh:
            text = fh.read()
        for h in HEXHASH.findall(text):
            rec.setdefault(h, set()).add(rel)
    return rec


DECLARE_KEY = "_hashes_not_in_this_tree"


def declared_external(root, artefacts):
    """hash -> (artefact, reason), from each artefact's own declaration.

    Some recorded hashes are of files that are not here and are not meant to
    be. chip/FLOW_SURFACE.json pins five LibreLane source files at two tags,
    which live in another repository, and chip/PLACEMENT_CFG.json records
    the hash of a fallback rendering that is deliberately not committed.
    Without a way to say so, H02 fires on both and the only ways out are to
    stop recording the hashes or to stop running the check.

    The declaration sits in the artefact, under one well known key, beside
    the thing it is about. That is the one piece of schema this script
    knows, against a docstring that otherwise refuses to walk one, and the
    trade is deliberate: the alternative is a table of hash values in here
    that goes stale the moment a producer runs.

    H06 is what stops the key being a hiding place."""
    import json
    out = {}
    for rel in artefacts:
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict):
            continue
        block = doc.get(DECLARE_KEY)
        if not isinstance(block, dict):
            continue
        for h, why in block.items():
            if HEXHASH.fullmatch(h):
                out[h] = (rel, why)
    return out


def index_tree(root, files, rules):
    """relpath -> dict of the three hashes plus what the bytes actually are."""
    idx = {}
    for rel in files:
        try:
            with open(os.path.join(root, rel), "rb") as fh:
                blob = fh.read()
        except OSError:
            continue
        kind = declared_kind(rel, rules)
        idx[rel] = {"raw": sha256_bytes(blob),
                    "checkout": sha256_bytes(checkout_bytes(blob, kind)),
                    "forced_lf": sha256_bytes(to_lf(blob)),
                    "kind": kind,
                    "cr": b"\r" in blob,
                    "binaryish": looks_binary(blob)}
    return idx


# ------------------------------------------------------------------- checks

class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})
        return ok

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


def run_checks(recorded, idx, ignore_plain, artefacts, external=None):
    res = Results()

    by = {"checkout": {}, "raw": {}, "forced_lf": {}}
    for rel, v in idx.items():
        for key in by:
            by[key].setdefault(v[key], []).append(rel)

    external = external or {}
    wrong_bytes, orphan, resolved = [], [], {}
    declared_orphan = []
    for h, where in sorted(recorded.items()):
        src = ",".join(sorted(where))
        if h in by["checkout"]:
            resolved[h] = by["checkout"][h]
        elif h in by["raw"]:
            resolved[h] = by["raw"][h]
            wrong_bytes.append("%s in %s is the disk copy of %s"
                               % (h[:12], src, ", ".join(by["raw"][h])))
        elif h in by["forced_lf"]:
            resolved[h] = by["forced_lf"][h]
            wrong_bytes.append(
                "%s in %s is %s with its carriage returns stripped, and it "
                "is not a text file" % (h[:12], src,
                                        ", ".join(by["forced_lf"][h])))
        elif h in external:
            declared_orphan.append(h)
        else:
            orphan.append("%s in %s" % (h[:12], src))

    named = sorted(set(sum(resolved.values(), [])))

    res.add("H01", "every recorded hash is of the bytes a checkout produces",
            not wrong_bytes,
            "; ".join(wrong_bytes) or "%d hashes over %d files"
            % (len(recorded), len(named)))

    res.add("H02", "every recorded hash belongs to a file in the tree "
                   "or is declared as not being one",
            not orphan,
            "; ".join(orphan) or "%d of %d resolve, %d declared external"
            % (len(resolved), len(recorded), len(declared_orphan)))

    undeclared = sorted(set("%s (%s)" % (extension_key(r), r)
                            for r in named if idx[r]["kind"] is None))
    res.add("H03", "every recorded file's extension is declared in "
                   ".gitattributes", not undeclared,
            ", ".join(undeclared) or
            "%d recorded files, none resting on the guess" % len(named))

    contradicted, covered = [], 0
    for rel, v in sorted(idx.items()):
        if v["kind"] is None:
            continue
        covered += 1
        if v["kind"] == "text" and v["binaryish"]:
            contradicted.append("%s is declared text and git would not "
                                "convert it" % rel)
        elif v["kind"] == "binary" and not v["binaryish"]:
            contradicted.append("%s is declared binary and reads as text"
                                % rel)
    res.add("H04", "every explicit .gitattributes rule agrees with git's own "
                   "reading",
            not contradicted,
            "; ".join(contradicted) or "%d files covered by a rule" % covered)

    excluded = sorted(set("%s (matched %s)" % (r, ignored(r, ignore_plain))
                          for r in named if ignored(r, ignore_plain)))
    hiding = sorted("%s declared in %s is %s"
                    % (h[:12], external[h][0], ", ".join(resolved[h]))
                    for h in external if h in resolved)
    # No second half about a declaration nothing uses: collect_recorded
    # reads the artefact as text, so the declaration block records its own
    # hashes and that check could never fire.
    res.add("H06", "every hash declared as not in this tree is absent from "
                   "it", not hiding,
            "; ".join(hiding) or "%d declared, all absent" % len(external))

    res.add("H05", "no recorded file sits somewhere .gitignore excludes",
            not excluded, "; ".join(excluded) or
            "%d artefacts read" % len(artefacts))

    return res, resolved, named


# ------------------------------------------------------------------ fixture

FIX_ATTR = """* text=auto

*.v text eol=lf
*.lef text eol=lf
*.log text eol=lf
*.gds binary
*.dat binary
lone.log -text
"""

FIX_IGNORE = """# fixture
scratch
"""

# b.lef is CRLF on purpose and its recorded hash is the LF one. It is the
# reason the fixture exists at all: without it a clean run would pass H01
# having never met the case H01 is about.
FIX_A = b"module a;\nendmodule\n"
FIX_B = b"MACRO x\r\n  SIZE 1 BY 2 ;\r\nEND x\r\n"
FIX_G = b"gds\x00\r\nbytes\x00\n"
FIX_D = b"opaque\x00\r\npayload\n"
FIX_I = b"module ignored;\nendmodule\n"
# bare carriage returns and not one NUL, the ngspice shape. Declared -text
# against the *.log rule above, which is what H04 has to accept.
FIX_L = b"step 1\rstep 2\rstep 3\ndone\n"


def write(root, rel, blob):
    path = os.path.join(root, rel.replace("/", os.sep))
    with open(path, "wb") as fh:
        fh.write(blob)


def build_fixture(tmp, drop_lef_rule=False, flip_dat=False, flip_lone=False,
                  record_raw_lef=False, record_forced_gds=False,
                  record_nothing=False, record_ignored=False,
                  declare_missing=False, declare_present=False):
    for sub in ("chip", "keep", "scratch"):
        os.makedirs(os.path.join(tmp, sub), exist_ok=True)

    attr = FIX_ATTR
    if drop_lef_rule:
        attr = attr.replace("*.lef text eol=lf\n", "")
    if flip_dat:
        attr = attr.replace("*.dat binary", "*.dat text eol=lf")
    if flip_lone:
        attr = attr.replace("lone.log -text\n", "")
    write(tmp, ".gitattributes", attr.encode("ascii"))
    write(tmp, ".gitignore", FIX_IGNORE.encode("ascii"))

    write(tmp, "keep/a.v", FIX_A)
    write(tmp, "keep/b.lef", FIX_B)
    write(tmp, "keep/g.gds", FIX_G)
    write(tmp, "keep/c.dat", FIX_D)
    write(tmp, "keep/lone.log", FIX_L)
    write(tmp, "scratch/i.v", FIX_I)

    rec = {"a": sha256_bytes(FIX_A),
           "b": sha256_bytes(to_lf(FIX_B)),
           "g": sha256_bytes(FIX_G)}
    if record_raw_lef:
        rec["b"] = sha256_bytes(FIX_B)
    if record_forced_gds:
        rec["g"] = sha256_bytes(to_lf(FIX_G))
    if record_nothing:
        rec["x"] = "f" * 64
    if record_ignored:
        rec["i"] = sha256_bytes(FIX_I)

    declare = {}
    if declare_missing:
        declare["f" * 64] = "not here on purpose"
    if declare_present:
        declare[sha256_bytes(FIX_A)] = "claims a.v is somewhere else"

    body = "".join('  "%s": "%s",\n' % (k, v) for k, v in sorted(rec.items()))
    if declare:
        inner = "".join('    "%s": "%s",\n' % (k, v)
                        for k, v in sorted(declare.items()))
        body += ('  "%s": {\n' % DECLARE_KEY) + inner.rstrip(",\n") + "\n  },\n"
    write(tmp, "chip/FIXTURE.json",
          ("{\n" + body.rstrip(",\n") + "\n}\n").encode("ascii"))
    return rec


def run_fixture(tmp, **kwargs):
    build_fixture(tmp, **kwargs)
    with open(os.path.join(tmp, ".gitattributes"), encoding="utf-8") as fh:
        rules = parse_gitattributes(fh.read())
    with open(os.path.join(tmp, ".gitignore"), encoding="utf-8") as fh:
        plain = parse_gitignore(fh.read())[0]
    arte = artefact_paths(tmp)
    idx = index_tree(tmp, walk_tree(tmp), rules)
    return run_checks(collect_recorded(tmp, arte), idx, plain, arte,
                      declared_external(tmp, arte))[0]


FAULTS = (
    ("H01", "a hash taken from the CRLF copy on disk",
     dict(record_raw_lef=True)),
    ("H01", "a binary file hashed with its carriage returns stripped",
     dict(record_forced_gds=True)),
    ("H02", "a recorded hash belonging to no file",
     dict(record_nothing=True)),
    ("H03", "a recorded file whose extension .gitattributes says nothing "
            "about", dict(drop_lef_rule=True)),
    ("H04", "a rule calling a file with a NUL in it text",
     dict(flip_dat=True)),
    ("H04", "a rule calling a bare-carriage-return log text",
     dict(flip_lone=True)),
    ("H05", "a hash recorded for a file inside an ignored directory",
     dict(record_ignored=True)),
    ("H06", "a declaration that a file which is here is somewhere else",
     dict(declare_present=True)),
)


def selftest():
    import shutil
    import tempfile
    ok = True
    print("hash_stability selftest")
    tmp = tempfile.mkdtemp(prefix="hsfix")
    try:
        res = run_fixture(tmp)
        if res.failed():
            print("  FAIL: clean fixture fails %s" % ", ".join(res.failed()))
            for r in res.rows:
                if not r["pass"]:
                    print("        %s %s" % (r["id"], r["detail"]))
            ok = False
        else:
            print("  clean fixture passes all %d checks, one CRLF file among "
                  "them" % len(res.rows))

        for want, label, kwargs in FAULTS:
            shutil.rmtree(tmp)
            os.makedirs(tmp)
            tripped = set(run_fixture(tmp, **kwargs).failed())
            if tripped == {want}:
                print("  ok    %-4s %s" % (want, label))
            elif want in tripped:
                print("  FAIL  %-4s %s -- also tripped %s"
                      % (want, label, ", ".join(sorted(tripped - {want}))))
                ok = False
            else:
                print("  FAIL  %-4s %s -- tripped %s"
                      % (want, label,
                         ", ".join(sorted(tripped)) or "nothing"))
                ok = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n  %s" % ("all %d faults isolated" % len(FAULTS) if ok
                      else "SELFTEST FAILED"))
    return 0 if ok else 1


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--root", default=ROOT)
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    root = os.path.abspath(a.root)
    attrs = os.path.join(root, ".gitattributes")
    if not os.path.exists(attrs):
        raise SystemExit("missing .gitattributes: %s" % attrs)
    with open(attrs, encoding="utf-8") as fh:
        rules = parse_gitattributes(fh.read())

    plain, skipped = [], []
    ig = os.path.join(root, ".gitignore")
    if os.path.exists(ig):
        with open(ig, encoding="utf-8") as fh:
            plain, skipped = parse_gitignore(fh.read())

    artefacts = artefact_paths(root)
    if not artefacts:
        raise SystemExit("no chip artefacts found under %s" % root)
    recorded = collect_recorded(root, artefacts)
    if not recorded:
        raise SystemExit("no hashes recorded in %d artefacts"
                         % len(artefacts))

    idx = index_tree(root, walk_tree(root), rules)
    res, resolved, named = run_checks(recorded, idx, plain, artefacts,
                                      declared_external(root, artefacts))

    print("Hash stability for %s" % os.path.basename(root))
    print("  %d artefacts, %d distinct hashes, %d files walked"
          % (len(artefacts), len(recorded), len(idx)))
    crlf = [r for r, v in idx.items() if v["cr"] and not v["binaryish"]]
    print("  %d text files carry a carriage return on this disk, %d of them "
          "recorded" % (len(crlf), len([r for r in named if idx[r]["cr"]
                                        and not idx[r]["binaryish"]])))
    for rel in named:
        v = idx[rel]
        mark = "CRLF" if v["cr"] and not v["binaryish"] else "    "
        print("    %-4s %-9s %s" % (mark, v["kind"] or "guessed", rel))
    if skipped:
        print("  %d .gitignore patterns not judged here: %s"
              % (len(skipped), ", ".join(skipped)))
    print()
    for r in res.rows:
        print("  %-4s %-62s %s" % (r["id"], r["name"],
                                   "pass" if r["pass"] else "FAIL"))
    bad = res.failed()
    print("\n  %s" % ("all %d checks pass" % len(res.rows) if not bad
                      else "FAILED: " + ", ".join(bad)))
    for r in res.rows:
        if r["detail"]:
            print("       %s: %s" % (r["id"], r["detail"]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
