#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0

"""Run a checked-in deck with PDK paths resolved from the environment.

The historical decks retain their original absolute include paths as provenance.
This runner substitutes only the SKY130 corner-library and standard-cell include
lines in a temporary copy; it never rewrites the checked-in deck.
"""

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from pdk_paths import sky130_spice_paths, spice_path


def portable_text(text):
    corner, cells = sky130_spice_paths()
    text, lib_count = re.subn(
        r'(?m)^\.lib\s+.*sky130\.lib\.spice"?\s+(\S+)\s*$',
        lambda match: f".lib {spice_path(corner)} {match.group(1)}",
        text,
    )
    text, cell_count = re.subn(
        r'(?m)^\.include\s+.*sky130_fd_sc_hd\.spice"?\s*$',
        f".include {spice_path(cells)}",
        text,
    )
    if lib_count != 1 or cell_count != 1:
        raise ValueError(
            f"expected one SKY130 .lib and one standard-cell .include; "
            f"found {lib_count} and {cell_count}"
        )
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("deck", type=Path)
    parser.add_argument("--log", type=Path,
                        help="ngspice log path (default: <deck stem>_out.txt)")
    args = parser.parse_args()

    ngspice = shutil.which(os.environ.get("NGSPICE", "ngspice"))
    if not ngspice:
        raise SystemExit("ngspice not found; install it or set NGSPICE")
    deck = args.deck.resolve()
    log = (args.log or deck.with_name(deck.stem + "_out.txt")).resolve()
    rewritten = portable_text(deck.read_text())

    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".spice", prefix="portable_",
                dir=deck.parent, delete=False) as handle:
            handle.write(rewritten)
            temp_name = handle.name
        completed = subprocess.run(
            [ngspice, "-b", temp_name, "-o", str(log)],
            cwd=deck.parent,
            check=False,
        )
        return completed.returncode
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
