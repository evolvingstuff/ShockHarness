import { preserves, produces, requires } from "./vendor/contracts.js";

type Series = readonly number[];

export function normalize(x: Series): Series {
  requires(x, "numeric");
  return produces(preserves(scale(x) as Series, x), "normalized");
}

export function fit(x: Series): number {
  requires(x, "normalized", "numeric");
  return x.length;
}

export function pipeline(raw: Series): number {
  requires(raw, "numeric");
  return fit(normalize(raw));
}

export function shortcut(raw: Series): number {
  requires(raw, "numeric");
  return fit(raw);
}

export const asserted = (raw: Series): number => {
  requires(raw, "numeric");
  const x = normalize(raw)!;
  return fit(x satisfies Series);
};
