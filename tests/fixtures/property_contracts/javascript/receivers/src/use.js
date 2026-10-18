import { produces, requires } from "./vendor/contracts.js";
import { Redactor, Store, store } from "./store.js";

export function deliver(text) {
  requires(text, "redacted");
  return text;
}

export function throughSingleton(raw) {
  store.save(raw);
  return deliver(store.clean(raw));
}

export function throughObject(raw) {
  Redactor.save(raw);
  return deliver(Redactor.clean(raw));
}

export function throughConstructed(raw) {
  const local = new Store();
  local.save(raw);
  return local.save(local.clean(raw));
}

export function throughNew(raw) {
  return new Store().save(raw);
}

export function objectThis(raw) {
  return deliver(Redactor.echo(raw));
}

export class Pipeline {
  clean(text) {
    return produces(text.trim(), "redacted");
  }

  tidy(text) {
    return text;
  }

  run(raw) {
    return deliver(this.clean(raw));
  }

  leak(raw) {
    return deliver(this.tidy(raw));
  }
}

export class Base {
  clean(text) {
    return produces(text.trim(), "redacted");
  }

  run(raw) {
    return deliver(this.clean(raw));
  }
}

export class Loud extends Base {
  clean(text) {
    return text;
  }
}

export class Quiet extends Base {
  relay(raw) {
    return deliver(this.clean(raw));
  }
}
