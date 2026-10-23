# Proposal: call boundaries, "only these files may call it"

Status: **built** (2026-10-23, on Tom's go-ahead) as CALL001, spec 21.1 decision 55.
Differences from this text: the catalogs are `@disk_writes` and `@network` (underscores,
as TOML keys); a `.open` method whose first argument is not a mode is another API and
counts as a read. The measurement is in `docs/rules.md` under CALL001.
Companion to IMPORT002's named modules (`docs/proposal-import-boundaries-modules.md`).
Source: MetaList's policy note (2026-10-22), sections 3.1 (disk writes), 3.3 (logging
content), 3.5 (process and environment) and 3.2 for the browser.

## The gap

IMPORT002 can now keep `httpx` in one file. Several of the note's invariants are not
imports, though:

* **The capability is a call on something everyone imports.** Writing a file is
  `open(path, "w")`, `Path.write_text`, `os.replace`, `shutil.copy`, `tempfile.mkstemp`,
  `json.dump(obj, f)`, `sqlite3.connect(path)`. Forbidding `os`, `pathlib` or `json` by
  import is not practical.
* **The capability is a global.** The browser's network egress is `fetch(...)`,
  `new WebSocket(...)` or `navigator.sendBeacon(...)`; storage is `localStorage.setItem`
  or `indexedDB.open`. None is imported.
* **The capability depends on an argument.** `open(path)` reads, while `open(path, "w")`
  writes.

MetaList today (`app/`, at 556e6ebf):
* **Disk writes:** 16 production files write to disk with open-for-write,
  `write_text`/`write_bytes`, `tempfile`, `shutil`, `os.replace`/`os.rename` or
  `json.dump`. Another 12 call `sqlite3.connect`.
* **Network from the browser:** 29 browser files call `fetch` directly, 88 sites in all.

## The change: a rule beside IMPORT002 (placeholder ID CALL001)

```toml
[[tool.shockharness.rules.call_boundaries.forbidden]]
callers = ["app/**"]                                  # the files the entry binds (globs)
allowed_callers = ["app/storage/encrypted_writer.py"] # bound files exempt from it (globs)
calls = ["@disk-writes"]                              # what they may not call
reason = "plaintext never touches disk: write through app/storage/encrypted_writer.py"
```

`calls` names calls in three forms:

* **A qualified function, with everything below it:** `shutil` (every `shutil.*`),
  `tempfile`, `os.replace`, `sqlite3.connect`, `subprocess`. A JavaScript name works the
  same way: `fetch`, `localStorage.setItem`, `navigator.sendBeacon`; `fs` covers
  `fs.promises.writeFile`. Each call is resolved through the file's own imports, as the
  H5 rules do (`qualified_callee`), so `import shutil as sh; sh.copy(...)` is
  `shutil.copy`. A global (`fetch`, `open`) is matched when no import or local of the file
  rebinds it. `new X(...)` counts as a call of `X` (`new WebSocket(...)`).
* **A method on any receiver:** `.write_text`, `.write_bytes`. These are matched by name,
  since the receiver's type is not known, so they are reported with `approximate`
  confidence, as DEF002 does for `.get`.
* **A catalog the tool ships, `@name`:** `@disk-writes` and `@network` (Python, Node and
  browser) to start with, listed in `docs/configuration.md` and versioned like the
  must-use lists. A project can write its own names beside or instead of them.

### Calls that depend on an argument

`open`, `Path.open`, `io.open` and Node's `fs.open`/`fs.createWriteStream` write
depending on their mode. The `@disk-writes` catalog lists them with a mode condition:
* a literal mode containing `w`, `a`, `x` or `+` is a write;
* a literal read mode, or no mode at all, is not;
* a mode the analysis cannot read (a variable, a computed string) is an **unknown**
  finding (`status = unknown`), which `fail_on_unknown` can gate. It is never silently
  treated as a read.

A project entry can write the same condition as `open/mode=write`. This is the one
argument condition proposed; others wait for a case that needs them.

### Like IMPORT002 in everything else

