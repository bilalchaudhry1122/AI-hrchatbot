# Discord RAG Chatbot

Python 3.12+ Discord support bot. Full product docs: **[PROJECT.md](./PROJECT.md)**

The bot answers ticket questions from the existing Pinecone index, kept up to date by the n8n + Google Drive pipeline. It never writes to Pinecone and never calls n8n.

| Setting | Value |
|---|---|
| Pinecone index | `document` |
| Dimension | `3072` |
| Embedding | Gemini `gemini-embedding-2` |
| Answers | OpenRouter `google/gemma-4-31b-it` |
| Example namespace | `web airy` |

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Use the existing `.env` and `channels.json`. Do not recreate the Pinecone index.

### Run the bot

```powershell
python -m app.main
```

Flow: `#open-ticket` → **Open ticket** → private ticket under **Tickets** → RAG answers. Admin can `/leave` so humans can talk. Close keeps the same channel.

Only one process may run. A second start is blocked by `.bot.instance.lock`.

### Tests

```powershell
pytest
```

### Diagnostic scripts (query-only)

```powershell
python scripts/inspect_pinecone.py
python scripts/test_embed.py "How do I get started?"
python scripts/test_retrieve.py "web airy" "a question from your docs"
python scripts/test_answer.py "web airy" "same question"
python scripts/test_suite.py
```

### Discord

Enable **Message Content Intent**. Bot needs View Channel, Send Messages, Read Message History, Manage Messages, Manage Channels.
