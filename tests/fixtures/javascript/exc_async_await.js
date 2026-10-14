async function sequential(urls) {
  const results = [];
  for (const url of urls) {
    try {
      results.push(await fetch(url));
    } catch (err) {
      results.push(null);
    }
  }
  return results;
}

async function awaitedChain(url) {
  try {
    const response = await fetch(url);
    return response.ok;
  } catch (err) {
    return false;
  }
}

const handler = async (event) => {
  try {
    await process(event);
  } catch (err) {
    throw new HandlerError(event.id, { cause: err });
  }
};

async function awaitInPromiseCatch(url) {
  return fetch(url).catch(async (err) => {
    await report(err);
    throw err;
  });
}
