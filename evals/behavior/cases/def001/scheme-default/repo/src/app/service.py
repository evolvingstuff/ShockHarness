"""The two databases the service opens."""

from app.dsn import dsn


def main_database(host: str, scheme: str) -> str:
    return dsn(host, "orders", scheme)


def audit_database(host: str, scheme: str) -> str:
    return dsn(host, "audit", scheme)
