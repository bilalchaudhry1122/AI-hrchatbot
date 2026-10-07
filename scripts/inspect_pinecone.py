import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.logger import create_logger
from app.pinecone.client import create_pinecone


def main():
    config = load_config()
    logger = create_logger(config["logLevel"])
    pinecone = create_pinecone(config, logger)
    description = pinecone["describe_index"]()
    stats = pinecone["describe_stats"]()
    namespaces = getattr(stats, "namespaces", None) or (stats.get("namespaces") if isinstance(stats, dict) else {})
    print({
        "index": getattr(description, "name", None) or config["pinecone"]["indexName"],
        "dimension": getattr(description, "dimension", None),
        "metric": getattr(description, "metric", None),
        "namespaces": list(namespaces.keys()) if isinstance(namespaces, dict) else namespaces,
    })


if __name__ == "__main__":
    main()
