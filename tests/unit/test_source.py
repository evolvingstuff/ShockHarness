from shockharness.source import SourceText


def test_line_splitting_handles_all_line_breaks() -> None:
    source = SourceText.from_text("a\r\nb\rc\nd")
    assert source.lines == ("a", "b", "c", "d")
    assert source.line_count == 4


def test_trailing_newline_does_not_count_as_a_line() -> None:
    assert SourceText.from_text("a\nb\n").line_count == 2
    assert SourceText.from_text("a\nb").line_count == 2
    assert SourceText.from_text("").line_count == 0


def test_byte_offset_to_character_column() -> None:
    source = SourceText.from_text('x = "héllo"; y = 30')
    # "héllo" has one two-byte character; byte 19 is the character at 1-based column 19.
    assert source.column_from_byte_offset(1, 0) == 1
    assert source.column_from_byte_offset(1, 19) == 19
    emoji = SourceText.from_text('e = "😀"; z = 2')
    assert emoji.column_from_byte_offset(1, 16) == 14


def test_out_of_range_line_is_empty_not_an_error() -> None:
    source = SourceText.from_text("a")
    assert source.line_text(0) == ""
    assert source.line_text(5) == ""
    assert source.excerpt(5) == ""


def test_excerpt_is_stripped_and_truncated() -> None:
    long_line = "    x = " + "1" * 300
    source = SourceText.from_text(long_line)
    excerpt = source.excerpt(1)
    assert excerpt.startswith("x = 111")
    assert excerpt.endswith("...")
    assert len(excerpt) == 120
