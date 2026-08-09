#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0

"""Resolve the two SKY130 ngspice files used by the local deck generators."""

import os
import tempfile
from pathlib import Path


def sky130_spice_paths():
    """Return (corner library, standard-cell SPICE) from PDK_ROOT and PDK."""
    raw_root = os.environ.get("PDK_ROOT")
    if not raw_root:
        raise RuntimeError(
            "PDK_ROOT is not set. Point it at the directory containing sky130A "
            "(or the process named by PDK)."
        )
    pdk = os.environ.get("PDK", "sky130A")
    root = Path(raw_root).expanduser().resolve() / pdk
    corner = root / "libs.tech" / "ngspice" / "sky130.lib.spice"
    cells = root / "libs.ref" / "sky130_fd_sc_hd" / "spice" / "sky130_fd_sc_hd.spice"
    missing = [str(path) for path in (corner, cells) if not path.is_file()]
    if missing:
        raise FileNotFoundError("required SKY130 SPICE file(s) missing: " + ", ".join(missing))
    return corner, cells


def spice_path(path):
    """Quote a host path for an ngspice include directive."""
    return '"' + str(path).replace("\\", "/").replace('"', '\\"') + '"'


def atomic_write_text(path, text):
    """Replace a generated text file only after its complete content exists."""
    target = Path(path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=target.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
