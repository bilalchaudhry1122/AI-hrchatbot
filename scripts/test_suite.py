import json
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
    root = Path(__file__).resolve().parents[1]
    questions_path = root / "tests" / "web-airy-questions.json"
    if not questions_path.exists():
        questions_path = root / "tests" / "questions.template.json"
    payload = json.loads(questions_path.read_text(encoding="utf-8"))
    namespace = payload.get("namespace") or "web airy"
    questions = payload.get("questions") or []
    config = load_config()
    logger = create_logger("warn")
    pinecone = create_pinecone(config, logger)
    description = pinecone["describe_index"]()
    rag = create_rag_pipeline(
        config=config,
        logger=logger,
        pinecone=pinecone,
        embeddings=create_gemini(config, logger),
        llm=create_answer_model(config, logger),
        index_info={
            "dimension": int(getattr(description, "dimension", 3072)),
            "metric": getattr(description, "metric", None) or "cosine",
            "namespaces": [],
        },
    )
    for item in questions:
        question = item if isinstance(item, str) else item.get("question")
        result = rag.answer_question(question=question, namespace=namespace, channel_id="suite")
        print(f"Q: {question}\nA: {result['answer'][:400]}\nfallback={result['fallback']}\n")


if __name__ == "__main__":
    main()
