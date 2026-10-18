from app.contracts import preserves, produces, requires


def load_notes(path):
    return read(path)


def validate(path, root):
    requires(path)
    requires(root)
    return produces(normalized(path, root), "validated_path")


def checked(path):
    requires(path, "validated_path")
    return preserves(read(path), path)


def nothing(path):
    requires(path)
    log(path)


def returns_none(path):
    requires(path)
    if not path:
        return None
    return preserves(path, path)


class Store:
    def __init__(self, root):
        requires(root)
        self.root = root

    def fetch(self, path, *rest):
        requires(path, "validated_path")
        return read(path)

    @staticmethod
    def build(root):
        return Store(root)


def outer(path):
    requires(path)

    def inner(item):
        return item

    return preserves(inner(path), path)
