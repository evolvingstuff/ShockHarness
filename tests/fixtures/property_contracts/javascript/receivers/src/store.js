import { produces, requires } from "./vendor/contracts.js";

export class Store {
  save(text) {
    requires(text, "redacted");
    return text;
  }

  clean(text) {
    return produces(text.replace("@", "[at]"), "redacted");
  }
}

export const store = new Store();

export const Redactor = {
  save(text) {
    requires(text, "redacted");
    return text;
  },
  clean: (text) => produces(text.replace("@", "[at]"), "redacted"),
  echo: function (text) {
    return this.clean(text);
  },
};

export function saveHere(raw) {
  return store.save(raw);
}
