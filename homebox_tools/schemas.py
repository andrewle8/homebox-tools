"""JSON output schemas for dry-run and error output."""

# Dry-run output schema:
# {
#   "name": str,
#   "description": str,
#   "manufacturer": str | None,
#   "model": str | None,
#   "price": float | None,
#   "purchase_date": str | None,  # ISO 8601
#   "image_path": str | None,     # local path to downloaded image
#   "manuals": [{"path": str, "name": str}],
#   "specs": [{"name": str, "value": str, "type": "text" | "number"}],
#   "suggested_tags": [str],
#   "asin": str | None,
#   "duplicate_warning": str | None
# }
#
# Error output schema:
# {
#   "error": str,  # machine-readable error code
#   "message": str  # human-readable message
# }
