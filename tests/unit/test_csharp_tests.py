"""G4 part three: C# test frameworks (NUnit, xUnit, MSTest, gdUnit4, GoDotTest) for
VERIFY001, VERIFY004 and ROLE001, and C#'s sleeps for SLEEP001; spec 21.1 decision 53."""

from pathlib import Path
from typing import Any

from shockharness.analysis import CACHE_BYPASSED, AnalysisOptions, analyze_text
from shockharness.api import analyze_paths
from shockharness.ir.csharp import extract_csharp_facts
from shockharness.ir.model import VerificationFacts
from shockharness.roles import ROLE_TEST
from shockharness.rules.verification import FileVerification, Renames, compare_revisions
from shockharness.source import SourceText

OPTIONS = AnalysisOptions(inline_suppressions=True, cache=CACHE_BYPASSED)
OPT_IN = 'include = ["**/*.cs"]\n'

SUITE = """\
using NUnit.Framework;
[TestFixture]
public class MathTests
{
    [Test]
    public void Adds() { Assert.That(Add(1, 2), Is.EqualTo(3)); }

    [TestCase(2)]
    public void Doubles(int x) { ClassicAssert.AreEqual(x * 2, Double(x)); }

    [Test, Ignore("flaky on CI")]
    public void Flaky() { Assert.True(true); }

    [Fact(Skip = "waiting on the save format")]
    public void Saves() { save.Should().NotBeNull(); }

    [Theory]
    public void Same(int x) { Assert.Equal(x, x); }

    [TestCase]
    public void Hits() { AssertThat(player.Hp).IsEqual(90); }

    [Test]
    public void Moves() { player.Position.ShouldBe(target); mock.Verify(m => m.Move()); }

    [TestMethod]
    public void Empty() { }

    [IgnoreUntil(Description = "physics rewrite")]
    [TestCase]
    public void Falls() { Prepare(); }

    private int Add(int a, int b) => a + b;
}

[Ignore]
public class Pending { [Test] public void Later() { true.ShouldBeTrue(); } }
"""


def facts(text: str) -> VerificationFacts:
    extracted = extract_csharp_facts(SourceText.from_text(text), "tests/MathTests.cs")
    assert extracted.parse_failure is None
    return extracted.verification


def test_cases_markers_and_tautologies() -> None:
    found = facts(SUITE)
    assert [(c.name, c.assertions, c.body_empty) for c in found.cases] == [
        ("MathTests.Adds", 1, False),
        ("MathTests.Doubles", 1, False),
        ("MathTests.Flaky", 1, False),
        ("MathTests.Saves", 1, False),
        ("MathTests.Same", 1, False),
        ("MathTests.Hits", 2, False),  # AssertThat(...) and the IsEqual chained on it
        ("MathTests.Moves", 2, False),
        ("MathTests.Empty", 0, True),
        ("MathTests.Falls", 0, False),
        ("Pending.Later", 1, False),
    ]
    tautologies = [(c.name, t.text) for c in found.cases for t in c.tautologies]
    assert tautologies == [
        ("MathTests.Flaky", "Assert.True(true)"),
        ("MathTests.Same", "Assert.Equal(x, x)"),
        ("Pending.Later", "true.ShouldBeTrue()"),
    ]
    assert [(m.kind, m.test, m.reason, m.span.line) for m in found.markers] == [
        ("skip", "MathTests.Flaky", "flaky on CI", 11),
        ("skip", "MathTests.Saves", "waiting on the save format", 14),
        ("skip", "MathTests.Falls", None, 29),
        ("skip", "Pending", None, 36),
    ]


SETTINGS: dict[str, Any] = {
    "enabled": True,
    "severity": "warning",
    "fail_on_unknown": False,
    "allowed_skip_reasons": [],
    "report_narrow_suppressions": False,
}


def verification(text: str) -> FileVerification:
    return FileVerification(
        path="tests/MathTests.cs",
        role=ROLE_TEST,
        failure=None,
        disabled=frozenset(),
        facts=facts(text),
        language="csharp",
        imports=(),
    )


BASE = """\
public class MathTests
{
    [Test]
    public void Adds() { Assert.That(Add(1, 2), Is.EqualTo(3)); }
}
"""


def test_verify001_and_verify004_on_csharp() -> None:
    head = BASE.replace("    [Test]\n", '    [Test, Ignore("later")]\n').replace(
        "Assert.That(Add(1, 2), Is.EqualTo(3));", "Assert.True(true);"
    )
    result = compare_revisions(
        {"tests/MathTests.cs": verification(BASE)},
        {"tests/MathTests.cs": verification(head)},
        Renames(available=True, error=None, head_to_base={}),
        SETTINGS,
        "a" * 40,
    )
    assert sorted((f.rule_id, f.span.line) for f in result.findings) == [
        ("VERIFY001", 3),
        ("VERIFY004", 4),
    ]


def project(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def test_role001_a_csharp_test_file_without_tests(empty_root: Path, make_config: Any) -> None:
    project(
        empty_root,
        {
            "tests/MathTests.cs": BASE,
            "tests/Helpers.cs": "public static class Helpers { public static int One() => 1; }\n",
            "src/Math.cs": "public static class Math2 { public static int Add() => 2; }\n",
        },
    )
    report = analyze_paths([empty_root], empty_root, make_config(OPT_IN), OPTIONS)
    found = [(f.rule_id, f.path) for f in report.findings if f.rule_id == "ROLE001"]
    assert found == [("ROLE001", "tests/Helpers.cs")]


SLEEPS = """\
public partial class Spawner : Node
{
    public async void Run()
    {
        Thread.Sleep(100);
        while (!ready) { await Task.Delay(50); }
        await Task.Delay(0);
        Thread.Sleep(0);
        await Task.Delay(TimeSpan.Zero);
        OS.DelayMsec(16);
        await ToSignal(GetTree().CreateTimer(1.0), "timeout");
        System.Threading.Thread.Sleep(5);
        await Task.Delay(TimeSpan.FromSeconds(1));
    }
}
"""


def test_sleep001_on_csharp(make_config: Any) -> None:
    result = analyze_text("Spawner.cs", "csharp", SLEEPS, make_config(OPT_IN), OPTIONS)
    found = [(f.span.line, f.message) for f in result.findings if f.rule_id == "SLEEP001"]
    assert [line for line, _message in found] == [5, 6, 10, 12, 13]
    assert found[1][1] == (
        "polls with a fixed sleep in a loop instead of waiting for the condition it needs: "
        "Task.Delay(50)"
    )
