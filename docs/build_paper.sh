#!/bin/sh
# Build the paper DOCX and PDF from paper_draft.md.
# Needs pandoc and libreoffice on PATH.
set -e
cd "$(dirname "$0")"
pandoc paper_draft.md --reference-doc=paper/reference.docx -o paper/SILICON_paper.docx
soffice --headless --convert-to pdf --outdir paper paper/SILICON_paper.docx
