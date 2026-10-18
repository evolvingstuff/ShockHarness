from app.contracts import produces, requires
from app.store import Store, cache, store


def deliver(text):
    requires(text, "redacted")
    return text


def through_singleton(raw):
    store.save(raw)
    return deliver(store.clean(raw))


def through_constructed(raw):
    local = Store()
    local.save(raw)
    return local.save(local.clean(raw))


def through_the_class(raw):
    Store.check(raw)
    Store.build(raw)
    return Store.save(store, raw)


def through_a_new_instance(raw):
    return Store().save(raw)


def not_resolved(raw):
    deliver(store.size())
    return deliver(cache.clean(raw))


class Pipeline:
    def clean(self, text):
        return produces(text.strip(), "redacted")

    def tidy(self, text):
        return text

    def run(self, raw):
        return deliver(self.clean(raw))

    def leak(self, raw):
        return deliver(self.tidy(raw))


class Base:
    def clean(self, text):
        return produces(text.strip(), "redacted")

    def run(self, raw):
        return deliver(self.clean(raw))


class Loud(Base):
    def clean(self, text):
        return text


class Quiet(Base):
    def relay(self, raw):
        return deliver(self.clean(raw))
