#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
"""When the gds job fails, say why somewhere a signed-out reader can see it.

Run 72 on 6 September failed inside the gds job after 2 minutes 41 seconds
and I could not find out why. The flow's own account of the failure lives in
runs/wokwi/ on a runner that is deleted when the job ends. What survives is
the GDS_logs artifact, which needs an API token, and the job log, which needs
a signed-in session. So the one thing I needed was the one thing behind a
login, and a build I cannot read the failure of is a build I cannot fix.

Three things are readable on a public run page with no account at all: the
job names, their durations, and the annotations. Annotations are the only one
of those that can carry text I choose. So this script reads the run directory
while it still exists and prints the failure into that channel, plus the job
summary and stdout for anyone who does have an account.

It does not diagnose anything. It finds the step the flow stopped in, quotes
what that step said, and quotes the flow's error.log, and it is careful about
which step it names because naming the wrong one is worse than naming none.

Checks, which run on real input as well as in the selftest:

  R01  a run directory was found and holds at least one numbered step
  R02  steps are ordered by their number and not by their name
  R03  the step named did not complete, so it is the one that stopped
  R04  every quoted line comes from the named step or from error.log
  R05  a log too big to read whole is read from its end and said to be
  R06  the annotation fits inside GitHub's per-annotation limit
  R07  the annotation and the summary name the same step
  R08  when the failing log names its own diagnosis above the error line,
       the quote carries that line too
  R09  when the failing step reported changing the design, the quote
       carries the counts

Which step to name took three goes. Sorting the directory names puts
44-openroad-detailedrouting behind 9-checker-netlistassignstatements, so the
number orders them. Then LibreLane makes a step's directory and copies
config.json into it before the step runs, so the highest numbered directory
can be one that never got going, and walking back to the last directory
holding a log was the second rule. That one named step 18, which had
finished cleanly, whenever step 19 died without writing anything, and quoted
18's log as though it were the failure. The rule now is the last step that
did not finish and did write something, falling back to the last that did
not finish. R03 is the check that survives all of that: if the step named
has a state_out.json then every step completed, LibreLane got to the end,
and whatever failed is outside it.

A selection rule is tested by asserting what it selects. Asking a check to
catch a wrong selection means writing the selection twice and comparing it
with itself, which is how the first R03 came to pass on every fixture,
including the ones planted to break it.

R08 and the lead-in exist because of run 73 on 7 September. The annotation
worked, and all it said was

    [ERROR DPL-0033] detailed placement checks failed.

which names the step and nothing else. OpenROAD lists what it found and
then stops, so the line that says which of the six placement checks failed,
and the lines naming the instances, were sitting directly above the one line
that got quoted. A tool's last line is where it gives up, not where it says
why. So the quote now carries the lines above the first error as well, and
separately the warning-marked lines above it, because when the list in
between runs to hundreds of instances the diagnosis is pushed out of the
lead-in window. R08 is the check, and it looks for that line itself rather
than trusting the selector.

R09 is the other half of the same day. Step 32 is repair_design, which
resizes gates and inserts buffers before it legalizes, and it says how many
of each it did. Those lines decide whether the step changed the cells that
were pinned or only worked around them, and they sit above everything the
placement check prints, which is further from the error than any lead-in
worth carrying. So they get their own sweep. A count is the cheapest fact a
log gives you and it was being thrown away.

R05 exists because the first version of read_text read the first two
megabytes of a log. Detailed routing writes tens of megabytes and puts the
reason it stopped on the last line, so that version would have quoted the
opening banner of the longest log in the flow and called it the error. It
reads backwards now.

R05 itself asks the filesystem which quoted files are over the limit and
requires the report to have said so about exactly those. No fixture can make
that disagree from the input side, because both sides come from the same
file: it is a consistency check against someone later changing the limit in
one place and not the other. What the selftest plants instead is the bug it
was written for, an error sitting past the limit at the end of a long log,
and asserts the quote carries it.

Scope. This runs after a failure and its own job is to report, so in report
mode a failed check is printed and the exit status stays 0: the alternative
is a reporter that fails the job it was called to explain. --strict turns
that around for use outside CI. --selftest exits non-zero, which is how the
evidence gate runs it.

    python3 chip/ci_failure_report.py --selftest
    python3 chip/ci_failure_report.py --run-dir runs/wokwi --annotate

"""

import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# GitHub truncates an annotation message past this. The real ceiling is
# quoted as 4096 characters; the report is held under a round 3600 so that
# the percent-encoding, which can treble the length of a run of newlines,
# cannot push a report that looked fine over the edge.
ANNOTATION_LIMIT = 3600

