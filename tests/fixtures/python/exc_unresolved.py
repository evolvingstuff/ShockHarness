import os.path
from pkg.compat import OSError
from . import errors
from .errors import RelativeError
from pkg.errors import Imported, Imported as Aliased
import pkg.errors as aliased_module

MyError = ValueError


class LocalError(Exception):
    pass


def unknown_name(x):
    try:
        return work(x)
    except NotImportedAnywhere as exc:
        raise Failed() from exc


def rebound_name(x):
    try:
        return work(x)
    except MyError as exc:
        raise Failed() from exc


def dynamic_expression(x, errors_to_catch):
    try:
        return work(x)
    except errors_to_catch[0] as exc:
        raise Failed() from exc


def call_expression(x):
    try:
        return work(x)
    except make_error_type() as exc:
        raise Failed() from exc


def relative_import(x):
    try:
        return work(x)
    except RelativeError as exc:
        raise Failed() from exc


def relative_module_attribute(x):
    try:
        return work(x)
    except errors.OtherError as exc:
        raise Failed() from exc


def local_class(x):
    try:
        return work(x)
    except LocalError as exc:
        raise Failed() from exc


def imported_and_aliased(x):
    try:
        return work(x)
    except (Imported, Aliased, aliased_module.Third) as exc:
        raise Failed() from exc


def dotted_import(x):
    try:
        return work(x)
    except os.error as exc:
        raise Failed() from exc


def nested_import(x):
    from pkg.nested import NestedError

    try:
        return work(x)
    except NestedError as exc:
        raise Failed() from exc


def import_shadows_builtin(x):
    try:
        return work(x)
    except OSError as exc:
        raise Failed() from exc
