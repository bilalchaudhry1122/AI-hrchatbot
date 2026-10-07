# Architecture

Layered Python package under `app/`.

```
Discord events (bot.py)
  → tickets (create/reopen/close) + messages
  → routing (channel→namespace, intent)
  → rag pipeline (social/self skip retrieve; else embed→query→generate)
  → Pinecone query-only + Gemini embed + OpenRouter/Gemini LLM
```

## Layers

- **Entry:** `app/main.py` — config, instance lock, Pinecone describe, wire RAG, start discord.py
- **Config:** `.env` + `channels.json` via `app/config.py`
- **Discord:** `app/discord/` — gateway, buttons (`ticket:open` / `ticket:close`), `/leave`
- **Tickets state:** `app/tickets/store.py` → `tickets.json`
- **RAG:** `app/rag/` — intent, retrieve, generate
- **External:** `app/pinecone/`, `app/embeddings/gemini.py`, `app/generation/`

## Patterns

- Factory functions (`create_*`) returning dicts or classes
- Query-only vector store
- Single-instance lock `.bot.instance.lock`
- Live HR data uses Airtable (`app/airtable/`, `app/hr/`). Policy still uses Pinecone. Ticket messages go through `app/agent/router.py`.