# One line of an OpenROAD log can carry a whole net name list. Past this a
# line is cut rather than allowed to spend the entire annotation budget.
LINE_LIMIT = 300

STEP_RX = re.compile(r"^(\d+)-(.+)$")

# Lines worth lifting out of a long log. Ordered loosely by how specific
# they are, and every one of them was seen in a real LibreLane or OpenROAD
# log rather than guessed at.
ERROR_RX = [
    re.compile(r"^\s*\[ERROR"),
    re.compile(r"^\s*ERROR[: ]"),
    re.compile(r"^%Error"),
    re.compile(r"^\s*Error:"),
    re.compile(r"^Traceback \(most recent call last\)"),
    re.compile(r"^\w*(Error|Exception): "),
    re.compile(r"child process exited abnormally"),
    re.compile(r"invalid command name"),
    re.compile(r'can\'t read "'),
    re.compile(r"^\s*Assertion.*failed"),
    re.compile(r"AssertionError"),
    re.compile(r"Fatal|FATAL"),
]

# Absolute runner paths are noise, they differ every run, and they eat the
# annotation budget. /home/runner/work/tt-ro-puf/tt-ro-puf/runs/... becomes
# runs/... and nothing is lost.
WARN_RX = [
    re.compile(r"^\s*\[WARNING"),
    re.compile(r"^\s*WARNING[: ]"),
    re.compile(r"^%Warning"),
]

# A line where a step says it changed something, which is a verb and a
# number on the same line. The number is what makes it a report rather
# than an announcement of intent, and the verbs are the ones the tools in
# this flow use: OpenROAD's resizer writes "Inserted 18 buffers in 12
# nets" and "Resized 42 instances", the legalizer writes "Mirrored 578
# instances".
CHANGE_RX = re.compile(
    r"\b(resiz|upsiz|downsiz|insert|remov|repair|replac|swap|buffer"
    r"|mirror|legaliz|clon)\w*", re.I)
DIGIT_RX = re.compile(r"\d")

# How many lines above the first error to carry, how many warning-marked
# and change-marked lines to sweep out of what sits above it, and what
# marks a gap between two runs of quoted lines. The three counts are read
# at call time and not bound as defaults, so the selftest can turn a
# sweep off and prove its check is able to fail. They are small because
# the annotation limit is 3600 characters and a trimmed annotation eats
# its own middle, which is exactly where a sweep lands.
LEAD_IN = 12
WARN_KEEP = 6
CHANGE_KEEP = 6
ELISION = "[...]"

RUNNER_PATH_RX = re.compile(r"/home/runner/work/[^/]+/[^/]+/")


# ------------------------------------------------------------------ reading


READ_LIMIT = 2 * 1024 * 1024


def read_text(path, limit=READ_LIMIT):
    """Read a log from its end, and say when that is not the whole file.

    The first version read the first two megabytes. Detailed routing writes
    tens of megabytes and the reason it stopped is on the last line, so that
    version would have quoted the opening banner of the longest log in the
    flow and called it the error. Reading backwards is the whole point.

    Returns (text, truncated).
    """
    try:
        size = os.path.getsize(path)
        with io.open(path, "rb") as fh:
            if size > limit:
                fh.seek(size - limit)
            blob = fh.read()
    except OSError:
        return "", False
    text = blob.decode("utf-8", "replace")
    if size > limit:
        # a seek lands mid-line; drop the partial one
        text = text.split("\n", 1)[-1]
    return text, size > limit


def find_run_dir(explicit, root):
    """Where the flow left its run directory.

    CI hardens at the workspace root, so runs/wokwi. On this machine the
    same tree is under gds_build/. Both are tried, the explicit one first,
    and nothing is guessed beyond those two.
    """
    if explicit:
        return explicit if os.path.isdir(explicit) else None
    for rel in ("runs/wokwi", "gds_build/runs/wokwi"):
        cand = os.path.join(root, rel)
        if os.path.isdir(cand):
            return cand
    return None


def list_steps(run_dir):
    """Every numbered step directory, ordered by its number.

    The number is what orders them. Sorting the names puts 9-checker after
    44-openroad and the report then blames a step that finished forty
    minutes earlier.
    """
    steps = []
    try:
        names = os.listdir(run_dir)
    except OSError:
        return steps
    for name in names:
        path = os.path.join(run_dir, name)
        if not os.path.isdir(path):
            continue
        m = STEP_RX.match(name)
        if not m:
            continue
        steps.append({"n": int(m.group(1)), "name": name, "path": path})
    steps.sort(key=lambda s: s["n"])
    return steps


def step_files(step):
    """Files the step wrote, newest last, directories ignored."""
    out = []
    for name in sorted(os.listdir(step["path"])):
        p = os.path.join(step["path"], name)
        if os.path.isfile(p):
            out.append((name, p, os.path.getsize(p)))
    return out


