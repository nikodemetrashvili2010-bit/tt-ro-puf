#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""The placement file the flow can actually read, and the reason it holds
only half of what G.3 step 7 asked for.

Step 7 is "pin Arm A and bind the sixteen Arm C regions". `gen_armc.py`
emitted `chip/armc_place.tcl` for it in August and left the binding line
blank on purpose, because the command that constrains a cell group to a
region differs between flow versions and that script had run none of them.
`docs/phaseE_armc_build.md` says to fill it in against the flow the build
actually uses.

I went and looked at that flow. It is LibreLane, 3.0.3 in the run directory
on this disk and 3.0.5 in CI, and the four files that decide every placement
question are byte identical between those two tags. It has no fence, no
region and no cell-group constraint, and none of its four Tcl hooks is read
by a placement step. So there is no line to fill in, and the 512 `place_cell`
lines above it have nowhere to be sourced from either. The whole file is
written against an interface this flow does not have.

`chip/FLOW_SURFACE.json` is that flow's configuration surface, all 413
variables and all 72 executed steps, taken from its own run record rather
than from documentation. This script reads it and does two things.

It emits `src/placement.cfg`, which is the file `MACRO_PLACEMENT_CFG` takes:
one instance per line, name, x, y, orientation. That is the pinning half of
step 7 and it works. The catch is in the step's own source: it builds its
config from `MACRO_PLACEMENT_CFG` if that is set and from `MACROS`
otherwise, an if/elif, so the moment this design hands the flow a cfg file
the sixteen hardened macros stop being placed by the `MACROS` block. The
file therefore carries all sixteen of them as well, at the coordinates
`config.json` already gives, and a check here fails if any of them is
dropped or moved.

It emits no Arm C line at all, and says so rather than quietly placing them.
Arm C without a region constraint is standard cells handed to an
unconstrained placer, which is Arm A's treatment, not a third one. Placing
every Arm C cell by hand would satisfy G.2's build criterion trivially and
would also make it measure nothing. That is a decision about the experiment
and it belongs in G.2, not in a generator. `PLACEMENT_CFG.json` records the
missing capability by name so the decision is taken with the reason in front
of it.

What this does not check is the interaction with the two steps that follow.
`Odb.ManualMacroPlacement` runs at step 17, before `OpenROAD.CutRows` and
`OpenROAD.TapEndcapInsertion`, so the taps go in around 512 cells that are
already FIRM. The frozen DEF proves a legal arrangement at these exact
coordinates exists, because it is one. It does not prove that tap insertion
finds it from this direction. Only the build says that, and the declared
fallback if it does not is `MANUAL_GLOBAL_PLACEMENTS`, which runs at step 33
after global placement and sets PLACED rather than FIRM. This script renders
that fallback too and records its hash without committing it.

Usage:
    python3 gen_placement_cfg.py --selftest
    python3 gen_placement_cfg.py
    python3 gen_placement_cfg.py --json /tmp/placement_cfg.json --emit /tmp/pl
    python3 gen_placement_cfg.py --emit-fallback /tmp/fallback.json
    python3 gen_placement_cfg.py --refresh-surface

