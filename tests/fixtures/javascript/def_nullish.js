// DEF004 for '??' on a plain identifier; DEF002 when the left side is a property or lookup.
function coalesce(count, other) {
  const n = count ?? 0;
  const label = count ?? other;
  let state = count;
  state ??= {};
  return n ?? label;
}

function properties(options, map, key) {
  const retries = options?.retries ?? 3;
  const mode = options.mode ?? "fast";
  const entry = map.get(key) ?? null;
  const indexed = options[key] ?? [];
  options.cache ??= new Map();
  return [retries, mode, entry, indexed];
}

function ternaries(value, other) {
  const a = value === undefined ? 100 : value;
  const b = value == null ? [] : value;
  const c = value !== undefined ? value : "x";
  const d = typeof value === "undefined" ? 0 : value;
  const e = value != null ? value : other;
  const f = value == null ? null : value.name;
  const g = value === null ? "on" : "off";
  const h = other.x == null ? 1 : other.x;
  return [a, b, c, d, e, f, g, h];
}

function membership(o, k) {
  const a = k in o ? o[k] : 0;
  const b = o.hasOwnProperty(k) ? o[k] : "none";
  const c = Object.hasOwn(o, "k") ? o.k : [];
  const d = !(k in o) ? 1 : o[k];
  const e = k in o ? o.other : 2;
  return [a, b, c, d, e];
}

const propagation = options?.deep?.value;
