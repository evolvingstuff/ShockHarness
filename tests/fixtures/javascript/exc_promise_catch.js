// Expected with a boundary for TimeoutError on this file.
fetch(url).catch((err) => {
  console.error(err);
});

fetch(url).catch(function (err) {
  throw new Upstream(url, { cause: err });
});

fetch(url).catch(handleError);

fetch(url).then(parse, (err) => null);

fetch(url)
  .then((response) => response.json())
  .catch((err) => {
    if (!(err instanceof TimeoutError)) throw err;
    throw new Upstream(url, { cause: err });
  });

fetch(url).catch((err) => {
  if (!(err instanceof TimeoutError)) throw err;
  throw new Upstream(url, { cause: err });
});

pending.catch((err) => {
  if (!(err instanceof TimeoutError)) throw err;
  throw new Upstream("pending", { cause: err });
});

fetch(url).then(parse);
fetch(url).finally(cleanup);
