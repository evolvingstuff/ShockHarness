// DEF001: parameter defaults in every function form; rest parameters are not defaults.
function plain(a, b = 1, c = "x") {
  return [a, b, c];
}

const arrow = (url, timeout = DEFAULT_TIMEOUT) => fetch(url, timeout);
const single = x => x;

class Service {
  constructor(client, cache = null) {
    this.client = client;
    this.cache = cache;
  }

  run(mode = "fast", ...rest) {
    return [mode, rest];
  }

  static create(options = {}) {
    return new Service(options.client);
  }
}

function destructured({ retries = 3, verbose }, [first = 0, second] = [], ...others) {
  return [retries, verbose, first, second, others];
}

function renamed({ size: n = 10, nested: { deep = true } }) {
  return [n, deep];
}

async function* generator(limit = 100) {
  yield limit;
}

function requiredOnly(host, port, timeout) {
  return [host, port, timeout];
}
