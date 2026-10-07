import httpx

from app.errors import AppError, ErrorCodes
from app.generation.prompt import answer_system_message, build_answer_prompt

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterClient:
    def __init__(self, config, logger, api_key=None):
        self.config = config
        self.logger = logger
        self.api_key = api_key or config["openrouter"]["apiKey"]

    def generate_answer(self, *, question, context_blocks, mode="knowledge", identity=None):
        prompt = build_answer_prompt(question, context_blocks, mode, identity or {})
        try:
            response = httpx.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://localhost",
                    "X-Title": "Discord RAG Chatbot",
                },
                json={
                    "model": self.config["openrouter"]["answerModel"],
                    "temperature": 0.2,
                    "max_tokens": 1200,
                    "reasoning": {"enabled": False},
                    "messages": [
                        {"role": "system", "content": answer_system_message(mode)},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=60.0,
            )
            payload = {}
            try:
                payload = response.json()
            except Exception:
                payload = {}
            if response.status_code >= 400:
                detail = ((payload.get("error") or {}).get("message")) or f"OpenRouter HTTP {response.status_code}"
                raise AppError(ErrorCodes.GENERATION_FAILED, detail, status=response.status_code)
            text = extract_openrouter_text(payload)
            if not text:
                raise AppError(ErrorCodes.GENERATION_FAILED, "The answer model returned an empty response.")
            self.logger.debug("Generated OpenRouter answer", {
                "model": self.config["openrouter"]["answerModel"],
            })
            return text
        except AppError:
            raise
        except Exception as error:
            raise AppError(ErrorCodes.GENERATION_FAILED, "Failed to generate an answer.", cause=error) from error


def create_openrouter(config, logger, api_key=None):
    return OpenRouterClient(config, logger, api_key=api_key)


def extract_openrouter_text(payload):
    message = ((payload or {}).get("choices") or [{}])[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        return "".join(part.get("text", "") if isinstance(part, dict) else "" for part in content).strip()
    return ""
