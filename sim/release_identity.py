#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""Is the layout this build made the one that was analysed.

Every prediction in this project was read off one layout, run 83's, archived
in dualarm/build_armc. The chip Tiny Tapeout makes is whatever GDS the last
green build produced when the project is submitted, and every push builds
again. Nothing before 23 September checked that the two are the same layout.
Run 83 and every build since use the same action tag, the same LibreLane
(3.0.14) and the same pinned OpenROAD, and only info.yaml's wording has
changed in what the build reads, so they should be; this says whether they
are.

Four files are compared. The GDS after zeroing the two dates in every BGNLIB
and BGNSTR record, which are the time the file was written and differ on
every run. The DEF byte for byte, and if it differs, how many components
moved and how many nets were routed differently. The netlist byte for byte.
The SPEF with its *DATE line dropped. Line endings are normalised first.

The first run in CI, run 88 on 24 September, found the DEF, netlist and SPEF
identical to run 83's and the GDS not. A GDS whose bytes differ can still be
the same layout written out in another order, so when the bytes differ the
GDS is compared again structure by structure, with the shapes inside each
structure compared as a set. The same set everywhere is the same layout,
and is reported as identical with the reason. Anything else names the
structures that differ.

  python3 sim/release_identity.py --run-dir runs/wokwi \
      --against dualarm/build_armc --annotate [--strict]
  python3 sim/release_identity.py --selftest

