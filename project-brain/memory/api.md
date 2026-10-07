# External APIs (query/consume only)

No HTTP API served by this app.

## Discord Gateway

discord.py client. Intents: message content on; members off. Needs Manage Channels, Manage Messages, View, Send, History.

## Pinecone

`app/pinecone/client.py` — describe index/stats, **query only**. Index `document`, dim 3072, cosine. Namespace from channel map. Ignore `record_type=namespace_marker`. Chunk text in metadata `text`. `app/pinecone/metadata.py` extracts text.

## Gemini embeddings

`app/embeddings/gemini.py` — `gemini-embedding-2`, task type from env (`RETRIEVAL_QUERY` recommended).

## OpenRouter

`app/generation/openrouter.py` — `google/gemma-4-31b-it`.

## Airtable (live HR)

`app/airtable/` query Employees, Leave Types, Leave Balances, Attendance; create/update Leave Requests. Token never sent to Discord or LLM prompts.

