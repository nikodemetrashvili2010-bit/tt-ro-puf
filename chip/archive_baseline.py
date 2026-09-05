#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""G.3 step 1: freeze the two-arm build before anything overwrites it.

Step 2 copies the generated three-arm modules over `dualarm/src/`. That is
the one irreversible edit in the runbook, and after it the two-arm design
exists nowhere on disk. Everything Phase E measured, the whole two-arm
result the paper quotes, was read off files that are about to be replaced.
So they get copied somewhere first, and the copy gets a manifest.

The archive is not only insurance. `chip/gen_e2_rtl.py` transforms the live
`dualarm/src/` and its checks need the untransformed design to run their
control against. Once the install has happened the live tree is the
transformed design and that control has nothing to compare with. Pointing
the generator at this archive instead keeps its sixteen checks, its control
and its planted faults working after the install, and turns the gate's
diff into a stronger statement than the one it made before: what is
installed in `dualarm/src/` is exactly what transforming the frozen
two-arm design produces. See docs/phaseG_g3_steps1to6.md.

What it checks:

  A01  every raw build input the release manifest hashes is on disk
  A02  every one of them still hashes to what the manifest recorded
  A03  every source file the runbook's archive step names is in the archive
  A04  every archived copy still hashes to what MANIFEST.txt records
  A05  no hash appears outside the manifest's two tables
  A06  no archived file is empty
  A07  the archive holds nothing the archive step did not name
  A08  the manifest names the build it froze, by the DEF hash
  A09  the frozen top level is the two-arm design, not something later
  A10  the manifest states the drift between the two source trees
  A11  no archived copy carries a carriage return

There is no date line in MANIFEST.txt on purpose. The gate regenerates the
file and diffs it against the committed copy, so every line has to be
derivable from what is in the archive, and a date is not. Git holds the
date. RELEASE_MANIFEST.json recorded its own hash and disagreed with itself on
every run, which cost a day on 31 August. A05 is the guard against that
shape. Every hash this file is entitled to carry sits in one of its two
tables, so a hash anywhere else belongs to nothing, which is what a file
recording its own sum looks like from the outside.

Usage:
    python3 archive_baseline.py --selftest
    python3 archive_baseline.py --freeze
    python3 archive_baseline.py --manifest /tmp/frozen_manifest.txt
    python3 archive_baseline.py
