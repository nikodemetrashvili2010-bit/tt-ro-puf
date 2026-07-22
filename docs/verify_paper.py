#!/usr/bin/env python3
"""Check that shipped paper artifacts match the Markdown and figure inputs."""

import argparse
import hashlib
import html
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

from pypdf import PdfReader

import build_paper


STALE_PHRASES = (
    "Automated Layout Manufactures Fake Entropy",
    "Every chip gets the same one",
    "zero by construction",
    "silicon-accurate",
    "matched macro removes",
)

WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD = "{" + WORD_NAMESPACE + "}"


def docx_text_and_core(path: Path):
    with zipfile.ZipFile(path) as archive:
        document = archive.read("word/document.xml").decode("utf-8")
        styles = archive.read("word/styles.xml").decode("utf-8")
        numbering = archive.read("word/numbering.xml").decode("utf-8")
        core = archive.read("docProps/core.xml").decode("utf-8")
        media = {
            name: archive.read(name)
            for name in archive.namelist()
            if name.startswith("word/media/")
        }
        xml_text = "\n".join(
            archive.read(name).decode("utf-8", "ignore")
            for name in archive.namelist()
            if name.endswith(".xml")
        )
        zip_dates = {item.date_time for item in archive.infolist()}
        names = archive.namelist()
    root = ElementTree.fromstring(document)
    paragraphs = []
    for paragraph in root.iter(WORD + "p"):
        text = "".join(node.text or "" for node in paragraph.iter(WORD + "t"))
        if text:
            paragraphs.append(text)
    return (
        "\n".join(paragraphs),
        core,
        media,
        xml_text,
        zip_dates,
        names,
        document,
        styles,
        numbering,
    )


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _word_value(element, name: str = "val"):
    return None if element is None else element.get(WORD + name)


def _numbering_properties(paragraph_properties):
    if paragraph_properties is None:
        return None
    properties = paragraph_properties.find(WORD + "numPr")
    if properties is None:
        return None
    number_id = _word_value(properties.find(WORD + "numId"))
    if number_id is None or number_id == "0":
        return None
    level = _word_value(properties.find(WORD + "ilvl"))
    return int(number_id), int(level or 0)


def docx_ordered_list_errors(document_xml: str, styles_xml: str, numbering_xml: str, blocks):
    expected = [
        (normalize(build_paper.plain_markdown(block.text)), block.level)
        for block in blocks
        if block.kind == "number"
    ]
    if not expected:
        return []

    styles_root = ElementTree.fromstring(styles_xml)
    styles = {}
    for style in styles_root.findall(WORD + "style"):
        style_id = _word_value(style, "styleId")
        if not style_id:
            continue
        based_on = _word_value(style.find(WORD + "basedOn"))
        styles[style_id] = (based_on, _numbering_properties(style.find(WORD + "pPr")))

    def paragraph_numbering(paragraph):
        paragraph_properties = paragraph.find(WORD + "pPr")
        direct = _numbering_properties(paragraph_properties)
        if direct is not None:
            return direct
        style_node = (
            paragraph_properties.find(WORD + "pStyle")
            if paragraph_properties is not None
            else None
        )
        style_id = _word_value(style_node)
        visited = set()
        while style_id and style_id not in visited:
            visited.add(style_id)
            based_on, inherited = styles.get(style_id, (None, None))
            if inherited is not None:
                return inherited
            style_id = based_on
        return None

    numbering_root = ElementTree.fromstring(numbering_xml)
    abstract_levels = {}
    for abstract in numbering_root.findall(WORD + "abstractNum"):
        abstract_id = int(_word_value(abstract, "abstractNumId"))
        for level in abstract.findall(WORD + "lvl"):
            level_id = int(_word_value(level, "ilvl") or 0)
            start = int(_word_value(level.find(WORD + "start")) or 1)
            number_format = _word_value(level.find(WORD + "numFmt")) or "decimal"
            level_text = _word_value(level.find(WORD + "lvlText")) or f"%{level_id + 1}."
            abstract_levels[(abstract_id, level_id)] = (start, number_format, level_text)

    number_definitions = {}
    for number in numbering_root.findall(WORD + "num"):
        number_id = int(_word_value(number, "numId"))
        abstract_id = int(_word_value(number.find(WORD + "abstractNumId")))
        overrides = {}
        for override in number.findall(WORD + "lvlOverride"):
            level_id = int(_word_value(override, "ilvl") or 0)
            start_override = _word_value(override.find(WORD + "startOverride"))
            if start_override is not None:
                overrides[level_id] = int(start_override)
        number_definitions[number_id] = (abstract_id, overrides)

    document_root = ElementTree.fromstring(document_xml)
    paragraphs = []
    counters = {}
    resolved_markers = {}
    for index, paragraph in enumerate(document_root.iter(WORD + "p")):
        text = normalize(
            "".join(node.text or "" for node in paragraph.iter(WORD + "t"))
        )
        paragraphs.append(text)
        numbering_properties = paragraph_numbering(paragraph)
        if numbering_properties is None:
            continue
        number_id, level_id = numbering_properties
        definition = number_definitions.get(number_id)
        if definition is None:
            continue
        abstract_id, overrides = definition
        level_definition = abstract_levels.get((abstract_id, level_id))
        if level_definition is None:
            continue
        start, number_format, level_text = level_definition
        start = overrides.get(level_id, start)
        key = (number_id, level_id)
        value = counters.get(key, start - 1) + 1
        counters[key] = value
        marker = level_text.replace(f"%{level_id + 1}", str(value))
        resolved_markers[index] = (number_format, marker)

    errors = []
    cursor = 0
    for text, expected_number in expected:
        try:
            index = paragraphs.index(text, cursor)
        except ValueError:
            errors.append(f"ordered-list item is missing from the DOCX: {text[:80]}")
            continue
        cursor = index + 1
        resolved = resolved_markers.get(index)
        expected_marker = f"{expected_number}."
        if resolved is None:
            errors.append(f"DOCX ordered-list item lacks numbering: {text[:80]}")
            continue
        number_format, marker = resolved
        if number_format != "decimal" or marker != expected_marker:
            errors.append(
                f"DOCX ordered-list marker is {marker!r} ({number_format}), "
                f"expected {expected_marker!r}"
            )
    return errors


