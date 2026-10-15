// Pagination (starting point: policy numbers baked into the code).

export function paginate(items, pageSize = 10) {
  const pages = [];
  for (let start = 0; start < items.length; start += pageSize) {
    pages.push(items.slice(start, start + pageSize));
  }
  return pages;
}

export function preview(items) {
  return items.slice(0, 3);
}

export function lastPage(pages) {
  return pages[pages.length - 1] ?? [];
}
