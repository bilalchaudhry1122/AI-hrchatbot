import asyncio
import sys

from app.config import load_config
from app.db.client import create_mysql_client
from app.discord.bot import create_discord_bot
from app.embeddings.gemini import create_gemini
from app.errors import AppError, ErrorCodes
from app.generation import create_answer_model
from app.hr import create_hr_services
from app.logger import create_logger
from app.pinecone.client import create_pinecone
from app.process_lock import acquire_instance_lock, release_instance_lock
from app.rag.pipeline import create_rag_pipeline


def load_index_info(pinecone, config, logger):
    try:
        description = pinecone["describe_index"]()
    except Exception as error:
        logger.error("Failed to read Pinecone index", {"message": str(error)})
        raise

    spec = getattr(description, "spec", None) or {}
    try:
        stats = pinecone["describe_stats"]()
    except Exception as error:
        logger.warn("Could not read Pinecone namespace stats", {"message": str(error)})
        stats = {"namespaces": {}}

    dimension = int(getattr(description, "dimension", None) or getattr(stats, "dimension", 0) or 0)
    metric = getattr(description, "metric", None) or getattr(spec, "metric", None) or "cosine"
    if not dimension:
        raise AppError(
            ErrorCodes.PINECONE_UNAVAILABLE,
            f'Pinecone index "{config["pinecone"]["indexName"]}" did not report a vector dimension.',
        )

    if isinstance(stats, dict):
        namespaces = stats.get("namespaces") or {}
    else:
        namespaces = getattr(stats, "namespaces", None) or {}

    names = list(namespaces.keys()) if isinstance(namespaces, dict) else []
    logger.info("Connected to Pinecone", {
        "index": getattr(description, "name", None) or config["pinecone"]["indexName"],
        "dimension": dimension,
        "metric": metric,
        "namespaces": names,
    })
    mapped = set(config["discord"]["channels"].values())
    for namespace in mapped:
        if names and namespace not in names:
            logger.warn("Mapped namespace was not found in the current index stats", {"namespace": namespace})
    return {"dimension": dimension, "metric": metric, "namespaces": names}


async def amain():
    try:
        config = load_config()
    except Exception as error:
        print(f"[config] {error}")
        sys.exit(1)

    logger = create_logger(config["logLevel"])
    acquire_instance_lock(config["rootDir"])
    rag = None
    if not config["echoMode"]:
        pinecone = create_pinecone(config, logger)
        embeddings = create_gemini(config, logger)
        llm = create_answer_model(config, logger)
        index_info = load_index_info(pinecone, config, logger)
        rag = create_rag_pipeline(
            config=config,
            logger=logger,
            pinecone=pinecone,
            embeddings=embeddings,
            llm=llm,
            index_info=index_info,
        )
    else:
        logger.warn("ECHO_MODE is enabled. The bot will reply without searching Pinecone.")

    store = None
    hr = None
    if (config.get("db") or {}).get("enabled"):
        try:
            store = create_mysql_client(config, logger)
            hr = create_hr_services(store, logger, config)
            logger.info("MySQL HR client ready", {
                "host": config["db"]["host"],
                "database": config["db"]["name"],
            })
        except Exception as error:
            logger.error("MySQL client failed; live HR data disabled", {"message": str(error)})
    else:
        logger.warn("MySQL is not configured; live HR data disabled")

    bot = create_discord_bot(config=config, logger=logger, rag=rag, hr=hr)
    try:
        await bot.start(config["discord"]["token"])
    finally:
        await bot.close()
        release_instance_lock(config["rootDir"])


def main():
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(error)
        sys.exit(1)


if __name__ == "__main__":
    main()
