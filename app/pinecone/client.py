from app.errors import AppError, ErrorCodes
from app.pinecone.metadata import (
    detect_text_field,
    extract_chunk_text,
    extract_source_name,
    is_namespace_marker,
    summarize_metadata_keys,
)


def create_pinecone(config, logger):
    from pinecone import Pinecone

    client = Pinecone(api_key=config["pinecone"]["apiKey"])
    index = client.Index(config["pinecone"]["indexName"])

    def describe_index():
        try:
            return client.describe_index(config["pinecone"]["indexName"])
        except Exception as error:
            raise wrap_pinecone_error(error) from error

    def describe_stats():
        try:
            return index.describe_index_stats()
        except Exception as error:
            raise wrap_pinecone_error(error) from error

    def query_namespace(*, namespace, vector, top_k, include_metadata=True):
        if not namespace:
            raise AppError(
                ErrorCodes.NAMESPACE_NOT_CONFIGURED,
                "No Pinecone namespace is configured for this channel.",
            )
        try:
            return index.query(
                vector=vector,
                top_k=top_k,
                namespace=namespace,
                include_metadata=include_metadata,
                include_values=False,
            )
        except Exception as error:
            raise wrap_pinecone_error(error, namespace) from error

    return {
        "client": client,
        "index": index,
        "describe_index": describe_index,
        "describe_stats": describe_stats,
        "query_namespace": query_namespace,
        "logger": logger,
    }


def wrap_pinecone_error(error, namespace=None):
    status = getattr(error, "status", None) or getattr(error, "status_code", None)
    message = str(getattr(error, "message", None) or error or "Pinecone request failed")
    if status in {401, 403} or re_auth(message):
        return AppError(ErrorCodes.PINECONE_AUTH, "Pinecone rejected the API credentials.", cause=error)
    if "dimension" in message.lower():
        extra = f" for namespace {namespace}" if namespace else ""
        return AppError(
            ErrorCodes.PINECONE_UNAVAILABLE,
            f"Pinecone rejected the query vector{extra}: {message}",
            cause=error,
        )
    return AppError(
        ErrorCodes.PINECONE_UNAVAILABLE,
        "The knowledge database is temporarily unavailable.",
        cause=error,
    )


def re_auth(message):
    lowered = message.lower()
    return "unauthorized" in lowered or "forbidden" in lowered or "api key" in lowered
