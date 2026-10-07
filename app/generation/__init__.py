import re
import time

from app.generation.openrouter import create_openrouter

DEFAULT_COOLDOWN_MS = 2 * 60 * 1000


def is_rate_limited(error):
    if not error:
        return False
    status = getattr(error, "status", None) or getattr(getattr(error, "cause", None), "status", None)
    if status == 429:
        return True
    text = str(getattr(error, "message", None) or error)
    return bool(re.search(r"429|rate limit|too many requests|resource exhausted", text, re.I))


class AnswerModel:
    """Tries each (name, client) provider in order until one answers.

    Any failure moves on to the next provider. A provider that returned 429
    is skipped for `cooldown_ms` so every request doesn't wait on it again.
    """

    def __init__(self, providers, logger, cooldown_ms):
        self.providers = list(providers)
        self.logger = logger
        self.cooldown_ms = cooldown_ms
        self.cooldown_until = {}

    def generate_answer(self, **args):
        now = time.time() * 1000
        ready = [p for p in self.providers if now >= self.cooldown_until.get(p[0], 0)]
        # Every provider cooling down: still try them rather than fail outright.
        candidates = ready or self.providers
        last_error = None
        for index, (name, client) in enumerate(candidates):
            try:
                return client.generate_answer(**args)
            except Exception as error:
                last_error = error
                rate_limited = is_rate_limited(error)
                if rate_limited:
                    self.cooldown_until[name] = time.time() * 1000 + self.cooldown_ms
                if index + 1 < len(candidates):
                    self.logger.warn("Answer provider failed, trying the next one", {
                        "provider": name,
                        "next": candidates[index + 1][0],
                        "rateLimited": rate_limited,
                        "message": str(error),
                    })
        raise last_error


def create_answer_model(config, logger):
    from app.embeddings.gemini import create_gemini

    if config["answer"]["provider"] != "openrouter":
        logger.info("Using Gemini for answers", {"model": config["gemini"]["answerModel"]})
        return create_gemini(config, logger)
    keys = [config["openrouter"]["apiKey"], *config["openrouter"].get("fallbackApiKeys", [])]
    providers = [
        (f"openrouter#{number}", create_openrouter(config, logger, api_key=key))
        for number, key in enumerate(dict.fromkeys(keys), start=1)
    ]
    providers.append(("gemini", create_gemini(config, logger)))
    cooldown_ms = config["answer"].get("rateLimitCooldownMs") or DEFAULT_COOLDOWN_MS
    logger.info("Using OpenRouter for answers", {
        "model": config["openrouter"]["answerModel"],
        "chain": [name for name, _ in providers],
        "fallback": config["gemini"]["answerModel"],
    })
    return AnswerModel(providers, logger, cooldown_ms)
