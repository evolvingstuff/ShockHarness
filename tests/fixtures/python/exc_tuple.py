from requests.exceptions import ConnectionError, Timeout


def fetch(session, url):
    try:
        return session.get(url)
    except (Timeout, ConnectionError) as exc:
        raise Upstream(url) from exc


def fetch_mixed(session, url):
    try:
        return session.get(url)
    except (Timeout, Exception) as exc:
        raise Upstream(url) from exc


def fetch_unknown(session, url):
    try:
        return session.get(url)
    except (Timeout, NotImported) as exc:
        raise Upstream(url) from exc
