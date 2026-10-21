#!/bin/sh
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
# run every deck in the given folders, one at a time, skipping finished ones
for d in "$@"; do
  for f in $d/*.spice; do
    log=${f%.spice}.log
    if [ -f $log ] && grep -q "^f = " $log; then continue; fi
    (cd $d && ngspice -b $(basename $f) > $(basename $log) 2>&1)
  done
done
echo decks done
