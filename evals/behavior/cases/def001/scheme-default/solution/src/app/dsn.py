"""Database connection strings."""


def dsn(host: str, database: str, scheme: str) -> str:
    return f"{scheme}://{host}/{database}"
