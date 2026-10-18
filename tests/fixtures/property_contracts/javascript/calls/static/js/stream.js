import { produces, requires } from "./vendor/contracts.js";
import { fit, normalize } from "./stats.js";

async function loaded(raw) {
  requires(raw, "numeric");
  return normalize(raw);
}

function* series(raw) {
  requires(raw, "numeric");
  yield normalize(raw);
  yield normalize(raw);
}

function* delegated(raw) {
  requires(raw, "numeric");
  yield* series(raw);
}

async function* streamed(raw) {
  requires(raw, "numeric");
  yield normalize(raw);
}

export async function awaitedCall(raw) {
  requires(raw, "numeric");
  return fit(await loaded(raw));
}

export function generated(raw) {
  requires(raw, "numeric");
  for (const x of series(raw)) {
    fit(x);
  }
  for (const x of delegated(raw)) {
    fit(x);
  }
}

export async function streamedItems(raw, other) {
  requires(raw, "numeric");
  for await (const x of streamed(raw)) {
    fit(x);
  }
  for await (const x of other) {
    fit(x);
  }
}

export function notAwaited(raw) {
  requires(raw, "numeric");
  return fit(loaded(raw));
}

export function shortcut(x) {
  return produces(x, "normalized");
}
