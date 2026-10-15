// Pagination without implicit sizes: the caller always says how many.

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

export function preview(items, previewLength) {
  if (!(previewLength >= 0)) {
    throw new RangeError(`previewLength must be at least 0, got ${previewLength}`);
  }
  return items.slice(0, previewLength);
}

export function lastPage(pages) {
  if (pages.length === 0) {
    throw new RangeError("lastPage of an empty array");
  }
  return pages[pages.length - 1];
}
