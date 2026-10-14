// DEF003: '||' outside Boolean tests; Boolean logic is not a fallback.
function constants(items, name, count) {
  const list = items || [];
  const label = name || "anonymous";
  let total = count || 0;
  total ||= 1;
  render(items || {}, label);
  return { list: items || [], label: name || `anon` };
}

function alternatives(primary, secondary, tertiary) {
  const chosen = primary || secondary;
  return primary || secondary || tertiary;
}

function chains(a, b) {
  return a || b || "z";
}

function booleanLogic(a, b, flag) {
  if (a || b) {
    return true;
  }
  while (a || flag) {
    a = step(a);
  }
  const ok = a === b || flag;
  const done = !(a || b);
  const found = a > b || b > a;
  const both = a && b;
  for (let i = 0; a || b; i++) {
    step(i);
  }
  return ok || done || found || both;
}

function ternaries(x, y) {
  const first = x ? x : "empty";
  const second = !y ? "empty" : y;
  return [first, second];
}

const inArgument = call(a || b);