"""

import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DESIGN = "tt_um_nikodemetrashvili20_ro_puf"
ARCHIVE = os.path.join("dualarm", "build_2arm_frozen")
MANIFEST = "MANIFEST.txt"
RELEASE = os.path.join(HERE, "RELEASE_MANIFEST.json")
RUNBOOK = os.path.join(HERE, "G3_RUNBOOK.json")

# The raw build files, keyed the way RELEASE_MANIFEST.json keys them. Two of
# its ten keys are not build outputs and are not looked for here: macro_lef
# is Arm B's hardened macro, which is an input to the build rather than a
# product of it, and cost is chip/ARMC_COST.json, which is an artefact of
# Phase E. The runbook says the same thing in raw_carried_forward.
RAW_PATHS = {
    "def": "dualarm/build_current/%s.def" % DESIGN,
    "netlist": "dualarm/build_current/%s.nl.v" % DESIGN,
    "spef": "dualarm/build_current/%s.nom.spef" % DESIGN,
    "metrics": "dualarm/build_current/metrics.json",
    "positions": "dualarm/build_current/dualarm_positions.csv",
    "dualarm_par_out.txt": "dualarm/build_current/dualarm_par_out.txt",
    "dualarm_par_ss_out.txt": "dualarm/build_current/dualarm_par_ss_out.txt",
    "dualarm_par_ff_out.txt": "dualarm/build_current/dualarm_par_ff_out.txt",
}

# The two source trees. dualarm/src is the one the build reads and the one
# backup_to_repo.sh mirrors to the clone's src/. The top-level src/ in the
# working tree is read by nothing in that chain and has been the June
# single-arm design since dual-arm v2 landed on 22 July. Both are archived,
# because "the two disagreed and here is by how much" is a fact about this
# repository that is worth keeping, and because step 2 resyncs the second
# from the first and the drift stops being visible afterwards.
DUALARM_SRC = ("ro_puf.v", "ro_puf_core.v", "tt_um_ro_puf.v", "ro_macro.v",
               "config.json")
TOP_SRC = DUALARM_SRC

# Where gen_e2_rtl.py looks for its untransformed inputs after the install.
TRANSFORM_INPUTS = ("ro_puf_core.v", "ro_puf.v", "tt_um_ro_puf.v",
                    "ro_macro.v", "config.json")


def sha256_bytes(blob):
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path):
    """The bytes a checkout produces, not the bytes on this disk.

    `.gitattributes` opens with `* text=auto`, so git stores a text file
    with LF endings whatever the machine that wrote it used. Hash the raw
    bytes of a CRLF file and the number recorded is one CI can never
    reproduce. That is what put TILE_BUDGET.json's macro_lef entry wrong
    on 31 August and held the evidence gate red for five pushes.

    The test below is git's own and both halves of it matter: a NUL in
    the first 8000 bytes, or a carriage return with no line feed behind
    it, and git leaves the file alone. It reads no attributes, which is
    safe only while no explicit rule contradicts the heuristic, and that
    is what chip/hash_stability.py H03 and H04 are there to require."""
    with open(path, "rb") as fh:
        blob = fh.read()
    if b"\x00" in blob[:8000] or blob.count(b"\r") != blob.count(b"\r\n"):
        return sha256_bytes(blob)
    return sha256_bytes(blob.replace(b"\r\n", b"\n"))


class Results(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail=""):
        self.rows.append({"id": cid, "name": name, "pass": bool(ok),
                          "detail": detail})
        return ok

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


# ------------------------------------------------------------ the archive

def plan():
    """archive name -> the path in the working tree it is a copy of.

    Flat two-directory layout on purpose. Nesting the real paths would put a
    second `dualarm/` inside `dualarm/`, and the point of the archive is that
    a reader can tell at a glance which of the two source trees a file came
    from.
    """
    rows = []
    for name in DUALARM_SRC:
        rows.append(("dualarm_src/" + name, "dualarm/src/" + name))
    for name in TOP_SRC:
        rows.append(("top_src/" + name, "src/" + name))
    rows.append(("dualarm_info.yaml", "dualarm/info.yaml"))
    rows.append(("top_info.yaml", "info.yaml"))
    return dict(rows)


def runbook_archives():
    """The paths G3_RUNBOOK.json's archive step says have to be kept."""
    with open(RUNBOOK, "r", encoding="utf-8") as fh:
        book = json.load(fh)
    for step in book["steps"]:
        if step.get("archives"):
            return list(step["archives"])
    return []


def recorded_raw():
    """raw_inputs out of RELEASE_MANIFEST.json, narrowed to build outputs."""
    with open(RELEASE, "r", encoding="utf-8") as fh:
        rel = json.load(fh)
    raw = rel.get("raw_inputs", {})
    return dict((k, v) for k, v in raw.items() if k in RAW_PATHS)


def read_archive(root=None):
    """Every file in the archive except the manifest, as name -> bytes."""
    base = os.path.join(root or ROOT, ARCHIVE)
    out = {}
    if not os.path.isdir(base):
        return out
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            name = os.path.relpath(full, base).replace(os.sep, "/")
            if name == MANIFEST:
                continue
            with open(full, "rb") as fh:
                out[name] = fh.read()
    return out


# ----------------------------------------------------------- the manifest

HEADER = [
    "two-arm baseline, frozen before G.3 step 2 replaced dualarm/src",
    "",
    "The design as it stood when Phase E measured it and when the E.2",
    "transformation was written against it. chip/gen_e2_rtl.py reads",
    "dualarm_src/ from here once the install has happened, so this archive",
    "is a live input to the evidence gate and not only a safety copy.",
    "",
    "No date line. The gate regenerates this file and diffs it against the",
    "committed copy, so every line has to be derivable from the archive and",
    "a date is not. Git holds the date.",
    "",
    "Copies are stored with LF endings. Four of the twelve originals are",
    "CRLF on disk and .gitattributes rewrites them on commit, so a copy kept",
    "byte for byte would hash one way here and another way in a checkout,",
    "and every hash below would be wrong in CI and right on this machine.",
    "",
]


