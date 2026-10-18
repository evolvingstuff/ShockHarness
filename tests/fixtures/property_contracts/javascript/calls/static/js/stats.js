import { preserves, produces, requires } from "./vendor/contracts.js";

export function normalize(x) {
  requires(x, "numeric");
  return produces(preserves(center(x) / deviation(x), x), "normalized");
}

function center(x) {
  requires(x, "numeric");
  return preserves(x.map((v) => v - average(x)), x);
}

export function fit(x) {
  requires(x, "normalized", "numeric");
  return train(x);
}

export function pipeline(raw) {
  requires(raw, "numeric");
  return fit(normalize(raw));
}

export function shortcut(raw) {
  requires(raw, "numeric");
  return fit(raw);
}

export const shifted = (raw) => {
  requires(raw, "numeric");
  const x = normalize(raw) + 1;
  return fit(x);
};

export function throughRegistry(raw, ops) {
  requires(raw, "numeric");
  return fit(ops.normalize(raw));
}

export async function awaited(raw) {
  requires(raw, "numeric");
  return fit(await load(raw));
}

export function upload(raw) {
  requires(raw, "numeric");
  fetch("/series", normalize(raw));
  return fetch("/series", raw);
}
