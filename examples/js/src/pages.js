// Pagination without implicit page sizes: the caller always says how many.

export function paginate(items, pageSize) {
  if (!(pageSize >= 1)) {
    throw new RangeError(`pageSize must be at least 1, got ${pageSize}`);
  }
  const pages = [];
  for (let start = 0; start < items.length; start += pageSize) {
    pages.push(items.slice(start, start + pageSize));
  }
  return pages;
}
