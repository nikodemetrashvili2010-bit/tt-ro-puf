#!/bin/sh
# SPDX-FileCopyrightText: 2026 Nikoloz Demetrashvili
# SPDX-License-Identifier: Apache-2.0
# second runner: one folder, decks in reverse order, skipping any deck
# that already has a log (finished or being run by the first runner)
d=$1
for f in $(ls $d/*.spice | sort -r); do
  log=${f%.spice}.log
  [ -e $log ] && continue
  (cd $d && ngspice -b $(basename $f) > $(basename $log) 2>&1)
done
echo reverse done
