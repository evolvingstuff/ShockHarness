import { preserves } from "./vendor/contracts.js";

export function head(x, n) {
  return preserves(x.slice(0, n), x);
}

export const first = (items) => preserves(items[0], items);

export function ident(x) {
  return x;
}