def render(files, raw, origins):
    """The manifest text. Everything in it comes from committed bytes."""
    lines = list(HEADER)
    lines.append("build frozen, hashes as RELEASE_MANIFEST.json recorded them")
    for key in sorted(raw):
        lines.append("  %-24s %s" % (key, raw[key]))
    lines.append("")
    lines.append("archived files, %d of them" % len(files))
    for name in sorted(files):
        blob = files[name]
        lines.append("  %-26s %-26s %s %7d"
                     % (name, origins.get(name, "?"), sha256_bytes(blob),
                        len(blob)))
    lines.append("")
    lines.append("the two source trees")
    same, differ = tree_drift(files)
    lines.append("  %d files held in both, %d differ" % (same + differ, differ))
    if differ:
        lines.append("  src/ is the June single-arm design and has been since")
        lines.append("  dual-arm v2 landed in dualarm/src on 22 July")
    lines.append("")
    return "\n".join(lines)


def tree_drift(files):
    """How many of the paired source files agree, and how many do not."""
    same = differ = 0
    for name in sorted(files):
        if not name.startswith("dualarm_src/"):
            continue
        twin = "top_src/" + name.split("/", 1)[1]
        if twin not in files:
            continue
        if files[name] == files[twin]:
            same += 1
        else:
            differ += 1
    for a, b in (("dualarm_info.yaml", "top_info.yaml"),):
        if a in files and b in files:
            if files[a] == files[b]:
                same += 1
            else:
                differ += 1
    return same, differ


def split_sections(text):
    """The manifest's two tables and everything that is not in them.

    A05 wants the third of those. Every hash the file is entitled to carry
    sits in one of the two tables, so a hash anywhere else is a hash that
    belongs to nothing, which is what a file recording its own sum looks
    like from the outside.
    """
    raw_rows, file_rows, other = [], [], []
    mode = None
    for line in text.split("\n"):
        if line.startswith("build frozen"):
            mode, _ = "raw", other.append(line)
            continue
        if line.startswith("archived files"):
            mode, _ = "files", other.append(line)
            continue
        if mode and line.startswith("  "):
            (raw_rows if mode == "raw" else file_rows).append(line)
            continue
        mode = None
        other.append(line)
    return raw_rows, file_rows, other


def manifest_hashes(text):
    """name -> (sha256, size) parsed back out of the manifest text."""
    out = {}
    for line in split_sections(text)[1]:
        parts = line.split()
        if len(parts) == 4:
            out[parts[0]] = (parts[2], int(parts[3]))
    return out


# ------------------------------------------------------------- the checks

def run_checks(files, text, raw_recorded, raw_disk, runbook_list, origins):
    res = Results()

    missing_raw = sorted(k for k in raw_recorded if k not in raw_disk)
    res.add("A01", "every raw build input the release manifest hashes is on "
                   "disk", not missing_raw,
            ", ".join(missing_raw) or "%d inputs" % len(raw_recorded))

    moved = sorted(k for k, h in raw_disk.items()
                   if k in raw_recorded and h != raw_recorded[k])
    res.add("A02", "every raw build input still hashes to what was recorded",
            not moved, ", ".join(moved) or "none moved")

    kept = set(origins.get(n) for n in files)
    unarchived = sorted(p for p in runbook_list if p not in kept)
    res.add("A03", "every source file the archive step names is in the "
                   "archive", not unarchived,
            ", ".join(unarchived) or "%d paths" % len(runbook_list))

    recorded = manifest_hashes(text)
    bad = []
    for name in sorted(set(files) | set(recorded)):
        want = recorded.get(name)
        if name not in files:
            bad.append(name + " (recorded, absent)")
        elif want is None:
            bad.append(name + " (present, unrecorded)")
        elif want != (sha256_bytes(files[name]), len(files[name])):
            bad.append(name)
    res.add("A04", "every archived copy still hashes to what the manifest "
                   "records", not bad,
            ", ".join(bad) or "%d files" % len(files))

    raw_rows, file_rows, other = split_sections(text)
    loose = re.findall(r"\b[0-9a-f]{64}\b", "\n".join(other))
    res.add("A05", "no hash appears outside the manifest's two tables",
            not loose,
            ", ".join(h[:16] + ".." for h in loose) or
            "%d raw rows, %d file rows" % (len(raw_rows), len(file_rows)))

    empty = sorted(n for n, b in files.items() if not b)
    res.add("A06", "no archived file is empty", not empty,
            ", ".join(empty) or "none")

    stray = sorted(n for n in files if n not in origins)
    res.add("A07", "the archive holds nothing the archive step did not name",
            not stray, ", ".join(stray) or "none")

    want_def = raw_recorded.get("def", "")
    res.add("A08", "the manifest names the build it froze, by the DEF hash",
            bool(want_def) and want_def in text,
            want_def[:16] + ".." if want_def else "no def hash recorded")

    top = files.get("dualarm_src/tt_um_ro_puf.v", b"").decode(
        "utf-8", "replace")
    core = files.get("dualarm_src/ro_puf_core.v", b"").decode(
        "utf-8", "replace")
    two_arm = ("WINDOW = 16'd1000" in top and "g_armc" not in top
               and "g_armc" not in core)
    res.add("A09", "the frozen design is the two-arm one, not something "
                   "later", two_arm,
            "fixed 1000-cycle window, no Arm C bank" if two_arm
            else "this archive is not the pre-install design")

    same, differ = tree_drift(files)
    claim = "  %d files held in both, %d differ" % (same + differ, differ)
    res.add("A10", "the manifest states the drift between the two source "
                   "trees", claim in text.split("\n"),
            "%d of %d differ" % (differ, same + differ))

    crlf = sorted(n for n, b in files.items() if b"\r" in b)
    res.add("A11", "no archived copy carries a carriage return", not crlf,
            ", ".join(crlf) or "%d files, all LF" % len(files))

    return res


