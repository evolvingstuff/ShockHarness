a = 30  # shockharness: ignore[MAGIC001] reason="RFC 1234 section 2 field width"
b = 30  # shockharness: ignore[MAGIC001]
c = 30  # shockharness: ignore[MAGIC001] reason=""
d = 30  # shockharness: ignore[NOPE001] reason="typo in rule id"
e = 1  # shockharness: ignore[MAGIC001] reason="nothing to suppress"
f = 30  # shockharness: ignore[MAGIC001, SUPP002] reason="multi id form"
g = 30  # shockharness: please ignore this
h = '# shockharness: ignore[MAGIC001] reason="inside a string, not a comment"'
i = 30  # unrelated comment mentioning no prefix
