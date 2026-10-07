from app.config import FALLBACK_ANSWER
from app.errors import AppError, ErrorCodes
from app.rag.retrieve import is_relevant, retrieve_knowledge
from app.rag.query import POLICY_RETRIEVE_HINT, expand_retrieval_query, should_retry_policy_retrieve
from app.agent.verification import is_broad_policy_catalog_question
from app.generation.quality import is_degenerate_answer
from app.routing.intent import (
    classify_social,
    is_about_bot,
    social_fallback_reply,
    situational_fallback_reply,
)
from app.routing.scope import no_answer_reply, off_topic_kind, policy_catalog_reply, redirect_reply


class RagPipeline:
    def __init__(self, *, config, logger, pinecone, embeddings, llm, index_info):
        self.config = config
        self.logger = logger
        self.pinecone = pinecone
        self.embeddings = embeddings
        self.llm = llm
        self.metric = index_info.get("metric") or "cosine"
        self.dimension = index_info.get("dimension")

    def answer_question(self, *, question, namespace, channel_id, identity=None, conversation_history=None):
        prompt_identity = dict(identity or {})
        prompt_identity["conversationHistory"] = conversation_history or []
        self.logger.info("RAG start", {
            "channel": channel_id,
            "namespace": namespace,
            "question": str(question)[:300],
        })

        social_kind = classify_social(question)
        if social_kind and not should_retry_policy_retrieve(
            question,
            prompt_identity.get("conversationHistory"),
            last_topic=prompt_identity.get("sessionTopic") or "",
        ):
            try:
                answer = self.llm.generate_answer(
                    question=question,
                    context_blocks=[],
                    mode="social",
                    identity={**prompt_identity, "socialKind": social_kind},
                )
            except Exception:
                answer = social_fallback_reply(social_kind, question)
            self.logger.info("Answered a social message", {
                "channel": channel_id,
                "namespace": namespace,
                "socialKind": social_kind,
            })
            return {"answer": answer, "fallback": True, "chunks": []}

        if is_about_bot(question) and not should_retry_policy_retrieve(
            question,
            prompt_identity.get("conversationHistory"),
            last_topic=prompt_identity.get("sessionTopic") or "",
        ):
            try:
                answer = self.llm.generate_answer(
                    question=question,
                    context_blocks=[],
                    mode="self",
                    identity=prompt_identity,
                )
            except Exception:
                answer = situational_fallback_reply(question, prompt_identity)
            self.logger.info("Answered a question about the bot", {
                "channel": channel_id,
                "namespace": namespace,
            })
            return {"answer": answer, "fallback": True, "chunks": []}

        retrieve_question = expand_retrieval_query(
            question,
            prompt_identity.get("conversationHistory"),
            last_topic=prompt_identity.get("sessionTopic") or "",
        )
        vector = self.embeddings.embed_query(retrieve_question, self.dimension)
        try:
            chunks = retrieve_knowledge(
                pinecone=self.pinecone,
                vector=vector,
                namespace=namespace,
                top_k=self.config["pinecone"]["topK"],
                metric=self.metric,
                logger=self.logger,
            )
        except AppError as error:
            if error.code in {ErrorCodes.MISSING_CHUNK_TEXT, ErrorCodes.EMPTY_RESULTS}:
                self.logger.error("Retrieval produced unusable records", {
                    "code": error.code,
                    "namespace": namespace,
                })
                return {
                    "answer": self._fallback_answer(question, prompt_identity),
                    "fallback": True,
                    "chunks": [],
                }
            raise

        relevant = is_relevant(chunks, self.config["rag"]["relevanceThreshold"], self.metric)
        if (not chunks or not relevant) and should_retry_policy_retrieve(
            question,
            prompt_identity.get("conversationHistory"),
            last_topic=prompt_identity.get("sessionTopic") or "",
        ):
            retry_vector = self.embeddings.embed_query(POLICY_RETRIEVE_HINT, self.dimension)
            try:
                retry_chunks = retrieve_knowledge(
                    pinecone=self.pinecone,
                    vector=retry_vector,
                    namespace=namespace,
                    top_k=self.config["pinecone"]["topK"],
                    metric=self.metric,
                    logger=self.logger,
                )
            except AppError:
                retry_chunks = []
            if is_relevant(retry_chunks, self.config["rag"]["relevanceThreshold"], self.metric):
                chunks = retry_chunks
                relevant = True
        if not chunks or not relevant:
            self.logger.info("Out of scope; handbook had no match", {
                "namespace": namespace,
                "matchCount": len(chunks),
                "topScore": chunks[0]["score"] if chunks else None,
                "threshold": self.config["rag"]["relevanceThreshold"],
            })
            return {
                "answer": self._fallback_answer(question, prompt_identity),
                "fallback": True,
                "chunks": chunks,
            }

        locale = prompt_identity.get("replyLanguage")
        if is_broad_policy_catalog_question(question):
            self.logger.info("Listed policy topics instead of dumping the handbook", {
                "namespace": namespace,
                "matchCount": len(chunks),
            })
            return {
                "answer": policy_catalog_reply(chunks, locale),
                "fallback": False,
                "chunks": chunks,
            }

        answer = self.llm.generate_answer(
            question=question,
            context_blocks=chunks,
            mode="knowledge",
            identity=prompt_identity,
        )
        if is_degenerate_answer(answer):
            self.logger.warn("Rejected a looped model answer", {
                "namespace": namespace,
                "length": len(str(answer or "")),
            })
            return {
                "answer": policy_catalog_reply(chunks, locale),
                "fallback": True,
                "chunks": chunks,
            }
        self.logger.info("RAG complete", {
            "namespace": namespace,
            "matchCount": len(chunks),
            "topScore": chunks[0]["score"] if chunks else None,
            "sources": [chunk.get("source") for chunk in chunks],
            "fallback": False,
        })
        return {"answer": answer, "fallback": False, "chunks": chunks}

    def _fallback_answer(self, question, identity):
        """No usable handbook match.

        Two different situations, and they must not share a message. Something
        off-topic gets the scope redirect; a fair HR question the handbook does
        not cover gets an honest "I could not find that", because telling an
        employee who asked about their contract that we only discuss workplace
        topics is both wrong and confusing.
        """
        locale = (identity or {}).get("replyLanguage")
        kind = off_topic_kind(question)
        if kind:
            return redirect_reply(question, kind, locale)
        return no_answer_reply(question, locale) or FALLBACK_ANSWER


def create_rag_pipeline(**kwargs):
    return RagPipeline(**kwargs)
