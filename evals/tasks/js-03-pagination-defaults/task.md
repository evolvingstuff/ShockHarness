# js-03-pagination-defaults: the caller always says how many

`src/pages.js` paginates with a default page size, previews with a fixed
length and reaches the last page with an arithmetic trick. Make every policy
number an explicit, validated argument.

Contract (encoded in `tests/pages.test.js`):

* `paginate(items, pageSize)` splits `items` into pages of `pageSize`; a
  `pageSize` below 1 throws `RangeError`.
* `preview(items, previewLength)` returns the first `previewLength` items; a
  `previewLength` below 0 throws `RangeError`.
* `lastPage(pages)` returns the last page and throws `RangeError` for an
  empty array.

No parameter defaults, no numeric literal other than 0 or 1, no suppression.
`shockharness check .` must pass.
