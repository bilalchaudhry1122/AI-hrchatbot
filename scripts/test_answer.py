import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.embeddings.gemini import create_gemini
from app.generation import create_answer_model
from app.logger import create_logger
from app.pinecone.client import create_pinecone
from app.rag.pipeline import create_rag_pipeline


def main():
    args = sys.argv[1:]
    namespace = args[0] if args else "web airy"
    question = " ".join(args[1:]) or "What are the rules?"
    config = load_config()
    logger = create_logger("info")
    pinecone = create_pinecone(config, logger)
    description = pinecone["describe_index"]()
    stats = pinecone["describe_stats"]()
    namespaces = getattr(stats, "namespaces", None) or {}
    rag = create_rag_pipeline(
        config=config,
        logger=logger,
        pinecone=pinecone,
        embeddings=create_gemini(config, logger),
        llm=create_answer_model(config, logger),
        index_info={
            "dimension": int(getattr(description, "dimension", 3072)),
            "metric": getattr(description, "metric", None) or "cosine",
            "namespaces": list(namespaces.keys()) if isinstance(namespaces, dict) else [],
        },
    )
    result = rag.answer_question(question=question, namespace=namespace, channel_id="cli")
    print(result["answer"])
    print({"fallback": result["fallback"], "chunks": len(result["chunks"])})


if __name__ == "__main__":
    main()
