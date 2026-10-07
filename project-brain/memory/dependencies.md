# Dependencies

From `requirements.txt` / `pyproject.toml` (Python >=3.12):

| Package | Purpose |
|---|---|
| discord.py>=2.4 | Gateway bot |
| python-dotenv>=1.0 | `.env` |
| google-genai>=1.0 | Embeddings + Gemini answers |
| pinecone>=5.0 | Vector query |
| pyairtable>=3.0 | Airtable REST |
| pytest>=8 | Tests |

## Config sources

- `.env` / `.env.example` — tokens, models, thresholds, `ECHO_MODE`, `LOG_LEVEL`, SMTP send (`SMTP_HOST`, `SMTP_USERNAME`), leave To (`LEAVE_MAIL_HR`). HOD Cc comes from Employees Email in Airtable.
- `channels.json` — `respondMode`, tickets category/roles, channel ID → namespace
- Do not commit `.env`, `channels.json`, `tickets.json`, lockfile
