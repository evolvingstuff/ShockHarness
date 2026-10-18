import { requires } from "./vendor/contracts.js";

export function deliver(text) {
  requires(text, "redacted");
  return text;
}

// A method of an exported object literal reads names its enclosing unit never binds
// (`document`, `controller`): each method is its own unit.
export const Tracker = {
  start() {
    document.addEventListener("keydown", () => {});
  },
  show(raw) {
    return deliver(raw);
  },
};

export function body(chunk) {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(chunk);
    },
  });
}