The archived answers are `PLACEMENT_CFG.json` beside this file and
`src/placement.cfg` under `dualarm/`. CI regenerates both and diffs.
"""

import argparse
import collections
import decimal
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tile_budget as tb  # noqa: E402  sha256_file only, see sha256_file below

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DEF_PATH = os.path.join(
    ROOT, "dualarm", "build_current",
    "tt_um_nikodemetrashvili20_ro_puf.def")
CONFIG_PATH = os.path.join(ROOT, "dualarm", "src", "config.json")
SURFACE_PATH = os.path.join(HERE, "FLOW_SURFACE.json")
REGIONS_PATH = os.path.join(HERE, "ARMC_REGIONS.json")
TCL_PATH = os.path.join(HERE, "armc_place.tcl")
RUN_DIR = os.path.join(ROOT, "gds_build", "runs", "wokwi")

CFG_NAME = "placement.cfg"
CFG_DEST = os.path.join(ROOT, "dualarm", "src", CFG_NAME)
JSON_DEST = os.path.join(HERE, "PLACEMENT_CFG.json")

# The eight LEF orientations placers.py can translate. Anything else and
# lef_rot_to_oa_rot asserts, which kills the build at step 17 rather than
# reporting a bad line. Copied from the values, not the behaviour: the
# recorded sha256 of placers.py in FLOW_SURFACE.json is what pins it.
LEF_ORIENTS = ("N", "S", "W", "E", "FN", "FS", "FW", "FE")

# placers.py rounds every coordinate to a multiple of this many database
# units before it places anything: gridify(n, 5). A coordinate that does not
# survive that is moved by the flow without saying so.
GRIDIFY = 5

ARM_A_RE = re.compile(r"^u_puf\.u_core\.g_ro_bank\[(\d+)\]\.u_ro\.")
ARM_C_RE = re.compile(r"^u_puf\.u_core\.g_armc\[(\d+)\]\.u_roc\.")
TAPLIKE = ("tapvpwrvgnd", "decap", "fill")

# Masters that are not standard cells and do not stand on a row.
MACRO_MASTER = "ro_macro_hard"


def sha256_file(path):
    """The bytes a checkout produces. tile_budget.py owns the rule and the
    six chip scripts that hash files share its copy; see the header of
    chip/hash_stability.py for why hashing the disk bytes held the gate red
    for five pushes."""
    return tb.sha256_file(path)


def sha256_text(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unescape(name):
    """The DEF escapes each bracket, the netlist escapes the whole
    identifier with one leading backslash, and placers.py wants neither: it
    calls escape_verilog_name on what it reads. Strip backslashes and let
    the flow put its own back."""
    return name.replace("\\", "")


def dec(value):
    """A coordinate as an exact decimal. placers.py multiplies whatever
    string it reads by the database units with Decimal arithmetic, so a
    float that prints as 3.2200000000000002 becomes a different cell
    position. Everything here goes through Decimal from the text."""
    if isinstance(value, decimal.Decimal):
        return value
    return decimal.Decimal(str(value))


def dec_str(value):
    """Render a Decimal the way the cfg file carries it: plain, no
    exponent, no trailing zero padding beyond what the value needs."""
    d = dec(value).normalize()
    if d == d.to_integral_value():
        d = d.quantize(decimal.Decimal(1))
    return format(d, "f")


class Cell(object):
    __slots__ = ("inst", "master", "x", "y", "orient", "status")

    def __init__(self, inst, master, x, y, orient, status):
        self.inst = inst
        self.master = master
        self.x = x
        self.y = y
        self.orient = orient
        self.status = status


class Row(object):
    __slots__ = ("name", "site", "x", "y", "orient", "num", "step")

    def __init__(self, name, site, x, y, orient, num, step):
        self.name = name
        self.site = site
        self.x = x
        self.y = y
        self.orient = orient
        self.num = num
        self.step = step

    @property
    def x_end(self):
        return self.x + self.num * self.step


class Design(object):
    def __init__(self, units, die, rows, cells):
        self.units = units
        self.die = die
        self.rows = rows
        self.cells = cells
        self.by_y = collections.defaultdict(list)
        for c in cells:
            self.by_y[c.y].append(c)
        self.rows_by_y = {}
        for r in rows:
            self.rows_by_y.setdefault(r.y, []).append(r)

    @property
    def row_height(self):
        ys = sorted(set(r.y for r in self.rows))
        gaps = sorted(set(ys[i + 1] - ys[i] for i in range(len(ys) - 1)))
        return gaps[0]


COMP_RE = re.compile(
    r"^-\s+(\S+)\s+(\S+)\s*(.*)$")
PLACE_RE = re.compile(
    r"\+\s*(FIXED|PLACED|COVER|UNPLACED)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*"
    r"(\S+)")
ROW_RE = re.compile(
    r"^ROW\s+(\S+)\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(\S+)\s+DO\s+(\d+)\s+BY\s+"
    r"(\d+)\s+STEP\s+(\d+)\s+(\d+)\s*;")


def read_def(path):
    """Enough of DEF 5.8 to answer where every instance and every row is.

    The component section is one statement per record but a record can wrap,
    so the section is joined and split on the leading dash rather than read
    line by line. Nothing here parses nets: this file is about positions."""
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    m = re.search(r"^UNITS DISTANCE MICRONS\s+(\d+)\s*;", text, re.M)
    if not m:
        raise ValueError("no UNITS line in %s" % path)
    units = int(m.group(1))

    m = re.search(r"^DIEAREA\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*"
                  r"\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*;", text, re.M)
    if not m:
        raise ValueError("no DIEAREA line in %s" % path)
    die = tuple(int(g) for g in m.groups())

    rows = []
    for line in text.splitlines():
        rm = ROW_RE.match(line.strip())
        if rm:
            name, site, x, y, orient, num, by, stepx, _ = rm.groups()
            rows.append(Row(name, site, int(x), int(y), orient,
                            int(num), int(stepx)))
    if not rows:
        raise ValueError("no ROW lines in %s" % path)

    start = text.find("\nCOMPONENTS")
    end = text.find("\nEND COMPONENTS")
    if start < 0 or end < 0:
        raise ValueError("no COMPONENTS section in %s" % path)
    body = text[text.index("\n", start + 1):end]

    cells = []
    # A record is indented before its dash, so splitting on a bare "\n-"
    # matches nothing and hands the whole section back as one record. That
    # parses, produces exactly one instance called "-", and every check that
    # counts instances then passes on an empty set.
    for record in re.split(r"\n\s*-\s+", body):
        record = record.strip()
        if not record:
            continue
        record = record.rstrip(";").strip()
        parts = record.split()
        if len(parts) < 2:
            continue
        inst, master = parts[0], parts[1]
        pm = PLACE_RE.search(record)
        if not pm:
            continue
        status, x, y, orient = pm.groups()
        cells.append(Cell(inst, master, int(x), int(y), orient, status))
    if not cells:
        raise ValueError("no components parsed from %s" % path)
    return Design(units, die, rows, cells)


def rows_at(design, y):
    """Every row record at this y. A y can carry more than one: the strip
    beside the macro block is its own ROW_n_5 and starts at a different x
    from the full width rows below it."""
    return design.rows_by_y.get(y, ())



# ---------------------------------------------------------------------------
# The flow's configuration surface
# ---------------------------------------------------------------------------

# Words that would appear in the name of a variable able to hold a cell
# inside an area. The search below runs over all 413 names and the only hit
# is IO_EXCLUDE_PIN_REGION, which is about pins.
AREA_WORDS = ("REGION", "FENCE", "GROUP", "GUIDE", "CLUSTER", "PARTITION")

# The six variables in this flow whose names carry one of those words, and
# what each of them actually does. They are listed one by one rather than
# filtered out by prefix so that a seventh, in a later flow version, is
# reported instead of absorbed.
AREA_WORDS_ALLOWED = (
    "IO_EXCLUDE_PIN_REGION",            # keeps IO pins out of an area
    "CTS_SINK_CLUSTERING_ENABLE",       # clock tree sinks, not placement
    "CTS_SINK_CLUSTERING_SIZE",
    "CTS_SINK_CLUSTERING_MAX_DIAMETER",
    "CTS_MACRO_CLUSTERING_SIZE",
    "CTS_MACRO_CLUSTERING_MAX_DIAMETER",
)


def load_surface(path=SURFACE_PATH):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def area_variable_hits(surface):
    hits = []
    for name in surface["variables"]:
        upper = name.upper()
        if any(word in upper for word in AREA_WORDS):
            hits.append(name)
    return sorted(hits)


def mechanism(surface, mech_id):
    for m in surface["placement_mechanisms"]:
        if m["id"] == mech_id:
            return m
    return None


def refresh_surface(run_dir=RUN_DIR, out=SURFACE_PATH):
    """Rebuild the pinned surface from the flow's own run directory.

    gds_build/ is not mirrored to the clone, so this cannot run in CI and is
    not in the gate. It fails rather than skips when the directory is
    missing: a mode that reports success because it found nothing to read is
    the shape that made B07 green against an empty gate list on 31 August.

    The identical_across_versions block is not rebuilt. It records what came
    off raw.githubusercontent.com at two tags on 2026-09-06, the same way
    extraction/INPUT_MANIFEST.json records a download, and it is carried
    forward untouched."""
    if not os.path.isdir(run_dir):
        raise SystemExit(
            "refresh-surface needs %s and it is not here. That directory is "
            "the flow's own run record and it is not mirrored to the clone."
            % run_dir)
    old = load_surface(out)
    with io.open(os.path.join(run_dir, "resolved.json"),
                 encoding="utf-8") as fh:
        resolved = json.load(fh)
    with io.open(os.path.join(run_dir, "pdk.json"), encoding="utf-8") as fh:
        pdk = json.load(fh)
    steps = sorted(d for d in os.listdir(run_dir) if re.match(r"^\d\d-", d))
    ids = {}
    with io.open(os.path.join(run_dir, "flow.log"),
                 encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r"Running '([^']+)' at '([^']+)'", line.strip())
            if m:
                ids[os.path.basename(m.group(2))] = m.group(1)

    fresh = dict(old)
    fresh["flow"] = dict(old["flow"])
    fresh["flow"]["name"] = pdk["FLOW_NAME"]
    fresh["flow"]["version_on_disk"] = pdk["FLOW_VERSION"]
    fresh["flow"]["pdk"] = pdk["PDK"]
    fresh["flow"]["pdk_version"] = pdk["PDK_VERSION"]
    fresh["variables"] = sorted(resolved.keys())
    fresh["variable_count"] = len(resolved)
    fresh["steps_executed"] = [{"dir": d, "id": ids.get(d, "")}
                               for d in steps]
    fresh["step_count"] = len(steps)
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(fresh, fh, indent=2)
        fh.write("\n")
    return fresh


# ---------------------------------------------------------------------------
# What goes in the file
# ---------------------------------------------------------------------------

def arm_a_cells(design):
    """The 512 standard cells of the sixteen Arm A rings, in the order the
    DEF lists them so that regenerating this file twice gives the same
    bytes."""
    out = [c for c in design.cells if ARM_A_RE.match(unescape(c.inst))]
    out.sort(key=lambda c: unescape(c.inst))
    return out


def arm_c_cells(design):
    return [c for c in design.cells if ARM_C_RE.match(unescape(c.inst))]


def macro_instances(config_path=CONFIG_PATH):
    """The sixteen hardened macros, read from the same config.json the
    build reads, with the coordinates kept as text.

    parse_float=Decimal matters. json.load turns 3.22 into a float that is
    not 3.22, and placers.py multiplies the string it is given by 1000
    using Decimal arithmetic, so a rendered float would place the macro
    somewhere else."""
    with io.open(config_path, encoding="utf-8") as fh:
        config = json.load(fh, parse_float=decimal.Decimal)
    out = []
    macros = config.get("MACROS") or {}
    for module in sorted(macros):
        insts = macros[module].get("instances") or {}
        for name in sorted(insts, key=lambda s: (len(s), s)):
            data = insts[name]
            loc = data.get("location")
            if loc is None:
                continue
            out.append({
                "inst": name,
                "module": module,
                "x": dec(loc[0]),
                "y": dec(loc[1]),
                "orient": data.get("orientation"),
            })
    return out, config


def cfg_rows(design, config_path=CONFIG_PATH):
    """Every line the cfg file will carry, macros first and then Arm A.

    Macros first because that is the order the MACROS block would have
    produced them in, and this file is standing in for it."""
    rows = []
    macros, config = macro_instances(config_path)
    for m in macros:
        rows.append({
            "inst": m["inst"],
            "kind": "macro",
            "master": m["module"],
            "x": m["x"],
            "y": m["y"],
            "orient": m["orient"],
            "x_dbu": None,
            "y_dbu": None,
        })
    units = design.units
    for c in arm_a_cells(design):
        rows.append({
            "inst": unescape(c.inst),
            "kind": "arm_a",
            "master": c.master,
            "x": dec(c.x) / units,
            "y": dec(c.y) / units,
            "orient": c.orient,
            "x_dbu": c.x,
            "y_dbu": c.y,
        })
    return rows, config


def render_cfg(rows):
    """The MACRO_PLACEMENT_CFG format: instance, x, y, orientation, one per
    line, whitespace separated, # starts a comment.

    placers.py splits on '#' before it splits on whitespace, so the header
    is safe. It also exits 1 naming any instance it cannot find, which is
    the line in the build log that says the pinning took."""
    out = [
        "# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili",
        "# SPDX-License-Identifier: Apache-2.0",
        "#",
        "# MACRO_PLACEMENT_CFG for Odb.ManualMacroPlacement, step 17.",
        "# Generated by chip/gen_placement_cfg.py, do not edit.",
        "#",
        "# Sixteen hardened Arm B macros and 512 Arm A standard cells, all",
        "# placed FIRM before the rows are cut. The macros are here because",
        "# the step reads MACRO_PLACEMENT_CFG instead of MACROS, not as",
        "# well as it, so leaving them out would unplace the whole macro",
        "# block. Arm A is here because a rebuild otherwise re-places it and",
        "# the two-arm result the paper measured is quoted off these exact",
        "# coordinates.",
        "#",
        "# No Arm C line. See chip/PLACEMENT_CFG.json and",
        "# docs/phaseG_g3_step7.md.",
        "",
    ]
    for r in rows:
        out.append("%s %s %s %s" % (r["inst"], dec_str(r["x"]),
                                    dec_str(r["y"]), r["orient"]))
    return "\n".join(out) + "\n"


def render_fallback(rows):
    """MANUAL_GLOBAL_PLACEMENTS, the declared fallback, as the JSON
    fragment that would go into config.json.

    Only the Arm A half. The macros keep their MACROS placement in this
    arrangement, which is the reason it is worth having: it changes one
    thing instead of two. It buys that at the price of PLACED instead of
    FIRM, so detailed placement is allowed to move a cell and only says by
    how much afterwards.

    Not committed. Its hash is recorded so that the thing being offered as
    a fallback is a specific file and not a sentence."""
    body = collections.OrderedDict()
    for r in rows:
        if r["kind"] != "arm_a":
            continue
        body[r["inst"]] = collections.OrderedDict((
            ("location", [float(r["x"]), float(r["y"])]),
            ("orientation", r["orient"]),
        ))
    doc = collections.OrderedDict((("MANUAL_GLOBAL_PLACEMENTS", body),))
    return json.dumps(doc, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

class Checks(object):
    def __init__(self):
        self.rows = []

    def add(self, cid, name, ok, detail):
        self.rows.append({"id": cid, "name": name,
                          "pass": bool(ok), "detail": detail})

    def failed(self):
        return [r["id"] for r in self.rows if not r["pass"]]


def row_for(design, cell):
    """The row a cell stands on, or None.

    This asks where the origin lands, not where the cell ends, because no
    cell width is recovered here. Whether the placement is legal end to end
    is tile_budget.py's T06, which checks width consistency, row packing and
    row area as the one property they are, for the whole die. Repeating it
    here bought nothing and cost a planted fault that shrank the recovered
    width instead of showing up as an overlap."""
    for r in rows_at(design, cell.y):
        if r.x <= cell.x < r.x_end:
            return r
    return None


def run_checks(design, surface, rows, config, tcl_text, regions,
               fallback_text, fallback_again, on_fixture=False):
    ck = Checks()
    units = design.units

    # -- P01 ---------------------------------------------------------------
    flow = surface.get("flow", {})
    same = surface.get("identical_across_versions", {})
    files = same.get("files", {})
    need = ("librelane/steps/odb.py", "librelane/steps/openroad.py",
            "librelane/scripts/odbpy/placers.py")
    have_all = all(f in files for f in need)
    tags = same.get("tags") or []
    ok = (flow.get("name") == "LibreLane"
          and flow.get("version_on_disk")
          and flow.get("version_in_ci")
          and len(tags) == 2
          and have_all
          and all(len(files[f]) == 64 for f in need))
    ck.add("P01", "the flow is named, both versions are pinned, and the "
           "files that decide placement hash the same at each",
           ok, "%s %s on disk, %s in CI, %d files pinned at %d tags"
           % (flow.get("name"), flow.get("version_on_disk"),
              flow.get("version_in_ci"), len(files), len(tags)))

    # -- P02 ---------------------------------------------------------------
    hits = area_variable_hits(surface)
    unexpected = [h for h in hits if h not in AREA_WORDS_ALLOWED]
    recorded = surface.get("region_binding", {})
    ok = (not unexpected
          and recorded.get("exists") is False
          and sorted(recorded.get("hits") or []) == sorted(hits))
    ck.add("P02", "no variable in the flow can hold a cell inside an area",
           ok, "%d of %d variable names carry an area word: %s"
           % (len(hits), surface.get("variable_count", 0),
              ", ".join(hits) if hits else "none"))

    # -- P03 ---------------------------------------------------------------
    hooks = surface.get("tcl_hooks", {})
    uses_place_cell = "place_cell" in tcl_text
    ok = (hooks.get("reaches_a_placement_step") is False
          and uses_place_cell)
    ck.add("P03", "armc_place.tcl asks for a command no step will source",
           ok, "place_cell present: %s, tcl hooks reaching a placement "
           "step: %s" % (uses_place_cell,
                         hooks.get("reaches_a_placement_step")))

    # -- P04 ---------------------------------------------------------------
    mech = mechanism(surface, "MACRO_PLACEMENT_CFG") or {}
    declared, _ = macro_instances_from_config(config)
    emitted = {r["inst"]: r for r in rows if r["kind"] == "macro"}
    moved = []
    for d in declared:
        e = emitted.get(d["inst"])
        if e is None or dec(e["x"]) != dec(d["x"]) or \
                dec(e["y"]) != dec(d["y"]) or e["orient"] != d["orient"]:
            moved.append(d["inst"])
    ok = (mech.get("excludes") == "MACROS"
          and len(emitted) == len(declared)
          and not moved)
    ck.add("P04", "every macro the MACROS block places is in the file, "
           "because the step reads one or the other and not both",
           ok, "%d declared, %d emitted, %d moved or missing%s"
           % (len(declared), len(emitted), len(moved),
              ": " + ", ".join(moved[:4]) if moved else ""))

    # -- P05 ---------------------------------------------------------------
    arma = arm_a_cells(design)
    emitted_a = [r for r in rows if r["kind"] == "arm_a"]
    seen = collections.Counter(r["inst"] for r in emitted_a)
    dupes = [n for n, c in seen.items() if c > 1]
    wrong = []
    by_inst = {unescape(r["inst"]): r for r in emitted_a}
    for c in arma:
        r = by_inst.get(unescape(c.inst))
        if r is None:
            wrong.append(unescape(c.inst))
            continue
        if r["x_dbu"] != c.x or r["y_dbu"] != c.y or r["orient"] != c.orient:
            wrong.append(unescape(c.inst))
    expected = 512 if not on_fixture else len(arma)
    ok = (len(emitted_a) == len(arma) == expected
          and not dupes and not wrong)
    ck.add("P05", "every Arm A cell is in the file once, at the coordinate "
           "and orientation the frozen DEF gives it",
           ok, "%d in the DEF, %d emitted, %d duplicated, %d moved"
           % (len(arma), len(emitted_a), len(dupes), len(wrong)))

    # -- P06 ---------------------------------------------------------------
    off = []
    for r in rows:
        for axis in ("x", "y"):
            raw = int(dec(r[axis]) * units)
            if raw % GRIDIFY != 0:
                off.append("%s %s" % (r["inst"], axis))
    ok = not off
    ck.add("P06", "no coordinate is moved by the flow's own rounding",
           ok, "%d of %d coordinates are not a multiple of %d dbu%s"
           % (len(off), 2 * len(rows), GRIDIFY,
              ": " + ", ".join(off[:4]) if off else ""))

    # -- P07 ---------------------------------------------------------------
    from_inputs = set(c.orient for c in arma)
    from_inputs |= set(d["orient"] for d in declared)
    bad = sorted(o for o in from_inputs if o not in LEF_ORIENTS)
    ok = not bad
    ck.add("P07", "every orientation the inputs carry is one the flow can "
           "translate", ok, "%d distinct orientations, %d untranslatable%s"
           % (len(from_inputs), len(bad),
              ": " + ", ".join(bad) if bad else ""))

    # -- P08 ---------------------------------------------------------------
    escaped = [r["inst"] for r in rows if "\\" in r["inst"]]
    roundtrip = []
    for c in arma:
        if unescape(c.inst) not in by_inst:
            continue
        if re_escape_brackets(unescape(c.inst)) != c.inst:
            roundtrip.append(c.inst)
    ok = not escaped and not roundtrip
    ck.add("P08", "names go in unescaped and come back as the DEF spells "
           "them", ok, "%d names carry a backslash, %d fail the round trip"
           % (len(escaped), len(roundtrip)))

    # -- P09 ---------------------------------------------------------------
    offrow = [unescape(c.inst) for c in arma if row_for(design, c) is None]
    ok = not offrow
    ck.add("P09", "every pinned cell stands on a row of the frozen DEF, "
           "inside that row's span", ok, "%d of %d off any row%s"
           % (len(offrow), len(arma),
              ": " + ", ".join(offrow[:3]) if offrow else ""))

    # -- P10 ---------------------------------------------------------------
    offgrid = []
    for c in arma:
        r = row_for(design, c)
        if r is not None and (c.x - r.x) % r.step != 0:
            offgrid.append(unescape(c.inst))
    ok = not offgrid
    ck.add("P10", "every pinned cell starts on its row's site grid",
           ok, "%d off the grid, site %d dbu"
           % (len(offgrid), design.rows[0].step))

    # -- P11 ---------------------------------------------------------------
    armc_emitted = [r for r in rows if ARM_C_RE.match(r["inst"])]
    named = (surface.get("region_binding", {}).get("conclusion") or "")
    ok = (not armc_emitted
          and len(regions) == 16
          and "region" in named.lower())
    ck.add("P11", "no Arm C line is emitted and the capability that would "
           "be needed is named", ok,
           "%d Arm C lines, %d regions on record, conclusion recorded: %s"
           % (len(armc_emitted), len(regions), bool(named)))

    # -- P12 ---------------------------------------------------------------
    ok = fallback_text == fallback_again and fallback_text.strip() != ""
    ck.add("P12", "the declared fallback renders the same bytes twice",
           ok, "%d bytes, stable: %s"
           % (len(fallback_text), fallback_text == fallback_again))

    return ck


def re_escape_brackets(name):
    """Put back the escaping the DEF uses: a backslash before each bracket.
    The netlist escapes the whole identifier instead, and mixing the two up
    is what cost a day in Phase E."""
    return name.replace("[", "\\[").replace("]", "\\]")


def macro_instances_from_config(config):
    """Same as macro_instances but from an already loaded config, so the
    checks do not read the file a second time and disagree with the
    emitter about what it said."""
    out = []
    macros = config.get("MACROS") or {}
    for module in sorted(macros):
        insts = macros[module].get("instances") or {}
        for name in sorted(insts, key=lambda s: (len(s), s)):
            data = insts[name]
            loc = data.get("location")
            if loc is None:
                continue
            out.append({"inst": name, "module": module,
                        "x": dec(loc[0]), "y": dec(loc[1]),
                        "orient": data.get("orientation")})
    return out, config


# ---------------------------------------------------------------------------
# Fixture and planted faults
# ---------------------------------------------------------------------------

FIXTURE_CONFIG = {
    "MACROS": {
        "ro_macro_hard": {
            "instances": {
                "u_rob0": {"location": [3.22, 20], "orientation": "N"},
                "u_rob1": {"location": [63.22, 20], "orientation": "N"},
            }
        }
    }
}

FIXTURE_SURFACE = {
    "flow": {"name": "LibreLane", "version_on_disk": "3.0.3",
             "version_in_ci": "3.0.5", "pdk": "sky130A"},
    "identical_across_versions": {
        "tags": ["3.0.3", "3.0.5"],
        "files": {
            "librelane/steps/odb.py": "0" * 64,
            "librelane/steps/openroad.py": "1" * 64,
            "librelane/scripts/odbpy/placers.py": "2" * 64,
            "librelane/flows/classic.py": "3" * 64,
        },
    },
    "variables": ["IO_EXCLUDE_PIN_REGION", "MACROS", "MACRO_PLACEMENT_CFG",
                  "MANUAL_GLOBAL_PLACEMENTS", "PL_TARGET_DENSITY_PCT"],
    "variable_count": 5,
    "placement_mechanisms": [
        {"id": "MACRO_PLACEMENT_CFG", "excludes": "MACROS",
         "status_set": "FIRM"},
        {"id": "MANUAL_GLOBAL_PLACEMENTS", "excludes": None,
         "status_set": "PLACED"},
    ],
    "region_binding": {"exists": False, "hits": ["IO_EXCLUDE_PIN_REGION"],
                       "conclusion": "no fence, region or cell-group "
                                     "constraint exists"},
    "tcl_hooks": {"PDN_CFG": "OpenROAD.GeneratePDN",
                  "reaches_a_placement_step": False},
}

FIXTURE_TCL = ("# generated\nplace_cell -inst_name {u_x} "
               "-origin {1.0 2.0} -orient N -status FIRM\n")

W = 1380          # the one cell width the fixture uses
STEP = 460        # site
RH = 2720         # row height


def fixture_design():
    """Two rows, two Arm A rings of three cells each, one neighbour per row
    that is not Arm A, and a gap in the second row so that a cell can be
    moved off the site grid without also being moved into another cell.

    P05 counts 512 on the real design and len(arma) here; that exemption is
    by name in run_checks, the same way ARMC_REGIONS.json's A01 and A11 are
    excused on their fixture."""
    rows = [Row("R0", "unithd", 0, 0, "N", 20, STEP),
            Row("R1", "unithd", 0, RH, "FS", 20, STEP),
            Row("R2", "unithd", 0, 2 * RH, "N", 20, STEP)]
    cells = []
    for ring, y, orient in ((0, 0, "N"), (1, RH, "FS")):
        base = "u_puf.u_core.g_ro_bank\\[%d\\].u_ro." % ring
        cells.append(Cell(base + "u_nand", "cellA", 0, y, orient, "PLACED"))
        cells.append(Cell(base + "g_inv\\[1\\].u_inv", "cellA", W, y,
                          orient, "PLACED"))
        cells.append(Cell(base + "g_inv\\[2\\].u_inv", "cellA", 2 * W, y,
                          orient, "PLACED"))
    cells.append(Cell("u_other0", "cellA", 3 * W, 0, "N", "PLACED"))
    cells.append(Cell("u_other1", "cellA", 4 * W, RH, "FS", "PLACED"))
    # A third row, packed edge to edge and holding no Arm A cell. The width
    # recovery takes the smallest abutment a master is ever seen at, so
    # without a row a fault cannot reach, moving one cell to make it overlap
    # its neighbour shrinks the recovered width instead and the overlap
    # check never fires. That is what the first version of the P09 fault
    # did.
    for k in range(4):
        cells.append(Cell("u_clean%d" % k, "cellA", k * W, 2 * RH, "N",
                          "PLACED"))
    return Design(1000, (0, 0, 10000, 10000), rows, cells)


def fixture_bundle(config=None):
    """Everything run_checks wants, built from scratch so a fault applied to
    one bundle cannot leak into the next."""
    import tempfile
    design = fixture_design()
    cfg = json.loads(json.dumps(config or FIXTURE_CONFIG))
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cfg, fh)
    try:
        rows, loaded = cfg_rows(design, path)
    finally:
        os.unlink(path)
    surface = json.loads(json.dumps(FIXTURE_SURFACE))
    fb = render_fallback(rows)
    regions = [{"index": i} for i in range(16)]
    return {"design": design, "surface": surface, "rows": rows,
            "config": loaded, "config_raw": cfg,
            "tcl": FIXTURE_TCL, "regions": regions,
            "fallback": fb, "fallback_again": fb}


def check_bundle(b):
    return run_checks(b["design"], b["surface"], b["rows"], b["config"],
                      b["tcl"], b["regions"], b["fallback"],
                      b["fallback_again"], on_fixture=True)


def _arm_a_row(b, index=1):
    return [r for r in b["rows"] if r["kind"] == "arm_a"][index]


def rebuild(b):
    """Re-derive the emitted rows and the widths after a fault has moved
    something in the design. Without this every design-side fault also
    reads as P05, because the file would still be carrying the old
    coordinate and that is a different fault entirely."""
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(b["config_raw"], fh)
    try:
        b["rows"], b["config"] = cfg_rows(b["design"], path)
    finally:
        os.unlink(path)
    b["fallback"] = render_fallback(b["rows"])
    b["fallback_again"] = b["fallback"]


def f01_drop_a_pinned_file(b):
    del b["surface"]["identical_across_versions"]["files"][
        "librelane/scripts/odbpy/placers.py"]


def f02_a_region_variable_appears(b):
    b["surface"]["variables"].append("PL_FENCE_REGIONS")
    b["surface"]["variable_count"] += 1


def f03_a_tcl_hook_reaches_placement(b):
    b["surface"]["tcl_hooks"]["reaches_a_placement_step"] = True


def f04_a_macro_moves(b):
    for r in b["rows"]:
        if r["kind"] == "macro":
            r["x"] = dec(r["x"]) + dec("10")
            return


def f05_an_arm_a_cell_moves(b):
    r = _arm_a_row(b)
    r["x_dbu"] += STEP
    r["x"] = dec(r["x_dbu"]) / b["design"].units


def f06_a_coordinate_falls_off_the_rounding_grid(b):
    r = _arm_a_row(b)
    r["x"] = dec(r["x"]) + dec("0.001")


def f07_an_orientation_the_flow_cannot_translate(b):
    for c in b["design"].cells:
        if ARM_A_RE.match(unescape(c.inst)):
            c.orient = "R0"
            break
    rebuild(b)


def f08_a_name_keeps_its_escaping(b):
    r = _arm_a_row(b)
    r["inst"] = re_escape_brackets(r["inst"])


def f09_a_pinned_cell_sits_between_two_rows(b):
    """Half a row height up, which is not a row and is still a multiple of
    the flow's rounding step, so it is P09 that fires and not P06."""
    for c in b["design"].cells:
        if c.inst.endswith("g_inv\\[1\\].u_inv") and c.y == 0:
            c.y += RH // 2
            break
    rebuild(b)


