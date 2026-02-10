"""Text chunking with section awareness for SEC filings."""

import re
import hashlib

# SEC filing section headers
SEC_SECTION_RE = re.compile(
    r"^(?:ITEM|PART)\s+\d+[A-Z]?[\.\:\s\-]+",
    re.IGNORECASE | re.MULTILINE,
)

CHUNK_SIZE = 1000
OVERLAP = 200


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split text into (section_name, section_text) tuples."""
    matches = list(SEC_SECTION_RE.finditer(text))
    if not matches:
        return [("", text)]

    sections = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_name = m.group(0).strip().rstrip(".:- ")
        sections.append((section_name, text[start:end]))

    # Include any text before the first section
    if matches[0].start() > 0:
        sections.insert(0, ("", text[:matches[0].start()]))

    return sections


def _chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[str]:
    """Chunk text respecting paragraph and sentence boundaries."""
    if len(text) <= size:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        if end >= len(text):
            chunk = text[start:]
            if chunk.strip():
                chunks.append(chunk)
            break

        # Try to break at paragraph boundary
        para_break = text.rfind("\n\n", start, end)
        if para_break > start + size // 2:
            end = para_break + 2
        else:
            # Try sentence boundary
            sent_break = max(
                text.rfind(". ", start, end),
                text.rfind(".\n", start, end),
            )
            if sent_break > start + size // 2:
                end = sent_break + 1

        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)

        start = end - overlap if end - overlap > start else end

    return chunks


def chunk_document(text: str, metadata: dict) -> list[tuple[str, str, dict]]:
    """Chunk a document into (id, text, metadata) tuples.

    Returns list of (chunk_id, chunk_text, chunk_metadata).
    """
    sections = _split_sections(text)
    results = []
    chunk_index = 0

    for section_name, section_text in sections:
        chunks = _chunk_text(section_text)
        for chunk in chunks:
            chunk_meta = {**metadata, "chunk_index": chunk_index}
            if section_name:
                chunk_meta["section"] = section_name

            # Deterministic ID from source + index
            source = metadata.get("source_file", "unknown")
            chunk_id = hashlib.md5(f"{source}:{chunk_index}".encode()).hexdigest()

            results.append((chunk_id, chunk, chunk_meta))
            chunk_index += 1

    return results
