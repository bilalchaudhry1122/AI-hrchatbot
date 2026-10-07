# Overview

Python Discord RAG support bot. Ticket-only UX: members open a private ticket from `#open-ticket`; the bot answers from an existing Pinecone index filled by n8n (Google Drive). This app never writes to Pinecone and never calls n8n during chat.

## Goals

- Grounded answers from namespace mapped to the entry channel (example: `web airy`)
- One reusable ticket channel per member; close locks send; reopen same channel
- Admin/Staff can join; `/leave` silences the bot until close+reopen

## Tech stack

Python 3.12+, discord.py 2.x, google-genai, pinecone, httpx, pytest. Run: `python -m app.main`.

## Constraints (do not change unless asked)

- Index `document`, dim `3072`, cosine
- Embeddings: Gemini `gemini-embedding-2`
- Answers: OpenRouter `google/gemma-4-31b-it`; Gemini `gemini-3.5-flash` fallback
- Message Content Intent on; Guild Members intent off
