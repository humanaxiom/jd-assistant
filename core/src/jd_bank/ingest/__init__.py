"""JD Bank ingestion — archive walk, hashing, format detection, text
extraction, and incumbent-name normalization, persisting ``source_documents``.

Public surface:

- :func:`~src.jd_bank.ingest.ingest.detect_format`,
  :func:`~src.jd_bank.ingest.ingest.compute_sha256`,
  :func:`~src.jd_bank.ingest.ingest.walk_archive`,
  :func:`~src.jd_bank.ingest.ingest.ingest_document`
- :func:`~src.jd_bank.ingest.extract.extract_text` (+ ``extract_text_from_path``)
- :func:`~src.jd_bank.ingest.scrub.normalize_incumbent_names` /
  :class:`~src.jd_bank.ingest.scrub.ScrubReport`
"""

from src.jd_bank.ingest.extract import (
    DocumentTooLargeError,
    ExtractionError,
    UnsupportedFormatError,
    extract_text,
    extract_text_from_path,
    read_document_bytes,
    stream_sha256,
)
from src.jd_bank.ingest.ingest import (
    IngestOutcome,
    compute_sha256,
    detect_format,
    ingest_document,
    ingest_unreadable_document,
    walk_archive,
)
from src.jd_bank.ingest.scrub import ScrubReport, normalize_incumbent_names

__all__ = [
    "DocumentTooLargeError",
    "ExtractionError",
    "UnsupportedFormatError",
    "extract_text",
    "extract_text_from_path",
    "read_document_bytes",
    "stream_sha256",
    "compute_sha256",
    "detect_format",
    "IngestOutcome",
    "ingest_document",
    "ingest_unreadable_document",
    "walk_archive",
    "ScrubReport",
    "normalize_incumbent_names",
]
