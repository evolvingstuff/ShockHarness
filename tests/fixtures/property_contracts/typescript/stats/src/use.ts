import { fit, normalize } from "./stats";
import { requires } from "./vendor/contracts.js";

export async function later(raw: readonly number[]): Promise<number> {
  requires(raw, "numeric");
  const x: readonly number[] = await Promise.resolve(normalize(raw));
  return fit(x);
}

export function viaImport(raw: readonly number[]): number {
  requires(raw, "numeric");
  return fit(normalize(raw));
}
