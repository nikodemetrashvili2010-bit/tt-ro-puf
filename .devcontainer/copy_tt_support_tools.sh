#!/bin/sh
set -eu

if [ -L tt ]; then
    exit 0
fi

if [ -e tt ]; then
    echo "tt already exists and is not a symlink; preserving it unchanged" >&2
    exit 0
fi

# The image contains an exact detached revision. A symlink avoids a mutable,
# silently pulled workspace copy while retaining the conventional ./tt path.
ln -s /ttsetup/tt-support-tools tt