def step_logs(step):
    """The step's own logs, longest first.

    A step writes config.json and state_in.json before it runs anything, so
    those are never the interesting file. What is left is the log, and when
    a step writes more than one the biggest is the one that got to say
    something.
    """
    skip = {"config.json", "state_in.json", "state_out.json", "runtime.txt"}
    logs = [(n, p, s) for (n, p, s) in step_files(step) if n not in skip]
    logs.sort(key=lambda t: -t[2])
    return logs


def tail(text, n):
    lines = text.splitlines()
    return lines[-n:] if len(lines) > n else lines


def error_indices(text, keep=12):
    """Indices of the lines that look like the reason, last `keep` of them.

    A traceback's last line is the useful one and it is already matched, so
    the indices deduplicate themselves: one line contributes once however
    many patterns it matches.
    """
    hits = []
    for i, line in enumerate(text.splitlines()):
        for rx in ERROR_RX:
            if rx.search(line):
                hits.append(i)
                break
    return hits[-keep:]


def error_lines(text, keep=12):
    """Lines that look like the reason."""
    lines = text.splitlines()
    return [lines[i] for i in error_indices(text, keep)]


def warn_indices(text, before, keep=None):
    """Warning-marked lines above `before`, last `keep` of them."""
    if keep is None:
        keep = WARN_KEEP
    hits = []
    for i, line in enumerate(text.splitlines()):
        if i >= before:
            break
        for rx in WARN_RX:
            if rx.search(line):
                hits.append(i)
                break
    return hits[-keep:] if keep else []


def change_indices(text, before, keep=None):
    """Lines above `before` where the step says what it changed."""
    if keep is None:
        keep = CHANGE_KEEP
    hits = []
    for i, line in enumerate(text.splitlines()):
        if i >= before:
            break
        if CHANGE_RX.search(line) and DIGIT_RX.search(line):
            hits.append(i)
    return hits[-keep:] if keep else []


def quote_indices(text, keep=12, lead=None, warns=None, changes=None):
    """Which lines of a step log to quote, as indices into it.

    Four sources: the lines that match an error marker, the non-blank
    lines immediately above the first of those, the warning-marked lines
    above it, and the lines where the step said what it changed. The last
    two are not the second with a bigger window - check_placement can list
    several hundred instances between its verdict and the error, and
    repair_design's counts are above all of that, so widening the window
    far enough to reach either would spend the whole annotation on
    instance names.
    """
    if lead is None:
        lead = LEAD_IN
    lines = text.splitlines()
    errs = error_indices(text, keep)
    if not errs:
        return []
    first = errs[0]
    idx = set(errs)
    idx.update(i for i in range(max(0, first - lead), first)
               if lines[i].strip())
    idx.update(warn_indices(text, first, warns))
    idx.update(change_indices(text, first, changes))
    return sorted(idx)


def lines_at(text, idx):
    """The chosen lines, with a marker wherever a run of them was skipped."""
    lines = text.splitlines()
    out, prev = [], None
    for i in idx:
        if prev is not None and i != prev + 1:
            out.append(ELISION)
        out.append(lines[i])
        prev = i
    return out


def clean(line):
    return RUNNER_PATH_RX.sub("", line.rstrip())


# ------------------------------------------------------------------ collect


