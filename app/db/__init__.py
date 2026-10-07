"""MySQL backend that matches the Airtable client shape used by HR services."""

from app.db.client import MysqlClient, create_mysql_client

__all__ = ["MysqlClient", "create_mysql_client"]