Without --strict a difference is a warning annotation and the exit is 0; a
file that cannot be found is always an error, because a comparison that
found nothing to compare has not passed.
"""

import argparse
import glob
import hashlib
import os
import re
import struct
import sys

TOP = "tt_um_nikodemetrashvili20_ro_puf"
DATED = {(0x01, 0x02), (0x05, 0x02)}   # BGNLIB, BGNSTR


def gds_normalised(blob):
    """The stream with every BGNLIB and BGNSTR date zeroed."""
    out = bytearray()
    i = 0
    while i + 4 <= len(blob):
        n = struct.unpack(">H", blob[i:i + 2])[0]
        if n < 4 or i + n > len(blob):
            raise ValueError("GDS record at byte %d has length %d" % (i, n))
        rec = bytearray(blob[i:i + n])
        if (rec[2], rec[3]) in DATED:
            rec[4:] = bytes(n - 4)
        out += rec
        i += n
        if (rec[2], rec[3]) == (0x04, 0x00):   # ENDLIB
            break
    return bytes(out)


def text(blob):
    return blob.replace(b"\r\n", b"\n").decode("utf-8", errors="replace")


def def_sections(t):
    """{section: {record name: record text}} for COMPONENTS, NETS and
    SPECIALNETS, plus everything else as one string."""
    secs, rest = {}, t
    for sec in ("COMPONENTS", "SPECIALNETS", "NETS"):
        m = re.search(r"^%s \d+ ;\n(.*?)^END %s" % (sec, sec), rest,
                      re.S | re.M)
        if not m:
            continue
        recs = {}
        for rec in re.split(r"\n(?=\s*- )", m.group(1)):
            rec = rec.strip()
            if rec.startswith("- "):
                recs[rec.split()[1]] = " ".join(rec.split())
        secs[sec] = recs
        rest = rest[:m.start()] + rest[m.end():]
    secs["_rest"] = rest
    return secs


def compare_def(a, b):
    """'' when equal, otherwise what moved."""
    if a == b:
        return ""
    sa, sb = def_sections(a), def_sections(b)
    parts = []
    for sec, word in (("COMPONENTS", "components moved or changed"),
                      ("NETS", "nets routed differently"),
                      ("SPECIALNETS", "power nets changed")):
        ra, rb = sa.get(sec, {}), sb.get(sec, {})
        diff = sum(1 for k in set(ra) | set(rb) if ra.get(k) != rb.get(k))
        if diff:
            parts.append("%d %s" % (diff, word))
    if sa["_rest"] != sb["_rest"]:
        parts.append("header, rows, pins or vias differ")
    return "; ".join(parts) or "differs"


def pick(pattern, want_suffix=""):
    hits = sorted(p for p in glob.glob(pattern) if p.endswith(want_suffix))
    return hits[0] if len(hits) == 1 else None, hits


def compare(run_dir, against):
    """[(file kind, verdict, detail)], verdict identical/differs/missing."""
    fresh = {
        "gds": pick(os.path.join(run_dir, "final", "gds", "*.gds")),
        "def": pick(os.path.join(run_dir, "final", "def", "*.def")),
        "netlist": pick(os.path.join(run_dir, "final", "nl", "*.nl.v")),
        "spef": pick(os.path.join(run_dir, "final", "spef", "*", "*.spef"),
                     ".nom.spef"),
    }
    archived = {
        "gds": os.path.join(against, TOP + ".gds"),
        "def": os.path.join(against, TOP + ".def"),
        "netlist": os.path.join(against, TOP + ".nl.v"),
        "spef": os.path.join(against, TOP + ".nom.spef"),
    }
    out = []
    for kind in ("gds", "def", "netlist", "spef"):
        path, hits = fresh[kind]
        if path is None:
            out.append((kind, "missing", "found %d candidates in %s"
                        % (len(hits), run_dir)))
            continue
        if not os.path.isfile(archived[kind]):
            out.append((kind, "missing", "no archived " + archived[kind]))
            continue
        new, old = open(path, "rb").read(), open(archived[kind], "rb").read()
        if kind == "gds":
            a, b = gds_normalised(new), gds_normalised(old)
            same, detail = a == b, ""
            if not same:
                same, detail = compare_gds(a, b)
                detail += "; sha256 %s against %s" % (
                    hashlib.sha256(a).hexdigest()[:12],
                    hashlib.sha256(b).hexdigest()[:12])
        elif kind == "def":
            detail = compare_def(text(new), text(old))
            same = not detail
        elif kind == "spef":
            strip = lambda t: re.sub(r"^\*DATE .*\n", "", t, flags=re.M)
            same = strip(text(new)) == strip(text(old))
            detail = "" if same else "parasitics differ"
        else:
            same = text(new) == text(old)
            detail = "" if same else "netlist differs"
        out.append((kind, "identical" if same else "differs", detail))
    return out


ELEMENTS = {0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x15, 0x2D}  # BOUNDARY to BOX


def gds_contents(blob):
    """{structure name: its elements sorted}, from a normalised stream.

    Each element is the bytes of its records from the opening one to ENDEL.
    Sorting them, and keying the structures by name, throws away the order a
    writer put things out in and nothing else. The header records go in
    under an empty name, so a change of units is still a difference."""
    out, head, elems, cur, name = {}, [], [], None, None
    i = 0
    while i + 4 <= len(blob):
        n = struct.unpack(">H", blob[i:i + 2])[0]
        rt, rec = blob[i + 2], blob[i:i + n]
        i += n
        if cur is not None:
            cur.append(rec)
            if rt == 0x11:                       # ENDEL
                elems.append(b"".join(cur))
                cur = None
        elif rt in ELEMENTS:
            cur = [rec]
        elif rt == 0x06:                         # STRNAME
            name = rec[4:].rstrip(b"\x00").decode("latin1")
        elif rt == 0x07:                         # ENDSTR
            out[name] = sorted(elems)
            elems, name = [], None
        elif name is None and rt != 0x05:        # header, not BGNSTR
            head.append(rec)
    out[""] = head
    return out


def compare_gds(new, old):
    """(same layout, detail) for two normalised streams whose bytes
    differ."""
    sa, sb = gds_contents(new), gds_contents(old)
    only_new = sorted(set(sa) - set(sb))
    only_old = sorted(set(sb) - set(sa))
    changed = sorted(k for k in set(sa) & set(sb) if sa[k] != sb[k])
    if not (only_new or only_old or changed):
        return True, ("same %d structures and shapes, written in another "
                      "order" % (len(sa) - 1))
    parts = []
    for what, names in (("only in this build", only_new),
                        ("only in the archive", only_old),
                        ("with different shapes", changed)):
        if names:
            shown = ", ".join(k or "(header)" for k in names[:4])
            more = " and %d more" % (len(names) - 4) if len(names) > 4 else ""
            parts.append("%d structures %s: %s%s"
                         % (len(names), what, shown, more))
    return False, "; ".join(parts)


def report(rows, annotate):
    bad = [r for r in rows if r[1] != "identical"]
    for kind, verdict, detail in rows:
        print("  %-8s %s%s" % (kind, verdict,
                               (": " + detail) if detail else ""))
    if annotate:
        if not bad:
            why = "; ".join("%s %s" % (r[0], r[2]) for r in rows if r[2])
            print("::notice title=release layout::this build's GDS, DEF, "
                  "netlist and SPEF are the analysed run 83 layout%s"
                  % ((" (" + why + ")") if why else ""))
        else:
            missing = any(r[1] == "missing" for r in bad)
            level = "error" if missing else "warning"
            print("::%s title=release layout::not the analysed layout: %s"
                  % (level, "; ".join("%s %s %s" % r for r in bad)))
    return bad


# ---------------------------------------------------------------- selftest

def gds_fixture(date, x):
    def rec(rt, dt, data=b""):
        return struct.pack(">HBB", 4 + len(data), rt, dt) + data
    d = struct.pack(">12H", *date)
    return b"".join([
        rec(0x00, 0x02, struct.pack(">H", 600)), rec(0x01, 0x02, d),
        rec(0x02, 0x06, b"LIB\x00"), rec(0x05, 0x02, d),
        rec(0x06, 0x06, b"TOP\x00"), rec(0x08, 0x00),
        rec(0x0D, 0x02, struct.pack(">H", 68)),
        rec(0x0E, 0x02, struct.pack(">H", 20)),
        rec(0x10, 0x03, struct.pack(">10i", 0, 0, x, 0, x, 5, 0, 5, 0, 0)),
        rec(0x11, 0x00), rec(0x07, 0x00), rec(0x04, 0x00)])


def gds_library(date, structs):
    """A stream holding the named structures in the order given, each with
    one BOUNDARY per x in its list."""
    def rec(rt, dt, data=b""):
        return struct.pack(">HBB", 4 + len(data), rt, dt) + data
    d = struct.pack(">12H", *date)
    out = [rec(0x00, 0x02, struct.pack(">H", 600)), rec(0x01, 0x02, d),
           rec(0x02, 0x06, b"LIB\x00")]
    for name, xs in structs:
        out += [rec(0x05, 0x02, d), rec(0x06, 0x06, name.encode() + b"\x00")]
        for x in xs:
            out += [rec(0x08, 0x00), rec(0x0D, 0x02, struct.pack(">H", 68)),
                    rec(0x0E, 0x02, struct.pack(">H", 20)),
                    rec(0x10, 0x03, struct.pack(">10i", 0, 0, x, 0, x, 5, 0,
                                                5, 0, 0)),
                    rec(0x11, 0x00)]
        out.append(rec(0x07, 0x00))
    out.append(rec(0x04, 0x00))
    return b"".join(out)


DEF_FIXTURE = """VERSION 5.8 ;
DESIGN top ;
COMPONENTS 2 ;
    - u1 sky130_fd_sc_hd__inv_1 + PLACED ( 100 200 ) N ;
    - u2 sky130_fd_sc_hd__inv_1 + PLACED ( 400 200 ) N ;