def collect(run_dir):
    """Everything the report needs, as plain data.

    Kept separate from rendering so the checks can be run against the data
    rather than against a string that has already been cut to fit.
    """
    rep = {
        "run_dir": run_dir,
        "steps": [],
        "entered": None,
        "reported": None,
        "completed": 0,
        "quotes": [],
        "sources": [],
        "empty_note": "",
        "truncated": [],
        "completed_all": False,
        "flow": {},
    }
    if run_dir is None:
        return rep

    steps = list_steps(run_dir)
    rep["steps"] = [{"n": s["n"], "name": s["name"]} for s in steps]
    if not steps:
        return rep

    rep["entered"] = steps[-1]["name"]

    # Which step to name. A step that finished writes state_out.json, so
    # the ones without it are the candidates. Of those, the last that also
    # wrote something is the one holding the reason: LibreLane makes the
    # directory and copies config.json in before the step runs, so an
    # unfinished directory with nothing else in it is a step that never got
    # going and it must not hide the one below it that did.
    #
    # Walking back to the last step with any log at all was the first rule
    # and it was wrong in the other direction: with step 19 dead and silent
    # it named step 18, which had finished cleanly, and quoted 18's log as
    # if it were the failure. Both halves are needed.
    def done(st):
        return os.path.exists(os.path.join(st["path"], "state_out.json"))

    unfinished = [st for st in steps if not done(st)]
    with_output = [st for st in unfinished if step_logs(st)]
    if with_output:
        reported = with_output[-1]
    elif unfinished:
        reported = unfinished[-1]
    else:
        reported = steps[-1]
    rep["reported"] = reported["name"]
    rep["completed"] = sum(
        1 for s in steps if os.path.exists(
            os.path.join(s["path"], "state_out.json")))
    rep["completed_all"] = rep["completed"] == len(steps)

    # error.log first. LibreLane writes the exception that stopped the flow
    # there, and it is short.
    err_path = os.path.join(run_dir, "error.log")
    if os.path.exists(err_path) and os.path.getsize(err_path) > 0:
        body, cut = read_text(err_path)
        picked = error_lines(body) or tail(body, 12)
        if picked:
            rep["quotes"].append(("error.log", [clean(l) for l in picked],
                                  cut))
            rep["sources"].append(err_path)

    # then the named step's own log, unless the flow finished, in which
    # case that log is a success report and quoting it would read as the
    # error. error.log above still applies: it is empty on a clean run.
    logs = [] if rep["completed_all"] else step_logs(reported)
    if logs:
        name, path, _ = logs[0]
        body, cut = read_text(path)
        if cut:
            rep["truncated"].append("%s/%s" % (reported["name"], name))
        picked = lines_at(body, quote_indices(body))
        if not picked:
            picked = tail(body, 20)
        if picked:
            rep["quotes"].append(
                ("%s/%s" % (reported["name"], name),
                 [clean(l) for l in picked], cut))
            rep["sources"].append(path)
        else:
            rep["empty_note"] = ("%s/%s is present and empty"
                                 % (reported["name"], name))
    elif rep["completed_all"]:
        rep["empty_note"] = ("every step finished, so look at the job's "
                             "later steps rather than at the flow")
    else:
        rep["empty_note"] = ("%s wrote no log of its own"
                             % reported["name"])

    # version and pdk, so two runs can be told apart at a glance
    for fn, keys in (("pdk.json", ("name", "version")),
                     ("resolved.json", ("PDK", "DESIGN_NAME"))):
        p = os.path.join(run_dir, fn)
        if not os.path.exists(p):
            continue
        try:
            data = json.loads(read_text(p)[0])
        except ValueError:
            continue
        for k in keys:
            if isinstance(data, dict) and k in data:
                rep["flow"][k] = data[k]
    return rep


# ------------------------------------------------------------------ render


def headline(rep):
    if rep["run_dir"] is None:
        return "no LibreLane run directory, so the flow never started"
    if not rep["steps"]:
        return "run directory is empty, so the flow never entered a step"
    if rep["completed_all"]:
        return ("LibreLane ran to the end, %d steps, so the job failed "
                "outside it" % len(rep["steps"]))
    return "LibreLane stopped in %s" % rep["reported"]


def body_lines(rep):
    out = []
    if rep["flow"]:
        out.append("flow: " + ", ".join(
            "%s %s" % (k, v) for k, v in sorted(rep["flow"].items())))
    if rep["steps"]:
        # "31 of 32 entered" was the old wording and it reads as though
        # 31 steps were entered. It meant 31 of the 32 that were entered
        # finished, which is the opposite end of the sentence.
        out.append("steps: %d entered, %d of them finished, last entered %s"
                   % (len(rep["steps"]), rep["completed"], rep["entered"]))
    if rep["empty_note"]:
        out.append(rep["empty_note"])
    for label, lines, cut in rep["quotes"]:
        out.append("")
        out.append("%s:%s" % (label, " (read from the end, the file is "
                              "longer than the read limit)" if cut else ""))
        for line in lines:
            out.append("  " + line[:LINE_LIMIT])
    if not rep["quotes"] and not rep["empty_note"]:
        out.append("nothing was quoted and no step left output to quote")
    return out


def encode_annotation(text):
    """GitHub's workflow-command escaping. Order matters: % first."""
    return (text.replace("%", "%25")
                .replace("\r", "%0D")
                .replace("\n", "%0A"))


TRIM_MARK = "  ... trimmed to fit the annotation ..."


