# py-04-pagination-numbers: policy numbers come from the caller

`src/app/pages.py` paginates with a default page size, a hard-coded page cap
and a negative index. Move every policy number into a validated settings
object and leave only arithmetic identity literals (0 and 1) in the code.

Contract (encoded in `tests/test_pages.py`):

* `PageSettings(page_size, max_pages)`; `load_page_settings(raw)` reads
  `PAGE_SIZE` and `MAX_PAGES` from a mapping, both required integers, both at
  least 1 (`ValueError` otherwise, `KeyError` when missing).
* `paginate(items, settings)` splits `items` into pages of `page_size` and
  raises `ValueError` when more than `max_pages` pages would result.
* `last_item(items)` returns the last element and raises `IndexError` on an
  empty list.

No parameter defaults, no numeric literal other than 0 or 1, no suppression.