def f10_a_pinned_cell_leaves_the_site_grid(b):
    for c in b["design"].cells:
        if c.inst.endswith("g_inv\\[2\\].u_inv") and c.y == RH:
            c.x += 230
            break
    rebuild(b)


def f11_an_arm_c_line_is_emitted(b):
    b["rows"].append({"inst": "u_puf.u_core.g_armc[0].u_roc.u_nand",
                      "kind": "arm_c", "master": "cellA",
                      "x": dec("1.0"), "y": dec("0"), "orient": "N",
                      "x_dbu": 1000, "y_dbu": 0})


def f12_the_fallback_does_not_regenerate(b):
    b["fallback_again"] = b["fallback"].replace("location", "loc", 1)


FAULTS = [
    ("P01", f01_drop_a_pinned_file,
     "one of the files pinned at both tags is missing"),
    ("P02", f02_a_region_variable_appears,
     "a variable that could fence a cell shows up in a later flow"),
    ("P03", f03_a_tcl_hook_reaches_placement,
     "a tcl hook is recorded as reaching a placement step"),
    ("P04", f04_a_macro_moves,
     "a macro is emitted somewhere other than where MACROS puts it"),
    ("P05", f05_an_arm_a_cell_moves,
     "a pinned cell is emitted one site away from its DEF coordinate"),
    ("P06", f06_a_coordinate_falls_off_the_rounding_grid,
     "a coordinate the flow would silently round"),
    ("P07", f07_an_orientation_the_flow_cannot_translate,
     "an orientation the flow has no translation for"),
    ("P08", f08_a_name_keeps_its_escaping,
     "a name goes out with the DEF's backslashes still on it"),
    ("P09", f09_a_pinned_cell_sits_between_two_rows,
     "a pinned cell is not on any row"),
    ("P10", f10_a_pinned_cell_leaves_the_site_grid,
     "a pinned cell sits between two sites"),
    ("P11", f11_an_arm_c_line_is_emitted,
     "Arm C gets placed after all, without a decision"),
    ("P12", f12_the_fallback_does_not_regenerate,
     "the fallback rendering is not reproducible"),
]


