"""H-TS: TypeScript (.ts, .tsx, .mts, .cts) through the JavaScript extractors, plus TYPE001's
TypeScript half (spec 21.1 decision 25)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, FileResult, analyze_text
from shockharness.api import analyze_paths
from shockharness.config import EffectiveConfig
from shockharness.discovery import discover
from shockharness.ir.javascript import extract_javascript_facts, extract_typescript_facts
from shockharness.rules import registry
from shockharness.source import SourceText

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)


def run(config: EffectiveConfig, path: str, text: str) -> FileResult:
    return analyze_text(path, "typescript", text, config, OPTIONS)


def rows(result: FileResult, rule: str) -> list[tuple[int, str]]:
    return [(f.span.line, f.message) for f in result.findings if f.rule_id == rule]


def write(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def project(root: Path, config: EffectiveConfig, files: dict[str, str]) -> Any:
    write(root, files)
    return analyze_paths([root], root, config, OPTIONS)


# -- discovery and parsing ---------------------------------------------------------------


def test_typescript_files_are_discovered_and_declarations_excluded(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    write(
        empty_root,
        {
            "src/a.ts": "",
            "src/b.tsx": "",
            "src/c.mts": "",
            "src/d.cts": "",
            "src/types.d.ts": "",
            "src/e.js": "",
        },
    )
    result = discover(empty_root, [empty_root], strict_config)
    assert [(f.relative, f.language) for f in result.files] == [
        ("src/a.ts", "typescript"),
        ("src/b.tsx", "typescript"),
        ("src/c.mts", "typescript"),
        ("src/d.cts", "typescript"),
        ("src/e.js", "javascript"),
    ]
    assert registry.TYPESCRIPT in registry.ALL_LANGUAGES


def test_tsx_and_angle_bracket_assertions_use_their_own_grammar() -> None:
    jsx = "export const v = <div className={name}>{n}</div>;\n"
    assertion = "export const v = <number>raw;\n"
    assert extract_typescript_facts(SourceText.from_text(jsx), "a.tsx").parse_failure is None
    assert extract_typescript_facts(SourceText.from_text(assertion), "a.ts").parse_failure is None
    assert extract_typescript_facts(SourceText.from_text(jsx), "a.ts").parse_failure is not None
    facts = extract_typescript_facts(SourceText.from_text(assertion), "a.ts")
    assert facts.language == "typescript"
    assert facts.parser.startswith("tree-sitter-typescript ")


def test_test_and_config_roles_cover_typescript(strict_config: EffectiveConfig) -> None:
    text = "export function f(x: number): number { return x * 3; }\n"
    assert run(strict_config, "src/a.test.ts", text).role == "test"
    assert run(strict_config, "src/ui/a.spec.tsx", text).role == "test"
    assert run(strict_config, "vite.config.ts", text).role == "config"
    assert run(strict_config, "src/a.ts", text).role == "production"


# -- the JavaScript rules on TypeScript syntax --------------------------------------------


def test_magic001_types_enums_and_the_number_keyword(strict_config: EffectiveConfig) -> None:
    text = (
        "enum Color { Red = 3 }\n"  # 1: an enum value is a runtime value
        "type Port = 8080 | 1;\n"  # 2: a literal type
        "export function f(x: number, y: Array<number>): 5 {\n"  # 3: `number` is a keyword
        "  return 5 as 5;\n"  # 4: the value, then the type
        "}\n"
    )
    found = [
        (f.span.line, f.message.split(" justification ")[1])
        for f in run(strict_config, "src/a.ts", text).findings
        if f.rule_id == "MAGIC001"
    ]
    assert found == [
        (1, "in executable code"),
        (2, "in a type annotation"),
        (3, "in a type annotation"),
        (4, "in executable code"),
        (4, "in a type annotation"),
    ]


def test_def001_typed_parameters(strict_config: EffectiveConfig) -> None:
    text = (
        "export function f(name: string = 'x', count?: number, port = PORT): void {}\n"
        "export class A {\n"
        "  constructor(private value: number = ZERO, readonly other?: string) {}\n"
        "  m(this: A, { a = NONE }: { a?: string }): void {}\n"
        "}\n"
    )
    found = [f.message for f in run(strict_config, "src/a.ts", text).findings]
    assert [m for m in found if m.startswith("parameter")] == [
        "parameter 'name' of f has a default value: 'x'",
        "parameter 'port' of f has a default value: PORT",
        "parameter 'value' of constructor has a default value: ZERO",
    ]
    assert any(m.startswith("destructuring default for 'a' in parameters") for m in found)


def test_parameters_are_locals_in_both_languages() -> None:
    js = "let cache = [];\nexport function f(cache, { a }, [b = 1]) { cache.push(a, b); }\n"
    ts = (
        "let cache: string[] = [];\n"
        "export function f(cache: string[], { a }: T, [b = 1]: U, this: V) { cache.push(a); }\n"
    )
    for facts in (
        extract_javascript_facts(SourceText.from_text(js), "a.js"),
        extract_typescript_facts(SourceText.from_text(ts), "a.ts"),
    ):
        (unit,) = [u for u in facts.functions if u.name == "f"]
        assert {"cache", "a", "b"} <= unit.locals
        assert unit.writes == ()
    (ts_unit,) = [
        u
        for u in extract_typescript_facts(SourceText.from_text(ts), "a.ts").functions
        if u.name == "f"
    ]
    assert ts_unit.parameters == 3  # `this: V` declares the receiver; it is not a parameter


def test_classes_fields_and_type_wrappers(strict_config: EffectiveConfig) -> None:
    text = (
        "import { exec } from 'node:child_process';\n"
        "export abstract class Service {\n"
        "  abstract start(): Promise<void>;\n"
        "  static boot = exec('ls');\n"  # 4: a static field runs at import
        "  handler = (e: Event) => { try { run(e); } catch (err) { console.log(err); } };\n"
        "}\n"
        "export function g(opts: Opts): string {\n"
        "  return (opts.name as string) || 'anon';\n"  # 8: DEF003 through the assertion
        "}\n"
    )
    result = run(strict_config, "src/a.ts", text)
    assert [f.span.line for f in result.findings if f.rule_id == "IMPORT001"] == [4]
    assert [f.span.line for f in result.findings if f.rule_id == "DEF003"] == [8]
    (handler,) = [f for f in result.findings if f.rule_id == "EXC002"]
    assert handler.scope == "Service.handler"


def test_javascript_samples_give_the_same_findings_as_typescript(
    strict_config: EffectiveConfig,
) -> None:
    """JavaScript is (nearly) TypeScript: the same text must give the same findings."""
    text = (
        "import { execSync } from 'node:child_process';\n"
        "let calls = 0;\n"
        "export async function f(cmd, opts = {}) {\n"
        "  calls += 1;\n"
        "  execSync('ls ' + cmd);\n"
        "  load();\n"
        "  try { return opts.value ?? 30; } catch (e) { return null; }\n"
        "}\n"
        "async function load() { return 1; }\n"
        "export function isAllowed(user) { return true; }\n"
    )

    def shape(result: FileResult) -> list[tuple[str, int, int, str]]:
        return [(f.rule_id, f.span.line, f.span.column, f.message) for f in result.findings]

    javascript = analyze_text("src/a.js", "javascript", text, strict_config, OPTIONS)
    typescript = run(strict_config, "src/a.ts", text)
    assert len(shape(javascript)) > len(["MAGIC001", "DEF001", "PROCESS001"])
    assert shape(typescript) == shape(javascript)


# -- imports and the module graph ---------------------------------------------------------


def test_type_only_imports_are_erased_and_import_require_is_an_import() -> None:
    text = (
        'import type { T } from "./t";\n'
        'import { type U, V } from "./u";\n'
        'import { type Only } from "./only";\n'
        'export type { W } from "./w";\n'
        'export { type X, Y } from "./xy";\n'
        'import fs = require("node:fs");\n'
        'import "./side";\n'
    )
    facts = extract_typescript_facts(SourceText.from_text(text), "a.ts")
    assert [(i.span.line, i.kind, i.module, i.names) for i in facts.imports] == [
        (2, "names", "./u", (("V", "V"),)),
        (5, "reexport", "./xy", (("Y", "Y"),)),
        (6, "module", "node:fs", (("", "fs"),)),
        (7, "module", "./side", ()),
    ]
    assert [b.name for b in facts.bindings] == ["V", "fs"]


def test_js_specifiers_resolve_to_typescript_sources_and_type_cycles_do_not_count(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    report = project(
        empty_root,
        strict_config,
        {
            "src/a.ts": (
                'import { b } from "./b.js";\nexport function a(): number { return b(); }\n'
            ),
            "src/b.ts": (
                'import type { A } from "./a";\nimport { c } from "./c";\n'
                "export function b(): number { return c(); }\n"
            ),
            "src/c.mts": 'import { a } from "./a.js";\nexport function c(): number { return 1; }\n',
            "src/d.ts": 'import { a } from "./a";\nexport const d = (): number => a();\n',
            # e -> f at run time; f -> e by a type-only import: no cycle
            "src/e.ts": 'import { f } from "./f";\nexport function e(): number { return f(); }\n',
            "src/f.ts": (
                'import type { E } from "./e";\nimport { type G } from "./e";\n'
                "export function f(): number { return 1; }\n"
            ),
        },
    )
    edges = sorted((e["from"], e["to"]["id"]) for e in report.metrics["graph"]["edges"])
    assert edges == [
        ("src/a.ts::a", "src/b.ts::b"),
        ("src/b.ts::b", "src/c.mts::c"),
        ("src/d.ts::d", "src/a.ts::a"),
        ("src/e.ts::e", "src/f.ts::f"),
    ]
    cycles = [c["modules"] for c in report.metrics["graph"]["cycles"]]
    assert cycles == [["src/a.ts", "src/b.ts", "src/c.mts"]]
    (finding,) = [f for f in report.findings if f.rule_id == "CPLX005"]
    assert "3 TypeScript module(s)" in finding.message


def test_role001_ignores_type_only_imports_of_test_files(
    empty_root: Path, strict_config: EffectiveConfig
) -> None:
    report = project(
        empty_root,
        strict_config,
        {
            "src/a.ts": (
                'import type { Fixture } from "../tests/fixture";\n'
                'import { helper } from "../tests/helper";\n'
                "export function a(f: Fixture): string { return helper(f.name); }\n"
            ),
            "tests/fixture.ts": "export interface Fixture { name: string }\n",
            "tests/helper.ts": "export function helper(x: string): string { return x; }\n",
            "tests/a.test.ts": (
                'import { a } from "../src/a";\nit("a", () => expect(a).toBeDefined());\n'
            ),
        },
    )
    imports = [(f.path, f.span.line) for f in report.findings if f.rule_id == "ROLE001"]
    assert ("src/a.ts", 2) in imports
    assert ("src/a.ts", 1) not in imports


# -- TYPE001 ------------------------------------------------------------------------------


TYPED = (
    "export function f(raw: any, xs: Array<any>): Map<string, any> {\n"  # 1: three any
    "  const a = raw as number;\n"  # 2
    "  const b = <string>raw;\n"  # 3
    "  const c = raw as unknown as Date;\n"  # 4: one assertion
    "  const d = [ONE] as const;\n"  # not an assertion
    "  const e = raw!.field;\n"  # 6: non-null
    "  // @ts-ignore\n"  # 7
    "  const g: number = a;\n"
    "  // @ts-expect-error\n"  # 9
    "  return new Map([[b, c], [d, e], [g, g]]);\n"
    "}\n"
)


def test_type001_typescript_kinds(strict_config: EffectiveConfig) -> None:
    found = rows(run(strict_config, "src/a.ts", TYPED), "TYPE001")
    assert [line for line, _ in found] == [1, 1, 1, 2, 3, 4, 6, 7, 9]
    messages = [message for _, message in found]
    assert messages[0] == "any turns type checking off for this value: raw: any"
    assert messages[2] == "any turns type checking off for this value: Map<string, any>"
    assert messages[3] == "a type assertion asserts a type without checking it: raw as number"
    assert messages[6].startswith("a non-null assertion (!) claims the value is never null")
    assert messages[7] == "@ts-ignore silences the type checker on this line"


def test_type001_switches_and_javascript(make_config: Callable[[str], EffectiveConfig]) -> None:
    narrowed = make_config(
        "[tool.shockharness.rules.types]\n"
        "report_any = false\nreport_cast = false\nreport_non_null = false\n"
    )
    assert [line for line, _ in rows(run(narrowed, "src/a.ts", TYPED), "TYPE001")] == [7, 9]
    assert any("rules.types.report_non_null is false" in d for d in narrowed.deviations)
    javascript = analyze_text(
        "src/a.js", "javascript", "// @ts-ignore\nexport const a = b;\n", make_config(""), OPTIONS
    )
    assert "TYPE001" not in javascript.rules_applied
    assert registry.TYPE001.languages == ("python", "typescript", "csharp")


@pytest.mark.parametrize("suffix", [".ts", ".tsx", ".mts", ".cts"])
def test_every_suffix_is_typescript(suffix: str, strict_config: EffectiveConfig) -> None:
    result = run(strict_config, "src/a" + suffix, "export const v = raw!;\n")
    assert result.language == "typescript"
    assert [line for line, _ in rows(result, "TYPE001")] == [1]