def pdf_plain_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"\1", text)
    text = re.sub(r"`([^`]+?)`", r"\1", text)
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)


def blocks_in_order(artifact_text: str, blocks, transform) -> list[str]:
    artifact = normalize(artifact_text)
    cursor = 0
    missing = []
    for index, block in enumerate(blocks, start=1):
        if block.kind == "rule" or not block.text:
            continue
        expected = normalize(transform(block.text))
        position = artifact.find(expected, cursor)
        if position < 0:
            missing.append(f"block {index}: {expected[:90]}")
        else:
            cursor = position + len(expected)
    return missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, default=build_paper.OUTPUT_DIR)
    args = parser.parse_args()

    blocks = build_paper.parse_markdown(build_paper.SOURCE)
    build_id = build_paper.paper_build_id(blocks)
    title = build_paper.plain_markdown(blocks[0].text)
    docx_path = args.artifact_dir / "SILICON_paper.docx"
    pdf_path = args.artifact_dir / "SILICON_paper.pdf"

    (
        docx_text,
        core,
        media,
        docx_xml,
        zip_dates,
        docx_names,
        document_xml,
        styles_xml,
        numbering_xml,
    ) = docx_text_and_core(docx_path)
    pdf = PdfReader(str(pdf_path))
    pdf_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    pdf_keywords = str((pdf.metadata or {}).get("/Keywords", ""))
    combined = "\n".join((docx_text, core, pdf_text, pdf_keywords))

    errors = []
    if f"build-sha256={build_id}" not in core:
        errors.append("DOCX build fingerprint is missing or stale")
    if f"build-sha256={build_id}" not in pdf_keywords:
        errors.append("PDF build fingerprint is missing or stale")
    normalized_title = normalize(title)
    normalized_docx = normalize(docx_text)
    normalized_pdf = normalize(pdf_text)
    if normalized_title not in normalized_docx or normalized_title not in normalized_pdf:
        errors.append("current paper title is missing")
    if len(media) < 4:
        errors.append(f"DOCX embeds {len(media)} figures, expected at least 4")
    if len(pdf.pages) < 5:
        errors.append(f"PDF has only {len(pdf.pages)} pages")
    missing_docx = blocks_in_order(docx_text, blocks, build_paper.plain_markdown)
    missing_pdf = blocks_in_order(pdf_text, blocks, pdf_plain_markdown)
    if missing_docx:
        errors.append("DOCX is missing or reorders source text: " + "; ".join(missing_docx[:3]))
    if missing_pdf:
        errors.append("PDF is missing or reorders source text: " + "; ".join(missing_pdf[:3]))
    errors.extend(
        docx_ordered_list_errors(document_xml, styles_xml, numbering_xml, blocks)
    )

    source_figures = [
        build_paper.resolve_asset(block.path).read_bytes()
        for block in blocks
        if block.kind == "image"
    ]
    source_hashes = Counter(hashlib.sha256(data).hexdigest() for data in source_figures)
    embedded_hashes = Counter(hashlib.sha256(data).hexdigest() for data in media.values())
    if source_hashes != embedded_hashes:
        errors.append("DOCX embedded figures do not exactly match the source PNG files")

    if re.search(r"\brsid\w*\b|<w14:docId\b", docx_xml, flags=re.IGNORECASE):
        errors.append("DOCX still contains editing-session identifiers")
    if any(name.startswith("customXml/") for name in docx_names):
        errors.append("DOCX still contains unused custom XML")
    if "2026-07-22T00:00:00Z" not in core:
        errors.append("DOCX build date is missing or stale")
    if zip_dates != {build_paper.ZIP_DATE}:
        errors.append("DOCX package timestamps are not normalized")
    for phrase in STALE_PHRASES:
        if phrase.casefold() in combined.casefold():
            errors.append(f"stale phrase remains: {phrase}")
    if errors:
        raise SystemExit("FAIL:\n- " + "\n- ".join(errors))
    print(f"PASS: DOCX/PDF match source fingerprint {build_id}")
    print(f"PASS: {len(media)} DOCX figures; {len(pdf.pages)} PDF pages")
    print(f"PASS: {len(blocks)} source blocks are present in order in both artifacts")
    print("PASS: DOCX figures and ordered-list numbering match the source")
    print("PASS: DOCX editing metadata is scrubbed")
    print("PASS: no stale claims found")


if __name__ == "__main__":
    main()