# ------------------------------------------------------------- the fixture

def fixture(mutate_files=None, mutate_text=None):
    origins = plan()
    files = {}
    for name, origin in sorted(origins.items()):
        body = "// %s\n" % origin
        if name == "dualarm_src/tt_um_ro_puf.v":
            body += "    localparam [15:0] WINDOW = 16'd1000;\n"
        elif name.startswith("top_src/"):
            body += "// June single-arm\n"
        files[name] = body.encode("utf-8")
    raw_recorded = dict((k, sha256_bytes(k.encode("utf-8")))
                        for k in RAW_PATHS)
    raw_disk = dict(raw_recorded)
    runbook_list = sorted(origins.values())
    if mutate_files:
        mutate_files(files, raw_recorded, raw_disk, runbook_list, origins)
    text = render(files, raw_recorded, origins)
    if mutate_text:
        text = mutate_text(text, files, raw_recorded)
    return files, text, raw_recorded, raw_disk, runbook_list, origins


def run_fixture(mutate_files=None, mutate_text=None):
    args = fixture(mutate_files, mutate_text)
    return run_checks(*args)


def selftest():
    print("archive_baseline selftest")
    ok = True
    res = run_fixture()
    if res.failed():
        print("  FAIL: the clean fixture fails %s" % ", ".join(res.failed()))
        for r in res.rows:
            if not r["pass"]:
                print("        %s %s" % (r["id"], r["detail"]))
        ok = False
    else:
        print("  clean fixture passes all %d checks" % len(res.rows))

    def f_a01(files, recorded, disk, book, origins):
        disk.pop("spef", None)

    def f_a02(files, recorded, disk, book, origins):
        disk["metrics"] = "0" * 64

    def f_a03(files, recorded, disk, book, origins):
        files.pop("top_src/ro_macro.v", None)

    def f_a06(files, recorded, disk, book, origins):
        files["dualarm_src/config.json"] = b""

    def f_a07(files, recorded, disk, book, origins):
        files["dualarm_src/scratch.v"] = b"// left behind\n"

    def f_a09(files, recorded, disk, book, origins):
        files["dualarm_src/ro_puf_core.v"] += b"  begin : g_armc\n"

    def f_a11(files, recorded, disk, book, origins):
        files["dualarm_src/ro_puf.v"] = files[
            "dualarm_src/ro_puf.v"].replace(b"\n", b"\r\n")

    def f_a04(text, files, recorded):
        files["dualarm_src/ro_macro.v"] += b"// edited after the manifest\n"
        return text

    def f_a05(text, files, recorded):
        return text + "sha256 " + sha256_bytes(text.encode("utf-8")) + "\n"

    def f_a08(text, files, recorded):
        return text.replace(recorded["def"], "f" * 64)

    def f_a10(text, files, recorded):
        out = []
        for line in text.split("\n"):
            if line.startswith("  ") and line.endswith(" differ"):
                line = line.replace(" differ", "1 differ")
            out.append(line)
        return "\n".join(out)

    faults = [
        ("A01", "a raw build input that is not on disk", f_a01, None),
        ("A02", "a raw build input edited since the manifest", f_a02, None),
        ("A03", "a file the archive step names and the archive lacks",
         f_a03, None),
        ("A04", "an archived file edited after the manifest was written",
         None, f_a04),
        ("A05", "a manifest carrying its own hash", None, f_a05),
        ("A06", "an archived file copied as zero bytes", f_a06, None),
        ("A07", "a file in the archive that nothing put there", f_a07, None),
        ("A08", "a manifest that does not name the build", None, f_a08),
        ("A09", "an archive taken after the three-arm install", f_a09, None),
        ("A10", "a manifest whose drift line is not what the files say",
         None, f_a10),
        ("A11", "a copy kept with the endings it had on Windows",
         f_a11, None),
    ]
    for cid, what, mf, mt in faults:
        got = run_fixture(mf, mt).failed()
        if got == [cid]:
            print("  ok    %s  %s" % (cid, what))
        else:
            print("  FAIL  %s  %s -> fired %s"
                  % (cid, what, ", ".join(got) or "nothing"))
            ok = False

    print("  %s" % ("all checks isolated" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# ---------------------------------------------------------------- the work

def gather(root=None):
    base = root or ROOT
    origins = plan()
    files = read_archive(base)
    raw_recorded = recorded_raw()
    raw_disk = {}
    for key, rel in sorted(RAW_PATHS.items()):
        path = os.path.join(base, rel.replace("/", os.sep))
        if os.path.exists(path):
            raw_disk[key] = sha256_file(path)
    book = runbook_archives()
    return files, raw_recorded, raw_disk, book, origins


def freeze(root=None):
    """Copy the sources in. Refuses to overwrite an archive that exists."""
    base = root or ROOT
    dest = os.path.join(base, ARCHIVE)
    if os.path.isdir(dest) and os.listdir(dest):
        raise SystemExit(
            "%s already holds an archive. The two-arm design is frozen once, "
            "before step 2. Delete it by hand if you really mean to redo it."
            % ARCHIVE)
    origins = plan()
    for name, origin in sorted(origins.items()):
        src = os.path.join(base, origin.replace("/", os.sep))
        if not os.path.exists(src):
            raise SystemExit("missing source: %s" % origin)
        out = os.path.join(dest, name.replace("/", os.sep))
        d = os.path.dirname(out)
        if not os.path.isdir(d):
            os.makedirs(d)
        with open(src, "rb") as fh:
            blob = fh.read()
        with open(out, "wb") as fh:
            fh.write(blob.replace(b"\r\n", b"\n"))
    files = read_archive(base)
    text = render(files, recorded_raw(), origins)
    with open(os.path.join(dest, MANIFEST), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(text)
    print("froze %d files into %s" % (len(files), ARCHIVE))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--freeze", action="store_true",
                    help="copy the sources in and write the manifest")
    ap.add_argument("--manifest", metavar="PATH",
                    help="rebuild the manifest text from the archive")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.freeze:
        return freeze()

    files, raw_recorded, raw_disk, book, origins = gather()
    if not files:
        print("no archive at %s. Run --freeze first." % ARCHIVE)
        return 2

    if a.manifest:
        text = render(files, raw_recorded, origins)
        with open(a.manifest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        return 0

    path = os.path.join(ROOT, ARCHIVE, MANIFEST)
    if not os.path.exists(path):
        print("no %s in %s" % (MANIFEST, ARCHIVE))
        return 2
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    res = run_checks(files, text, raw_recorded, raw_disk, book, origins)
    same, differ = tree_drift(files)
    print("two-arm baseline, frozen in %s" % ARCHIVE)
    print("  %d files, %d raw build inputs re-hashed, %d of %d paired "
          "sources differ" % (len(files), len(raw_disk), differ, same + differ))
    print("")
    for r in res.rows:
        print("  %s  %-58s %s"
              % (r["id"], r["name"], "pass" if r["pass"] else "FAIL"))
        if r["detail"]:
            print("       %s" % r["detail"])
    bad = res.failed()
    print("")
    print("  %s" % ("all %d checks pass" % len(res.rows) if not bad
                    else "FAILED: " + ", ".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
