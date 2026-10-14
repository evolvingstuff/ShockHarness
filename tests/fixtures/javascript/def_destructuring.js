// DEF002: destructuring defaults in declarations; DEF006 when the source is process.env.
const { retries = 3, verbose } = options;
const { size: n = 10, nested: { deep = true } } = config;
const [first = 0, second] = pair;
let { timeout = DEFAULT_TIMEOUT } = settings;
const { name } = user;
const [head, ...tail] = list;

const { PORT = "3000", HOST } = process.env;

function inner(payload) {
  const { items = [], total } = payload;
  return [items, total];
}

for (const { id, label = "none" } of rows) {
  use(id, label);
}

({ port = 80, host } = options);
({ SHELL = "/bin/sh" } = process.env);
