from app.contracts import produces, requires


class Store:
    def save(self, text):
        requires(text, "redacted")
        return text

    def clean(self, text):
        return produces(text.replace("@", "[at]"), "redacted")

    @staticmethod
    def check(text):
        requires(text, "redacted")
        return text

    @classmethod
    def build(cls, text):
        requires(text, "redacted")
        return cls()

    @property
    def size(self):
        return len(self.__dict__)


store = Store()
cache = Store()
cache = None


def save_here(raw):
    return store.save(raw)
