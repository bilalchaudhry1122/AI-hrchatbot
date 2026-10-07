from app.errors import AppError, ErrorCodes
from app.pinecone.metadata import (
    detect_text_field,
    extract_chunk_text,
    extract_source_name,
    is_namespace_marker,
    summarize_metadata_keys,
)


def higher_score_is_better(metric):
    return str(metric or "cosine").lower() != "euclidean"


def is_relevant(matches, threshold, metric="cosine"):
    if not matches:
        return False
    top = matches[0].get("score") if isinstance(matches[0], dict) else getattr(matches[0], "score", None)
    if not isinstance(top, (int, float)):
        return False
    return top >= threshold if higher_score_is_better(metric) else top <= threshold


def to_context_chunks(matches):
    chunks = []
    for match in matches:
        data = match if isinstance(match, dict) else {
            "id": getattr(match, "id", None),
            "score": getattr(match, "score", None),
            "metadata": getattr(match, "metadata", {}) or {},
        }
        metadata = data.get("metadata") or {}
        chunks.append({
            "id": data.get("id"),
            "score": data.get("score"),
            "text": extract_chunk_text(metadata),
            "source": extract_source_name(metadata),
            "namespace": metadata.get("namespace_name") or "",
            "metadata": metadata,
        })
    return chunks


def _as_match(match):
    if isinstance(match, dict):
        return match
    return {
        "id": getattr(match, "id", None),
        "score": getattr(match, "score", None),
        "metadata": getattr(match, "metadata", {}) or {},
    }


def retrieve_knowledge(*, pinecone, vector, namespace, top_k, metric, logger):
    result = pinecone["query_namespace"](
        namespace=namespace,
        vector=vector,
        top_k=top_k,
        include_metadata=True,
    )
    raw_matches = []
    if isinstance(result, dict):
        raw_matches = result.get("matches") or []
    else:
        raw_matches = getattr(result, "matches", None) or []

    usable = []
    missing_text = 0
    for match in raw_matches:
        item = _as_match(match)
        if is_namespace_marker(item):
            continue
        text = extract_chunk_text(item.get("metadata") or {})
        if not text:
            missing_text += 1
            continue
        usable.append(item)

    reverse = higher_score_is_better(metric)
    usable.sort(key=lambda item: item.get("score") or 0, reverse=reverse)

    if not usable and missing_text:
        raise AppError(
            ErrorCodes.MISSING_CHUNK_TEXT,
            "Pinecone records were returned without readable chunk text.",
        )

    logger.debug("Pinecone retrieval", {
        "namespace": namespace,
        "rawMatches": len(raw_matches),
        "usable": len(usable),
        "missingText": missing_text,
        "textField": detect_text_field(usable),
        "metadataKeys": summarize_metadata_keys(usable[:3]),
        "scores": [round(item.get("score") or 0, 4) for item in usable[:5]],
        "sources": [extract_source_name(item.get("metadata")) for item in usable[:5]],
    })
    return to_context_chunks(usable)
