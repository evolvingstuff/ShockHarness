"""Database connection strings."""


def dsn(host: str, database: str, scheme: str = "postgresql") -> str:
    return f"{scheme}://{host}/{database}"
