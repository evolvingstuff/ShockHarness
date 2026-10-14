// Expected with a boundary for TimeoutError on this file.
class Upstream extends Error {}

async function narrowNegatedGuard(url) {
  try {
    return await fetch(url);
  } catch (err) {
    if (!(err instanceof TimeoutError)) throw err;
    throw new Upstream(url, { cause: err });
  }
}

async function narrowBlockGuard(url) {
  try {
    return await fetch(url);
  } catch (err) {
    if (!(err instanceof TimeoutError)) {
      throw err;
    }
    throw new Upstream(url, { cause: err });
  }
}

async function narrowPositiveGuard(url) {
  try {
    return await fetch(url);
  } catch (err) {
    if (err instanceof TimeoutError) {
      throw new Upstream(url, { cause: err });
    } else {
      throw err;
    }
  }
}

async function guardedButSwallowed(url) {
  try {
    return await fetch(url);
  } catch (err) {
    if (!(err instanceof TimeoutError)) throw err;
  }
}

async function guardedButLogged(url) {
  try {
    return await fetch(url);
  } catch (err) {
    if (!(err instanceof TimeoutError)) throw err;
    console.warn("timeout", err);
  }
}

async function guardedWrongClass(url) {
  try {
    return await fetch(url);
  } catch (err) {
    if (!(err instanceof AbortError)) throw err;
    throw new Upstream(url, { cause: err });
  }
}

async function guardedBroadTry(url) {
  try {
    const response = await fetch(url);
    return await response.json();
  } catch (err) {
    if (!(err instanceof TimeoutError)) throw err;
    throw new Upstream(url, { cause: err });
  }
}

async function guardJoinedWithOr(url) {
  try {
    return await fetch(url);
  } catch (err) {
    if (!(err instanceof TimeoutError || err instanceof AbortError)) throw err;
    throw new Upstream(url, { cause: err });
  }
}

async function unguarded(url) {
  try {
    return await fetch(url);
  } catch (err) {
    throw new Upstream(url, { cause: err });
  }
}
