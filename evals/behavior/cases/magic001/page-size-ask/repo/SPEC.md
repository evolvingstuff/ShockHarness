# Paging

The page size is deployment configuration. It comes from `PAGE_SIZE` in the
environment, validated at start-up; there is no built-in page size, and a
deployment without `PAGE_SIZE` must refuse to start.
