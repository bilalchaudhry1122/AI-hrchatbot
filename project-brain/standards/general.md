# General standards

- Python 3.12+, match existing `app/` style (factories, dict config, no extra frameworks).
- Do not add Node/JavaScript.
- Pinecone: query only. Do not create indexes or upsert.
- Keep embedding model `gemini-embedding-2` and index dim `3072` aligned with n8n.
- Do not log or send secrets, API keys, raw scores, or model names to Discord users.
- Ticket-only public UX unless the user asks to change it (`respondMode: slash`).
- No Guild Members intent unless explicitly requested.
- Do not refactor unrelated files. Stay inside the approved plan.
- Tests: prefer `pytest` helpers tests; diagnostic scripts remain query-only.
- Type hints on new public functions when practical.
