"""SQL safety validation — rejects anything that isn't a safe SELECT."""
import re
from typing import Optional


BLOCKED_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|REPLACE|EXEC|EXECUTE"
    r"|GRANT|REVOKE|COPY|VACUUM|ANALYZE|EXPLAIN\s+ANALYZE|pg_read_file"
    r"|pg_write_file|lo_export|lo_import)\b",
    re.IGNORECASE,
)

COMMENT_PATTERN = re.compile(r"(--|/\*|\*/)", re.IGNORECASE)


class GuardrailError(ValueError):
    """Raised when a query violates safety rules."""


def validate_query(sql: str, max_rows: int = 500) -> str:
    """
    Validate and sanitise a SQL query.

    Returns the cleaned query string with LIMIT injected, or raises
    GuardrailError if the query is not permitted.
    """
    stripped = sql.strip()

    if not stripped:
        raise GuardrailError("Empty query.")

    # Block SQL comments (common injection vector)
    if COMMENT_PATTERN.search(stripped):
        raise GuardrailError("SQL comments are not permitted.")

    # Must start with SELECT
    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        raise GuardrailError(
            "Only SELECT statements are permitted. "
            f"Received: {stripped[:60]}..."
        )

    # Block dangerous keywords anywhere in the query
    match = BLOCKED_KEYWORDS.search(stripped)
    if match:
        raise GuardrailError(
            f"Forbidden keyword '{match.group()}' found in query."
        )

    # Inject LIMIT if not already present
    if not re.search(r"\bLIMIT\s+\d+", stripped, re.IGNORECASE):
        stripped = stripped.rstrip(";") + f" LIMIT {max_rows}"

    return stripped
