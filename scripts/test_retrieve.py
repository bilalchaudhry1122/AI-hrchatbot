import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.embeddings.gemini import create_gemini
from app.logger import create_logger
from app.pinecone.client import create_pinecone
from app.rag.retrieve import retrieve_knowledge


def main():
    args = sys.argv[1:]
    namespace = args[0] if args else "web airy"
    question = " ".join(args[1:]) or "What are the rules?"
    config = load_config()
    logger = create_logger("debug")
    pinecone = create_pinecone(config, logger)
    description = pinecone["describe_index"]()
    dimension = int(getattr(description, "dimension", 3072))
    metric = getattr(description, "metric", None) or "cosine"
    embeddings = create_gemini(config, logger)
    vector = embeddings.embed_query(question, dimension)
    chunks = retrieve_knowledge(
        pinecone=pinecone,
        vector=vector,
        namespace=namespace,
        top_k=config["pinecone"]["topK"],
        metric=metric,
        logger=logger,
    )
    print({
        "namespace": namespace,
        "question": question,
        "count": len(chunks),
        "topScore": chunks[0]["score"] if chunks else None,
        "sources": [chunk["source"] for chunk in chunks[:5]],
    })


if __name__ == "__main__":
    main()
