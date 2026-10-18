import { requires } from "./vendor/contracts.js";
import { fit, normalize } from "./stats.js";

export function remote(raw) {
  requires(raw, "numeric");
  return fit(normalize(raw));
}

export function remoteBad(raw) {
  requires(raw, "numeric");
  return fit(raw);
}

export function typo(x) {
  requires(x, "nmeric");
  return x;
}

export function computed(x, name) {
  requires(x, name);
  return x;
}

export function late(x) {
  const y = x;
  requires(x, "numeric");
  return y;
}

export function branch(x, flag) {
  if (flag) {
    requires(x, "numeric");
  }
  return x;
}
