TEXT_FIELDS = ["text", "pageContent", "page_content", "content", "chunk", "chunk_text", "document", "body"]
SOURCE_FIELDS = ["file_name", "fileName", "document_name", "source", "title"]


def is_namespace_marker(match):
    metadata = (match or {}).get("metadata") or {}
    match_id = str((match or {}).get("id") or "")
    return match_id == "__namespace_marker__" or metadata.get("record_type") == "namespace_marker"


def extract_chunk_text(metadata=None):
    metadata = metadata or {}
    for field in TEXT_FIELDS:
        value = metadata.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_source_name(metadata=None):
    metadata = metadata or {}
    for field in SOURCE_FIELDS:
        value = metadata.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return metadata.get("drive_file_id") or "unknown source"


def detect_text_field(records=None):
    for record in records or []:
        metadata = (record or {}).get("metadata") or {}
        for field in TEXT_FIELDS:
            if isinstance(metadata.get(field), str) and str(metadata.get(field)).strip():
                return field
    return None


def summarize_metadata_keys(records=None):
    keys = set()
    for record in records or []:
        keys.update(((record or {}).get("metadata") or {}).keys())
    return sorted(keys)
