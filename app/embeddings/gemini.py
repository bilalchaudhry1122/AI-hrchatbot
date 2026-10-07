from google import genai
from google.genai import types

from app.errors import AppError, ErrorCodes
from app.generation.prompt import build_answer_prompt


class GeminiClient:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.ai = genai.Client(api_key=config["gemini"]["apiKey"])

    def embed_query(self, text, dimension):
        input_text = str(text or "").strip()
        if not input_text:
            raise AppError(ErrorCodes.EMBEDDING_FAILED, "Cannot embed an empty question.")
        try:
            embed_config = {"output_dimensionality": dimension} if dimension else {}
            task = self.config["gemini"].get("embeddingTaskType")
            if task:
                embed_config["task_type"] = task
            response = self.ai.models.embed_content(
                model=self.config["gemini"]["embeddingModel"],
                contents=input_text,
                config=types.EmbedContentConfig(**embed_config) if embed_config else None,
            )
            values = []
            embeddings = getattr(response, "embeddings", None) or []
            if embeddings:
                values = getattr(embeddings[0], "values", None) or []
            elif getattr(response, "embedding", None):
                values = getattr(response.embedding, "values", None) or []
            if not values:
                raise AppError(ErrorCodes.EMBEDDING_FAILED, "Embedding API returned no vector.")
            if dimension and len(values) != dimension:
                raise AppError(
                    ErrorCodes.EMBEDDING_FAILED,
                    f"Embedding dimension {len(values)} does not match Pinecone index dimension {dimension}.",
                )
            self.logger.debug("Created query embedding", {
                "model": self.config["gemini"]["embeddingModel"],
                "dimension": len(values),
            })
            return list(values)
        except AppError:
            raise
        except Exception as error:
            raise AppError(ErrorCodes.EMBEDDING_FAILED, "Failed to embed the question.", cause=error) from error

    def generate_answer(self, *, question, context_blocks, mode="knowledge", identity=None):
        prompt = build_answer_prompt(question, context_blocks, mode, identity or {})
        try:
            response = self.ai.models.generate_content(
                model=self.config["gemini"]["answerModel"],
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=800),
            )
            text = _extract_generated_text(response)
            if not text:
                raise AppError(ErrorCodes.GENERATION_FAILED, "The answer model returned an empty response.")
            return text
        except AppError:
            raise
        except Exception as error:
            raise AppError(ErrorCodes.GENERATION_FAILED, "Failed to generate an answer.", cause=error) from error


def create_gemini(config, logger):
    return GeminiClient(config, logger)


def _extract_generated_text(response):
    direct = str(getattr(response, "text", "") or "").strip()
    if direct:
        return direct
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return ""
    parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
    return "".join(str(getattr(part, "text", "") or "") for part in parts).strip()
