# Proposal: import boundaries for named modules, and "only these files may import it"

Status: **built** (2026-10-22, on Tom's go-ahead), as proposed; spec 21.1 decision 44 is
amended. The measurement is in `docs/rules.md` under IMPORT002.
Extends IMPORT002 (spec 21.1 decision 44). Source: MetaList's policy note (2026-10-22,
passed on by Fable), sections 3.2, 3.4, 3.5 and 3.7.

## The gap

IMPORT002 forbids imports between the project's own files: both sides of an entry are
path globs, and an import is judged by the file it resolves to. The policy note's
security rules are mostly of another shape: *only module X may import library Y*.

* **Third-party and standard-library modules have no file.** `import httpx` or
  `from cryptography.hazmat.primitives.ciphers import Cipher` produce a module edge marked
  `external`, with the specifier as written and no target, so no `imported` glob can
  match it.
* **There is no "every file except these".** An entry binds the files its `importers`
  globs match. "Only `server/ai/outbound.py` may import `httpx`" would need a glob for
  every other file, kept up to date by hand.

## The change: two optional keys on each `forbidden` entry

```toml
[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["server/**"]                         # the files the entry binds (globs), as today
allowed_importers = ["server/ai/outbound.py"]     # NEW: bound files exempt from the entry (globs)
modules = ["httpx", "requests", "openai"]         # NEW: modules they may not import, by name
imported = []                                     # project files, by path (globs), as today
allowed_names = []                                # names they may still take, as today
reason = "one outbound chokepoint: call server/ai/outbound.py"
```

* **`modules`** names modules as code imports them, and matches the module or any
  submodule:
  * **Python:** `modules = ["cryptography.hazmat"]` matches `import cryptography.hazmat`,
    `from cryptography.hazmat.primitives import hashes` and
    `from cryptography import hazmat` (the name imported is the submodule). It doesn't
    match `import cryptography` alone. Relative imports never match, since they are the
    project's own files.
  * **JavaScript and TypeScript:** a package name matches the package and its paths
    (`openai`, `openai/resources`). A scoped name is whole (`@anthropic-ai/sdk`). Node's
    built-ins match with or without `node:` (`fs`, `node:fs`, `child_process`). Static
    `import`, `require` and dynamic `import("...")` with a literal all count.
  * Only edges that do not resolve to an analyzed file are matched by name. A project
    file is matched by `imported`, as today.
* **`allowed_importers`** takes files out of the entry. "Only X may import Y" becomes
  `importers = ["**"]` (or the production tree) with X under `allowed_importers`.
* An entry needs at least one of `imported` and `modules` (`imported` stops being
  required). `allowed_names` applies to both: `modules = ["hashlib"]` with
  `allowed_names = ["sha256"]` permits `from hashlib import sha256` and reports
  `import hashlib` and `from hashlib import scrypt`.
* **The message names who may import it:** `imports httpx, which only
  server/ai/outbound.py, server/controlplane/client.py may import here: one outbound
  chokepoint: call server/ai/outbound.py`.
* **VERIFY003 loosening:** removing a module from `modules` loosens, and so does adding
  a glob to `allowed_importers`. The "a new entry covers the old one" test grows two
  clauses: the new entry's modules include the old one's, and its allowed importers are
  among the old one's.
* **The edit-time hook sees more than before:** whether an import names `httpx` is known
  from the edited file alone. A project-file boundary needs the imported file in the
  same run.

## MetaList's note, written with it

**3.2, network egress.** One entry per kind of destination keeps each chokepoint to its
own libraries:

```toml
[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["server/**"]
allowed_importers = ["server/ai/outbound.py", "server/controlplane/client.py"]
modules = ["httpx", "requests", "aiohttp", "urllib.request", "http.client", "socket", "websockets"]
allowed_names = []
reason = "network calls go through server/ai/outbound.py or server/controlplane/client.py"

[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["server/**"]
allowed_importers = ["server/ai/providers/**"]
modules = ["openai", "anthropic"]
allowed_names = []
reason = "provider SDKs live in the adapters"

[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["server/**"]
allowed_importers = ["server/ai/outbound.py", "server/ai/providers/**"]
imported = ["server/ai/providers/**"]
allowed_names = []
reason = "adapters are reached only through server/ai/outbound.py"
```

Two more entries would cover `boto3`/`botocore` (only the uploader) and `smtplib` (only
the mail sender). `urllib.request` is listed rather than `urllib`, so `urllib.parse`
stays free. The third entry needs only `allowed_importers`: the provider adapters are
project files.

**3.4, cryptographic primitives.**

```toml
[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["server/**"]
allowed_importers = ["server/crypto/**"]
modules = ["cryptography.hazmat", "nacl", "argon2", "secrets"]
allowed_names = []
reason = "call crypto.encrypt_record / crypto.wrap_dek; primitives stay in server/crypto"

[[tool.shockharness.rules.import_boundaries.forbidden]]
importers = ["server/**"]
allowed_importers = ["server/crypto/**"]
modules = ["hashlib"]
allowed_names = ["sha256", "sha512"]
reason = "key derivation stays in server/crypto; digests are fine elsewhere"
```

**3.5, process and environment.** `subprocess`, `multiprocessing` and `ctypes` are
forbidden everywhere in `server/`. `prctl` and `resource` are forbidden except in
`server/hardening.py`.

**3.7, presentation state.** This one needs nothing new: `importers =
["server/presentation/web/**"]` and `imported = ["server/presentation/mobile/**"]` (and
the reverse) work today.

**On ShockHarness itself.** Only `history/git.py` imports `subprocess`, which matches
its catch boundary. An entry with `importers = ["src/**"]`, `allowed_importers =
["src/shockharness/history/git.py"]` and `modules = ["subprocess"]` passes now and
would catch a second subprocess call site the day one is written. I'd add it to
`.shockharness.toml` as the first real use.

## What it does not cover

* **Uses below the module.** `os.urandom`, `os.system`, `os.fork`, reading
  `os.environ`, `open(..., "w")` and the browser's `crypto.subtle` (a global, never
  imported) are calls or attributes, not imports. Forbidding `os` is not practical.
  These belong to the call-boundary idea in `docs/ideas.md` (BOUND001, 003, 005's
  remainder).
* **Re-exports through the chokepoint.** If `outbound.py` does `from httpx import Client`
  and another file imports `Client` from `outbound`, that file is allowed by this rule.
  A later check could report a chokepoint re-exporting a forbidden module's names.
* **Computed loading.** `importlib.import_module("httpx")`, `__import__` and
  `import(variable)` are not import facts. A literal-string `importlib.import_module`
  could become one later. Today it is invisible, as for project files.
* **Transitive reach.** As today, only direct imports are judged.

## Cost

* **Schema:** two keys, and `imported` becomes optional with an at-least-one check.
* **Rule:** a name matcher beside the glob matcher in `rules/import_boundaries.py`.
* **Also:** the loosening clauses, docs (configuration, rules, spec decision 44
  amended), and tests:
  * Python dotted, `from`-submodule and relative imports;
  * JavaScript packages, scoped packages, `node:` and dynamic `import()`;
  * `allowed_importers`, `allowed_names` on a module, the loosening cases, and the hook
    on a single file.
* **Measurement:** the ShockHarness entry above, plus MetaList read-only with one entry
  for its current AI and HTTP imports.
