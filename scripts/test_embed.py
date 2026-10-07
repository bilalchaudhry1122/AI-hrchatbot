import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.embeddings.gemini import create_gemini
from app.logger import create_logger
from app.pinecone.client import create_pinecone


def main():
    question = " ".join(sys.argv[1:]) or "How do I get started?"
    config = load_config()
    logger = create_logger("info")
    pinecone = create_pinecone(config, logger)
    description = pinecone["describe_index"]()
    dimension = int(getattr(description, "dimension", 3072))
    embeddings = create_gemini(config, logger)
    vector = embeddings.embed_query(question, dimension)
    print({"question": question, "dimension": len(vector), "model": config["gemini"]["embeddingModel"]})


if __name__ == "__main__":
    main()