def selftest():
    print("gen_placement_cfg selftest")
    clean = check_bundle(fixture_bundle())
    bad = clean.failed()
    print("  fixture, no fault: %d checks, %s"
          % (len(clean.rows), "all pass" if not bad
             else "FAILED " + ", ".join(bad)))
    if bad:
        for r in clean.rows:
            if not r["pass"]:
                print("       %s %s" % (r["id"], r["detail"]))
        return 1

    failures = 0
    for expect, fault, what in FAULTS:
        b = fixture_bundle()
        fault(b)
        got = check_bundle(b).failed()
        ok = got == [expect]
        print("  %-4s %-52s %s" % (expect, what,
                                   "caught" if ok else "MISSED %s" % got))
        if not ok:
            failures += 1

    print()
    if failures:
        print("  %d of %d faults not isolated" % (failures, len(FAULTS)))
        return 1
    print("  %d checks, %d faults, each tripping exactly one"
          % (len(clean.rows), len(FAULTS)))
    return 0


# ---------------------------------------------------------------------------

def load():
    design = read_def(DEF_PATH)
    surface = load_surface()
    rows, config = cfg_rows(design)
    with io.open(TCL_PATH, encoding="utf-8") as fh:
        tcl = fh.read()
    with io.open(REGIONS_PATH, encoding="utf-8") as fh:
        regions = json.load(fh).get("regions", [])
    return design, surface, rows, config, tcl, regions


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json")
    ap.add_argument("--emit", help="directory for the generated cfg")
    ap.add_argument("--emit-fallback",
                    help="write the MANUAL_GLOBAL_PLACEMENTS fragment here")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--refresh-surface", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.refresh_surface:
        fresh = refresh_surface()
        print("refreshed chip/FLOW_SURFACE.json: %s %s, %d variables, "
              "%d steps" % (fresh["flow"]["name"],
                            fresh["flow"]["version_on_disk"],
                            fresh["variable_count"], fresh["step_count"]))
        return 0

    design, surface, rows, config, tcl, regions = load()
    fallback = render_fallback(rows)
    res = run_checks(design, surface, rows, config, tcl, regions,
                     fallback, render_fallback(rows))
    cfg_text = render_cfg(rows)

    macros = [r for r in rows if r["kind"] == "macro"]
    arma = [r for r in rows if r["kind"] == "arm_a"]
    print("placement.cfg for %s %s"
          % (surface["flow"]["name"], surface["flow"]["version_in_ci"]))
    print("  mechanism  MACRO_PLACEMENT_CFG, Odb.ManualMacroPlacement, "
          "step 17, FIRM")
    print("  fallback   MANUAL_GLOBAL_PLACEMENTS, Odb.ManualGlobalPlacement,"
          " step 33, PLACED")
    print("  lines      %d macros + %d Arm A cells + %d Arm C cells = %d"
          % (len(macros), len(arma), 0, len(rows)))
    print("  region     %s"
          % surface["region_binding"]["conclusion"].split(".")[0])
    print()
    for r in res.rows:
        print("  %-4s %-64s %s" % (r["id"], r["name"][:64],
                                   "pass" if r["pass"] else "FAIL"))
    bad = res.failed()
    print("\n  %s" % ("all %d checks pass" % len(res.rows) if not bad
                      else "FAILED: " + ", ".join(bad)))
    for r in res.rows:
        if not r["pass"]:
            print("       %s: %s" % (r["id"], r["detail"]))

    if a.emit:
        if not os.path.isdir(a.emit):
            os.makedirs(a.emit)
        dest = os.path.join(a.emit, CFG_NAME)
        with io.open(dest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(cfg_text)
        print("  wrote %s" % dest)

    if a.emit_fallback:
        with io.open(a.emit_fallback, "w", encoding="utf-8",
                     newline="\n") as fh:
            fh.write(fallback)
        print("  wrote %s" % a.emit_fallback)

    if a.json:
        out = {
            "_comment": [
                "G.3 step 7. What the flow will accept, what it was given,",
                "and the half of the step that has no mechanism behind it.",
                "Regenerated and diffed in CI. See",
                "docs/phaseG_g3_step7.md.",
            ],
            "_hashes_not_in_this_tree": {
                sha256_text(fallback):
                    "the MANUAL_GLOBAL_PLACEMENTS fallback rendering, which "
                    "is generated on demand and deliberately not committed. "
                    "chip/hash_stability.py H06 requires this to be true.",
            },
            "flow": surface["flow"],
            "mechanism": {
                "chosen": "MACRO_PLACEMENT_CFG",
                "step": "Odb.ManualMacroPlacement",
                "step_position": 17,
                "status": "FIRM",
                "file": "src/" + CFG_NAME,
                "config_key": {"MACRO_PLACEMENT_CFG": "dir::" + CFG_NAME},
                "why": "the only mechanism in this flow that fixes a cell "
                       "so detailed placement cannot move it",
                "cost": "the step reads MACRO_PLACEMENT_CFG instead of "
                        "MACROS, so the sixteen hardened macros have to be "
                        "carried in the same file",
            },
            "fallback": {
                "id": "MANUAL_GLOBAL_PLACEMENTS",
                "step": "Odb.ManualGlobalPlacement",
                "step_position": 33,
                "status": "PLACED",
                "why": "runs after global placement, leaves MACROS alone, "
                       "and is not deprecated",
                "cost": "PLACED is not FIRM, so detailed placement may "
                        "move a pinned cell and will only report the "
                        "displacement afterwards",
                "not_committed": True,
                "render": "gen_placement_cfg.py --emit-fallback",
                "sha256": sha256_text(fallback),
                "entries": len(arma),
            },
            "emitted": {
                "path": "dualarm/src/" + CFG_NAME,
                "sha256": sha256_text(cfg_text),
                "lines": len(rows),
                "macros": len(macros),
                "arm_a_cells": len(arma),
                "arm_c_cells": 0,
            },
            "arm_c": {
                "regions_on_record": len(regions),
                "regions_source": "chip/ARMC_REGIONS.json",
                "emitted": 0,
                "blocked_by": surface["region_binding"]["conclusion"],
                "what_an_unconstrained_arm_c_would_be": "sixteen rings "
                    "handed to the same unconstrained placer that produced "
                    "Arm A, which is Arm A's treatment under a second name",
                "decision_belongs_to": "G.2",
            },
            "inputs": {
                "def": sha256_file(DEF_PATH),
                "config": sha256_file(CONFIG_PATH),
                "surface": sha256_file(SURFACE_PATH),
                "regions": sha256_file(REGIONS_PATH),
                "armc_place_tcl": sha256_file(TCL_PATH),
            },
            "checks": res.rows,
        }
        with io.open(a.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(out, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print("  wrote %s" % a.json)

    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