END COMPONENTS
NETS 2 ;
    - a ( u1 Y ) ( u2 A ) + USE SIGNAL
      + ROUTED met1 ( 100 200 ) ( 400 * ) ;
    - b ( u2 Y ) + USE SIGNAL ;
END NETS
END DESIGN
"""


def selftest():
    import tempfile
    ok = True

    def build(root, gds, df, nl, spef):
        os.makedirs(os.path.join(root, "final", "gds"))
        os.makedirs(os.path.join(root, "final", "def"))
        os.makedirs(os.path.join(root, "final", "nl"))
        os.makedirs(os.path.join(root, "final", "spef", "nom"))
        for sub, name, blob in (("gds", TOP + ".gds", gds),
                                ("def", TOP + ".def", df),
                                ("nl", TOP + ".nl.v", nl),
                                (os.path.join("spef", "nom"),
                                 TOP + ".nom.spef", spef)):
            with open(os.path.join(root, "final", sub, name), "wb") as fh:
                fh.write(blob if isinstance(blob, bytes) else blob.encode())

    base_date = (126, 9, 16, 17, 45, 36) * 2
    other_date = (126, 9, 23, 9, 1, 2) * 2
    nl = "module top; endmodule\n"
    spef = '*SPEF "ieee 1481-1999"\n*DATE "Wed Sep 16 2026"\n*D_NET *1 0.1\n'
    cases = [
        ("only the dates differ", dict(gds=gds_fixture(other_date, 10),
         spef=spef.replace("Sep 16", "Sep 23")), set()),
        ("a polygon moved", dict(gds=gds_fixture(base_date, 11)), {"gds"}),
        ("a component moved", dict(df=DEF_FIXTURE.replace(
            "( 400 200 )", "( 460 200 )")), {"def"}),
        ("a net rerouted", dict(df=DEF_FIXTURE.replace(
            "( 400 * )", "( 400 * ) ( * 260 )")), {"def"}),
        ("CRLF only", dict(df=DEF_FIXTURE.replace("\n", "\r\n"),
                           nl=nl.replace("\n", "\r\n")), set()),
    ]
    with tempfile.TemporaryDirectory() as d:
        arch = os.path.join(d, "arch")
        os.makedirs(arch)
        for name, blob in ((TOP + ".gds", gds_fixture(base_date, 10)),
                           (TOP + ".def", DEF_FIXTURE.encode()),
                           (TOP + ".nl.v", nl.encode()),
                           (TOP + ".nom.spef", spef.encode())):
            with open(os.path.join(arch, name), "wb") as fh:
                fh.write(blob)
        for k, (name, change, expect) in enumerate(cases):
            files = dict(gds=gds_fixture(base_date, 10), df=DEF_FIXTURE,
                         nl=nl, spef=spef)
            files.update(change)
            run = os.path.join(d, "run%d" % k)
            build(run, **files)
            rows = compare(run, arch)
            got = {r[0] for r in rows if r[1] != "identical"}
            good = got == expect
            print("selftest %-22s %s%s" % (name, "ok" if good else "WRONG",
                                           "" if good else " %s" % rows))
            ok = ok and good
            if name == "a component moved":
                detail = [r[2] for r in rows if r[0] == "def"][0]
                named = detail.startswith("1 components moved")
                print("selftest   says what moved: %s" % detail)
                ok = ok and named
            if name == "a net rerouted":
                detail = [r[2] for r in rows if r[0] == "def"][0]
                named = detail.startswith("1 nets routed differently")
                print("selftest   says what moved: %s" % detail)
                ok = ok and named
        rows = compare(os.path.join(d, "empty"), arch)
        missing = all(r[1] == "missing" for r in rows)
        print("selftest nothing built          %s" % ("ok" if missing
                                                    else "WRONG"))
        ok = ok and missing
    # The same layout written out in another order has to come out the
    # same, and a moved shape inside a reordered file still has to be named.
    base = gds_normalised(gds_library(
        base_date, [("A", [10, 20]), ("TOP", [30])]))
    for label, structs, want in (
            ("structures reordered", [("TOP", [30]), ("A", [10, 20])], True),
            ("shapes reordered", [("A", [20, 10]), ("TOP", [30])], True),
            ("reordered, one moved", [("TOP", [30]), ("A", [21, 10])], False),
            ("a structure missing", [("A", [10, 20])], False)):
        other = gds_normalised(gds_library(other_date, structs))
        same, detail = compare_gds(other, base)
        good = same == want and (same or "A" in detail or "TOP" in detail)
        print("selftest %-22s %s: %s" % (label, "ok" if good else "WRONG",
                                         detail))
        ok = ok and good
    print("selftest %s" % ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir")
    ap.add_argument("--against", default="dualarm/build_armc")
    ap.add_argument("--annotate", action="store_true")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.run_dir:
        ap.error("--run-dir or --selftest")
    rows = compare(a.run_dir, a.against)
    bad = report(rows, a.annotate)
    if any(r[1] == "missing" for r in bad):
        return 1
    return 1 if bad and a.strict else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