def render_annotation(rep, trim=True):
    """The workflow command, trimmed from the middle until it fits.

    The head says where the flow stopped and the tail carries the error, so
    when something has to go it goes from between them. trim=False exists
    only so the selftest can prove R06 is able to fail; nothing calls it
    that way in earnest.
    """
    title = headline(rep)
    body = "\n".join(body_lines(rep))
    enc = encode_annotation(body)
    if not trim:
        return "::error title=%s::%s" % (title.replace("::", " "), enc)
    while len(enc) > ANNOTATION_LIMIT:
        lines = body.splitlines()
        if len(lines) <= 3:
            body = body[:ANNOTATION_LIMIT // 3]
            enc = encode_annotation(body)
            break
        cut = len(lines) // 2
        if lines[cut] == TRIM_MARK:
            del lines[cut + 1]
        else:
            lines[cut] = TRIM_MARK
        body = "\n".join(lines)
        enc = encode_annotation(body)
    return "::error title=%s::%s" % (title.replace("::", " "), enc)


def render_summary(rep):
    out = ["## gds failed", "", headline(rep), ""]
    if rep["steps"]:
        out.append("| step | output |")
        out.append("|---|---|")
        for s in rep["steps"]:
            mark = ("**stopped here**" if s["name"] == rep["reported"]
                    else "ran")
            out.append("| %s | %s |" % (s["name"], mark))
        out.append("")
    for label, lines, cut in rep["quotes"]:
        out.append("### %s%s" % (label, " (tail only)" if cut else ""))
        out.append("")
        out.append("```")
        out.extend(lines)
        out.append("```")
        out.append("")
    if rep["empty_note"]:
        out.append(rep["empty_note"])
        out.append("")
    return "\n".join(out)


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


def run_checks(rep, run_dir):
    res = Results()
    steps = list_steps(run_dir) if run_dir else []

    res.add("R01", "a run directory with at least one numbered step",
            bool(run_dir) and bool(steps),
            "run_dir=%s steps=%d" % (run_dir, len(steps)))

    numbers = [s["n"] for s in steps]
    res.add("R02", "steps ordered by number, not by name",
            numbers == sorted(numbers),
            "order %s" % (numbers[:6] + ["..."] if len(numbers) > 6
                          else numbers))

    named = [s for s in steps if s["name"] == rep["reported"]]
    if named:
        done = os.path.exists(os.path.join(named[0]["path"],
                                           "state_out.json"))
        res.add("R03", "the step named did not complete",
                not done,
                "every step completed, so LibreLane finished and the "
                "failure is outside it" if done
                else "%s did not finish" % rep["reported"])
    else:
        res.add("R03", "the step named did not complete",
                rep["reported"] is None, "no steps")

    allowed = set()
    if run_dir:
        allowed.add(os.path.abspath(os.path.join(run_dir, "error.log")))
        for s in steps:
            if s["name"] == rep["reported"]:
                for _, p, _ in step_logs(s):
                    allowed.add(os.path.abspath(p))
    stray = [p for p in rep["sources"] if os.path.abspath(p) not in allowed]

    # The paths were the whole of R04 until the quote stopped being a
    # contiguous tail. Once lines are chosen out of the middle of a file
    # and a marker is put between them, "it came from an allowed file" is
    # no longer the same claim as "it is a line of that file", so check
    # the lines as well.
    off = []
    for (lbl, lines, _), path in zip(rep["quotes"], rep["sources"]):
        try:
            body, _ = read_text(path)
        except OSError:
            off.append("%s: could not be re-read" % lbl)
            continue
        pool = set(clean(l) for l in body.splitlines())
        for line in lines:
            if line != ELISION and line not in pool:
                off.append("%s: %r" % (lbl, line[:60]))
    res.add("R04", "every quoted line is a line of that step's log or of "
            "error.log",
            not stray and not off,
            ", ".join(["stray %s" % p for p in stray] + off) or "none")

    # Independent of what collect recorded: ask the filesystem which of the
    # quoted files is bigger than the read limit, and require the report to
    # have said so about exactly those.
    big = set()
    for path in rep["sources"]:
        try:
            if os.path.getsize(path) > READ_LIMIT:
                big.add(os.path.basename(path))
        except OSError:
            pass
    said = set(os.path.basename(lbl) for (lbl, _, cut) in rep["quotes"]
               if cut)
    res.add("R05", "a log too big to read whole is read from its end and "
            "said to be",
            said == big,
            "over the limit %s, reported as trimmed %s"
            % (sorted(big) or "none", sorted(said) or "none"))

    ann = render_annotation(rep)
    payload = ann.split("::", 2)[-1]
    res.add("R06", "the annotation fits GitHub's per-annotation limit",
            len(payload) <= ANNOTATION_LIMIT,
            "%d of %d characters" % (len(payload), ANNOTATION_LIMIT))

    summ = render_summary(rep)
    head = headline(rep)
    res.add("R07", "annotation and summary name the same step",
            head in ann and head in summ,
            "headline %r" % head)

    # Independent of what quote_indices chose: go back to the step log and
    # look for the two things a step says about itself above the point it
    # stopped. R08 wants the last warning-marked line, which is where
    # OpenROAD names the check that failed. R09 wants the last line where
    # the step said what it changed. Both are searched for here rather
    # than read off the selector, because a check that asks the selector
    # what it selected is the selector written twice.
    def carried(finder):
        for (lbl, lines, _), path in zip(rep["quotes"], rep["sources"]):
            if os.path.basename(path) == "error.log":
                continue
            try:
                body, _ = read_text(path)
            except OSError:
                continue
            errs = error_indices(body)
            if not errs:
                continue
            above = finder(body, errs[0])
            if not above:
                continue
            line = clean(body.splitlines()[above[-1]])
            return lbl, line, line in lines
        return "", None, True

    where, want, held = carried(lambda b, e: warn_indices(b, e, keep=1))
    res.add("R08", "the quote carries the log's own diagnosis above the "
            "error line",
            held,
            "no warning line above the error, nothing to carry"
            if want is None else "%s: %r" % (where, want[:70]))

    where, want, held = carried(lambda b, e: change_indices(b, e, keep=1))
    res.add("R09", "the quote carries what the step reported changing",
            held,
            "the step reported changing nothing, nothing to carry"
            if want is None else "%s: %r" % (where, want[:70]))
    return res


# ------------------------------------------------------------------ fixture


def wr(path, text):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


REAL_ERROR = """\
[INFO ODB-0227] LEF file: sky130A.tlef
[INFO ODB-0128] Design: tt_um_nikodemetrashvili20_ro_puf
Placing the following macros:
[ERROR TAP-0001] Endcap cell overlaps a fixed instance at (276000 106080).
Error: tapcell.tcl, 21 TAP-0001
child process exited abnormally
"""


DPL_DIAGNOSIS = (
    "[INFO RSZ-0027] Found 41 slew violations.\n"
    "[INFO RSZ-0028] Found 6 capacitance violations.\n"
    "[INFO RSZ-0030] Inserted 18 buffers in 12 nets.\n"
    "[INFO RSZ-0031] Resized 42 instances.\n"
    "[INFO DPL-0001] Placement Analysis\n"
    "[WARNING DPL-0005] Overlap check failed (12).\n"
    + "".join("  u_puf.u_core.g_ro_bank[%d].u_ro.g_inv[%d].u_inv overlaps "
              "u_puf.u_core.g_ro_bank[%d].u_ro.g_inv[%d].u_inv\n"
              % (i // 32, i % 32, i // 32, (i % 32) + 1)
              for i in range(200))
    + "[ERROR DPL-0033] detailed placement checks failed.\n"
      "Error: repair_design.tcl, 68 DPL-0033\n"
)


def build_fixture(tmp, lexical_trap=False, empty_tail=False,
                  no_step_log=False, no_error_lines=False,
                  long_lines=False, big_log=False, all_completed=False,
                  distant_diagnosis=False):
    """A run directory shaped like a real one.

    Nine steps, the last of which died. Each variant plants one way of
    getting the report wrong.
    """
    run = os.path.join(tmp, "runs", "wokwi")
    os.makedirs(run)
    wr(os.path.join(run, "flow.log"), "Starting...\n")
    wr(os.path.join(run, "pdk.json"), json.dumps({"name": "sky130A"}))

    names = [
        (1, "verilator-lint"), (5, "yosys-jsonheader"),
        (6, "yosys-synthesis"), (9, "checker-netlistassignstatements"),
        (13, "openroad-floorplan"), (16, "odb-setpowerconnections"),
        (17, "odb-manualmacroplacement"), (18, "openroad-cutrows"),
        (19, "openroad-tapendcapinsertion"),
    ]
    if lexical_trap:
        # 44 sorts before 9 as a string. It is the one that failed.
        names.append((44, "openroad-detailedrouting"))

    last = names[-1]
    for n, nm in names:
        d = os.path.join(run, "%d-%s" % (n, nm))
        os.makedirs(d)
        wr(os.path.join(d, "config.json"), "{}")
        wr(os.path.join(d, "state_in.json"), "{}")
        if (n, nm) != last or all_completed:
            wr(os.path.join(d, "state_out.json"), "{}")
        if (n, nm) != last:
            wr(os.path.join(d, "%s.log" % nm.split("-")[0]), "fine\n")

    ld = os.path.join(run, "%d-%s" % (last[0], last[1]))
    if not no_step_log:
        text = REAL_ERROR
        if no_error_lines:
            text = "".join("line %d of nothing interesting\n" % i
                           for i in range(40))
        if long_lines:
            text = REAL_ERROR + "".join(
                "[ERROR PAD-%04d] %s\n" % (i, "pad " * 120)
                for i in range(12))
        if distant_diagnosis:
            text = DPL_DIAGNOSIS
        if big_log:
            filler = "[INFO] routing net %d of very many\n"
            text = ("".join(filler % i
                            for i in range(READ_LIMIT // 30 + 5000))
                    + REAL_ERROR)
        wr(os.path.join(ld, "openroad.log"), text)

    if empty_tail:
        # a step the flow created and died before writing into
        d = os.path.join(run, "%d-%s" % (last[0] + 1, "openroad-nextstep"))
        os.makedirs(d)
        wr(os.path.join(d, "config.json"), "{}")
        wr(os.path.join(d, "state_in.json"), "{}")

    return run


def run_fixture(tmp, **kwargs):
    run = build_fixture(tmp, **kwargs)
    rep = collect(run)
    return rep, run_checks(rep, run)


FAULTS = (
    ("R03", "a run where every step completed, so LibreLane finished and "
            "the failure is somewhere else", dict(all_completed=True)),
)


def fresh(tmp):
    import shutil
    shutil.rmtree(tmp)
    os.makedirs(tmp)


def selftest():
    import shutil
    import tempfile
    ok = True
    print("ci_failure_report selftest")
    tmp = tempfile.mkdtemp(prefix="cifix")

    def bad(msg):
        print("  FAIL  %s" % msg)

    try:
        rep, res = run_fixture(tmp)
        if res.failed():
            bad("clean fixture fails %s" % ", ".join(res.failed()))
            for r in res.rows:
                if not r["pass"]:
                    print("        %s %s" % (r["id"], r["detail"]))
            ok = False
        else:
            print("  clean fixture passes all %d checks, and names %s"
                  % (len(res.rows), rep["reported"]))
        if "TAP-0001" not in render_annotation(rep):
            bad("the annotation does not carry the OpenROAD error line")
            ok = False
        else:
            print("  ok    the annotation carries the OpenROAD error")

        # Three shaped inputs where the answer is a value, not a failure.
        # A selection rule is tested by asserting what it selects; asking
        # a check to catch a wrong selection means writing the wrong
        # selection twice and comparing it with itself.
        fresh(tmp)
        rep, res = run_fixture(tmp, lexical_trap=True)
        if rep["reported"] == "44-openroad-detailedrouting" \
                and not res.failed():
            print("  ok    44 sorts after 9 and the report says so")
        else:
            bad("lexical trap: named %s, failed %s"
                % (rep["reported"], ", ".join(res.failed()) or "nothing"))
            ok = False

        fresh(tmp)
        rep, res = run_fixture(tmp, empty_tail=True)
        if rep["entered"] == "20-openroad-nextstep" \
                and rep["reported"] == "19-openroad-tapendcapinsertion" \
                and not res.failed():
            print("  ok    an empty step directory does not hide the step "
                  "that failed")
        else:
            bad("empty tail: entered %s named %s, failed %s"
                % (rep["entered"], rep["reported"],
                   ", ".join(res.failed()) or "nothing"))
            ok = False

        fresh(tmp)
        rep, res = run_fixture(tmp, no_step_log=True)
        if not rep["quotes"] and "wrote no log" in rep["empty_note"] \
                and not res.failed():
            print("  ok    a step that wrote nothing is reported as one")
        else:
            bad("no step log: quotes=%d note=%r failed=%s"
                % (len(rep["quotes"]), rep["empty_note"],
                   ", ".join(res.failed()) or "nothing"))
            ok = False

        fresh(tmp)
        rep, res = run_fixture(tmp, no_error_lines=True)
        if rep["quotes"] and not res.failed():
            print("  ok    a log with no error line in it is quoted anyway")
        else:
            bad("no error lines: quotes=%d failed=%s"
                % (len(rep["quotes"]), ", ".join(res.failed())))
            ok = False

        # R06 cannot fail on real input, because the renderer trims until
        # it fits. It still earns a planted fault, the same way the
        # unescaping-injectivity check in the SPEF census does: the fault
        # turns the trimmer off, so the check is known to work on the day
        # something gets past it.
        fresh(tmp)
        rep, res = run_fixture(tmp, long_lines=True)
        ann = render_annotation(rep)
        untrimmed = render_annotation(rep, trim=False)
        if res.failed():
            bad("long lines: trimmed report still fails %s"
                % ", ".join(res.failed()))
            ok = False
        elif TRIM_MARK.strip() not in ann:
            bad("long lines: nothing was trimmed")
            ok = False
        elif len(untrimmed.split("::", 2)[-1]) <= ANNOTATION_LIMIT:
            bad("long lines: the fixture does not overflow, so R06 is "
                "not being tested")
            ok = False
        else:
            print("  ok    R06  an oversized annotation is trimmed and "
                  "fits, and overflows when the trimmer is off")

        # The bug R05 was written for: the error is the last line of a
        # log longer than the read limit. Reading from the front misses it
        # and quotes the banner instead.
        fresh(tmp)
        rep, res = run_fixture(tmp, big_log=True)
        quoted = " ".join(l for (_, lines, _) in rep["quotes"] for l in lines)
        cut = [lbl for (lbl, _, c) in rep["quotes"] if c]
        if "TAP-0001" in quoted and cut and not res.failed():
            print("  ok    an error past the read limit is still quoted, "
                  "and the quote says the file was read from its end")
        else:
            bad("big log: TAP-0001 quoted %s, trimmed %s, failed %s"
                % ("TAP-0001" in quoted, cut,
                   ", ".join(res.failed()) or "nothing"))
            ok = False

        # The bug R08 was written for, and it is run 73's annotation:
        # the error line alone. The diagnosis is two hundred instance
        # lines above it, far outside the lead-in, so the warning sweep
        # is the only thing that can reach it. As with R06 the fault
        # turns the mechanism off, because with it on nothing can miss.
        global WARN_KEEP, CHANGE_KEEP
        fresh(tmp)
        run = build_fixture(tmp, distant_diagnosis=True)
        rep = collect(run)
        res = run_checks(rep, run)
        ann = render_annotation(rep)
        hw, hc = WARN_KEEP, CHANGE_KEEP
        WARN_KEEP, CHANGE_KEEP = 0, 0
        try:
            blind = run_checks(collect(run), run)
        finally:
            WARN_KEEP, CHANGE_KEEP = hw, hc
        if res.failed():
            bad("distant diagnosis: fails %s" % ", ".join(res.failed()))
            ok = False
        elif "DPL-0005" not in ann:
            bad("distant diagnosis: the annotation does not carry the "
                "line that says which check failed")
            ok = False
        elif "RSZ-0031" not in ann:
            bad("distant diagnosis: the annotation does not carry what "
                "the step reported changing")
            ok = False
        elif "DPL-0033" not in ann:
            bad("distant diagnosis: the annotation lost the error line")
            ok = False
        elif sorted(blind.failed()) != ["R08", "R09"]:
            bad("distant diagnosis: with both sweeps off, R08 and R09 "
                "should be the checks that fail, and %s did"
                % (", ".join(blind.failed()) or "nothing"))
            ok = False
        else:
            print("  ok    R08 R09  a diagnosis and a resize count two "
                  "hundred lines above the error are both quoted, and "
                  "both are missed when the sweeps are off")

        for want, label, kwargs in FAULTS:
            fresh(tmp)
            rep, res = run_fixture(tmp, **kwargs)
            tripped = set(res.failed())
            if tripped == {want}:
                print("  ok    %-4s %s" % (want, label))
            elif want in tripped:
                bad("%-4s %s -- also tripped %s"
                    % (want, label, ", ".join(sorted(tripped - {want}))))
                ok = False
            else:
                bad("%-4s %s -- tripped %s"
                    % (want, label,
                       ", ".join(sorted(tripped)) or "nothing"))
                ok = False

        # no run directory at all
        rep = collect(None)
        res = run_checks(rep, None)
        if res.failed() == ["R01"] and "never started" in headline(rep):
            print("  ok    R01  a missing run directory is reported as one")
        else:
            bad("R01  failed %s, headline %r"
                % (", ".join(res.failed()), headline(rep)))
            ok = False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n  %s" % ("selftest passed" if ok else "SELFTEST FAILED"))
    return 0 if ok else 1


# --------------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run-dir", default=None)
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--annotate", action="store_true",
                    help="emit a ::error:: workflow command")
    ap.add_argument("--summary", default=os.environ.get(
        "GITHUB_STEP_SUMMARY"),
        help="file to append the markdown summary to")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if a check on the report fails")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    run_dir = find_run_dir(a.run_dir, os.path.abspath(a.root))
    rep = collect(run_dir)
    res = run_checks(rep, run_dir)

    print(headline(rep))
    for line in body_lines(rep):
        print(line)

    if a.annotate:
        print(render_annotation(rep))
    if a.summary:
        try:
            with io.open(a.summary, "a", encoding="utf-8",
                         newline="\n") as fh:
                fh.write(render_summary(rep))
                fh.write("\n")
        except OSError as exc:
            print("could not write the summary: %s" % exc)

    bad = res.failed()
    if bad:
        print("\nreport checks failed: %s" % ", ".join(bad))
        for r in res.rows:
            if not r["pass"]:
                print("  %s %s -- %s" % (r["id"], r["name"], r["detail"]))
    return 1 if (bad and a.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