* **The message names who may call it:** `calls shutil.copy, which only
  app/storage/encrypted_writer.py may call: plaintext never touches disk`.
* **VERIFY003 loosening:** removing an entry, dropping a call, exempting another file
  or narrowing `callers` loosens the policy.
* **Inline suppressions work** and are reasoned; `suppressions.forbidden` can refuse them
  under a path.
* **Python, JavaScript and TypeScript first.** C# (`File.WriteAllText`) follows the same
  catalog if a C# project asks.
* **The edit-time hook sees it:** a call is judged from the calling file alone.

## MetaList's note, written with it

**3.1, disk writes.**

```toml
[[tool.shockharness.rules.call_boundaries.forbidden]]
callers = ["server/**"]
allowed_callers = ["server/storage/encrypted_writer.py", "server/storage/snapshot.py",
                   "server/storage/shards.py", "server/diagnostics/bundle.py"]
calls = ["@disk-writes"]
reason = "plaintext never touches disk (docs/leak-prevention.md)"
```

The paths are the note's planned layout. Today's code lives under `app/`, where the same
entry (with `callers = ["app/**"]` and today's storage modules allowed) would report
some of the 16 files above and the 12 `sqlite3.connect` callers. Which ones is the
measurement the build would make. That list is the work of moving MetaList to the
note's layout.

**3.2, the browser's one outbound chokepoint.**

```toml
[[tool.shockharness.rules.call_boundaries.forbidden]]
callers = ["app/static/js/**"]
allowed_callers = ["app/static/js/modules/api-client.js"]
calls = ["@network"]
reason = "the browser talks to the server through one client"
```

That is 88 `fetch` sites in 29 files today. IMPORT002 cannot see a global.

**3.5, process and environment.** `subprocess` is already importable-only-where-allowed
with IMPORT002; `os.system`, `os.fork`, `os.urandom` and `os.getenv` are calls:

```toml
calls = ["os.system", "os.fork", "os.getenv", "os.urandom"]
```

Reading `os.environ[...]` is an attribute, not a call. A second key, `references`
(any use of a qualified name), would cover it. I'd add that only if the note's
`server/config.py` rule turns out to need it.

## Not this rule

* **3.3, logging content.** The note itself prefers a type check over a name list
  ("a value of the `Plaintext` newtype"). Property contracts already do this: declare
  `logging.info:0`-style sinks requiring a `redacted` property, and every path that
  reaches a log without it is PROP001. That needs no new rule. During the build I'd check
  that a method on a logger object (`logger.info(...)` after
  `logger = logging.getLogger(...)`) resolves as such a callee; if it does not, that is
  the fix, rather than a name heuristic.
* **3.6, the native bridge's capabilities.** One registration file and its allowlist:
  a project check, not a general rule.
* **Data flow.** The rule judges where a call is written, not what reaches it: an
  allowed caller that writes whatever it is handed still writes plaintext. That is what
  property contracts are for (a `ciphertext` property required at the writer).
* **Calls through a wrapper.** If `utils.save()` calls `open(..., "w")`, then `utils.py`
  is reported, not its callers. That is the right place: the wrapper becomes the
  allowed caller, or it moves.

## Cost

* **Facts:** every call site's callee text and, for the mode-dependent calls, the
  literal mode, in Python and JavaScript. Most of it exists already for the H5 catalogs;
  globals need a "not rebound in this file" check.
* **Rule:** a matcher like IMPORT002's (prefix names, `.method`, `@catalog`), the mode
  condition, the unknown finding, and the two catalogs.
* **Also:** the loosening clauses, docs, and tests:
  * qualified calls through imports and aliases;
  * a method on any receiver;
  * globals, and a global rebound locally;
  * `new` expressions;
  * the mode condition, including an unreadable mode;
  * `allowed_callers`, the loosening cases, and the hook on a single file.
* **Measurement:** MetaList read-only with the two entries above. Every finding gets
  read; the result is the number of findings, how many sit in files the note would
  allow, and how many are reads the catalog mistook for writes (target: none).
