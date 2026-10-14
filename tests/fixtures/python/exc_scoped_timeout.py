# Expected with a boundary for requests.exceptions.Timeout on this file.
import requests
from requests.exceptions import Timeout as HttpTimeout


class Upstream(Exception):
    pass


def narrow(session, url, timeout):
    try:
        response = session.get(url, timeout=timeout)
    except HttpTimeout as exc:
        raise Upstream(url) from exc
    return response.json()


def narrow_dotted(session, url, timeout):
    try:
        response = session.get(url, timeout=timeout)
    except requests.exceptions.Timeout as exc:
        raise Upstream(url) from exc
    return response.json()


def broad_try(session, url, timeout):
    try:
        response = session.get(url, timeout=timeout)
        data = response.json()
        validate(data)
    except HttpTimeout as exc:
        raise Upstream(url) from exc
    return data


def nested_call(session, url, timeout):
    try:
        data = parse(session.get(url, timeout=timeout))
    except HttpTimeout as exc:
        raise Upstream(url) from exc
    return data


def fallback_inside_boundary(session, url, timeout):
    try:
        return session.get(url, timeout=timeout)
    except HttpTimeout:
        return None


def wrong_exception(session, url, timeout):
    try:
        return session.get(url, timeout=timeout)
    except requests.exceptions.ConnectionError as exc:
        raise Upstream(url) from exc
