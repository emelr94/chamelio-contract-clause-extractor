from enum import StrEnum


class ClauseType(StrEnum):
    DEFINITIONS = "definitions"
    CONFIDENTIALITY = "confidentiality"
    TERM_TERMINATION = "term_termination"
    PAYMENT = "payment"
    WARRANTIES = "warranties"
    LIABILITY_LIMITATION = "liability_limitation"
    INDEMNIFICATION = "indemnification"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    DATA_PROTECTION = "data_protection"
    COMPLIANCE = "compliance"
    GOVERNING_LAW = "governing_law"
    DISPUTE_RESOLUTION = "dispute_resolution"
    ASSIGNMENT = "assignment"
    NOTICES = "notices"
    FORCE_MAJEURE = "force_majeure"
    NON_SOLICITATION = "non_solicitation"
    INSURANCE = "insurance"
    GENERAL_PROVISIONS = "general_provisions"
    PREAMBLE = "preamble"
    SIGNATURE_BLOCK = "signature_block"
    EXHIBIT = "exhibit"
    OTHER = "other"


class DocumentStatus(StrEnum):
    COMPLETED = "completed"  # all chunks succeeded (warnings may still exist)
    PARTIAL = "partial"  # at least one chunk failed, at least one succeeded
    FAILED = "failed"  # every chunk failed


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FileType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"


class ClauseIssue(StrEnum):
    ANCHOR_NOT_FOUND = "ANCHOR_NOT_FOUND"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MAY_CONTAIN_MISSING_CLAUSE = "MAY_CONTAIN_MISSING_CLAUSE"


class WarningCode(StrEnum):
    NUMBERING_GAP = "NUMBERING_GAP"
    UNCOVERED_TEXT = "UNCOVERED_TEXT"
    CHUNK_FAILED = "CHUNK_FAILED"
    ANCHOR_NOT_FOUND = "ANCHOR_NOT_FOUND"


class ErrorCode(StrEnum):
    MISSING_FILE = "MISSING_FILE"
    EMPTY_FILE = "EMPTY_FILE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    UNREADABLE_DOCUMENT = "UNREADABLE_DOCUMENT"
    SCANNED_PDF_UNSUPPORTED = "SCANNED_PDF_UNSUPPORTED"
    DOCUMENT_TOO_LARGE = "DOCUMENT_TOO_LARGE"
    EXTRACTION_NOT_FOUND = "EXTRACTION_NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    LLM_ERROR = "LLM_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    HTTP_ERROR = "HTTP_ERROR"  # framework-level errors, e.g. unknown route
