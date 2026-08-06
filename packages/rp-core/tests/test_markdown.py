"""The shared markdown parser, promoted from rp-docx by rp-pptx-spec section 12
step 2.

rp-docx's own parser tests moved with nothing else: they still live in
``rp_docx/tests/test_write.py`` exercising the re-exported names, which is the
point — the promotion is only honest if the leaf's tests pass unchanged. What is
tested here is the shared contract itself, and the one behaviour rp-docx never
had: HTML comment blocks surfaced as AST nodes.
"""

from __future__ import annotations

from rp_core.markdown import Block, Span, parse_inline, parse_markdown, split_row


class TestBlocks:
    def test_headings_cap_at_four(self):
        """rp-docx maps levels onto h1-h4 style roles and would KeyError above
        that; rp-pptx treats 3 and deeper alike. Neither wants a level 5."""
        blocks = parse_markdown("# a\n\n## b\n\n### c\n\n#### d\n\n##### e")
        assert [(b.kind, b.level) for b in blocks] == [
            ("heading", 1),
            ("heading", 2),
            ("heading", 3),
            ("heading", 4),
            ("heading", 4),
        ]

    def test_a_wrapped_paragraph_is_one_block(self):
        blocks = parse_markdown("one line\nand its continuation\n\nsecond")
        assert [b.text for b in blocks] == ["one line and its continuation", "second"]

    def test_list_nesting_becomes_levels(self):
        blocks = parse_markdown("- top\n  - nested\n    - deeper")
        assert [(b.kind, b.level) for b in blocks] == [
            ("bullet", 1),
            ("bullet", 2),
            ("bullet", 3),
        ]

    def test_a_pipe_table_needs_its_divider(self):
        table = parse_markdown("| a | b |\n|---|---|\n| 1 | 2 |")[0]
        assert table.kind == "table"
        assert table.rows == [["a", "b"], ["1", "2"]]
        assert parse_markdown("a | b")[0].kind == "paragraph"

    def test_thematic_breaks(self):
        assert [b.kind for b in parse_markdown("---\n\n***\n\n___")] == ["rule"] * 3

    def test_fenced_code_is_taken_literally(self):
        blocks = parse_markdown("```\n  indented\n# not a heading\n```")
        assert blocks[0].kind == "code"
        assert blocks[0].lines == ["  indented", "# not a heading"]

    def test_blank_input_is_no_blocks(self):
        assert parse_markdown("\n\n   \n") == []


class TestHtmlComments:
    """The section 12 step 2 addition. rp-pptx maps these to speaker notes, so
    they have to survive parsing as nodes rather than falling through to a
    paragraph and rendering as visible text."""

    def test_a_comment_is_its_own_block(self):
        blocks = parse_markdown("body text\n\n<!-- speaker notes here -->")
        assert [b.kind for b in blocks] == ["paragraph", "comment"]
        assert blocks[1].text == "speaker notes here"

    def test_a_comment_may_span_lines(self):
        blocks = parse_markdown("<!-- first\nsecond -->\n\nafter")
        assert blocks[0].kind == "comment"
        assert blocks[0].text == "first\nsecond"
        assert blocks[1].text == "after"

    def test_an_unterminated_comment_runs_to_the_end_and_does_not_hang(self):
        blocks = parse_markdown("<!-- never closed\nmore text")
        assert [b.kind for b in blocks] == ["comment"]

    def test_a_comment_does_not_swallow_the_paragraph_before_it(self):
        blocks = parse_markdown("intro\n<!-- note -->\ntail")
        assert [b.kind for b in blocks] == ["paragraph", "comment", "paragraph"]
        assert blocks[0].text == "intro"
        assert blocks[2].text == "tail"


class TestInline:
    def test_spans_carry_their_formatting(self):
        spans = parse_inline("plain **b** and *i* and `c`")
        assert (spans[0].text, spans[0].bold) == ("plain ", False)
        assert (spans[1].text, spans[1].bold) == ("b", True)
        assert (spans[3].text, spans[3].italic) == ("i", True)
        assert (spans[5].text, spans[5].code) == ("c", True)

    def test_underscore_forms_work_too(self):
        assert [(s.text, s.bold, s.italic) for s in parse_inline("__b__ _i_")] == [
            ("b", True, False),
            (" ", False, False),
            ("i", False, True),
        ]

    def test_a_link_keeps_label_and_href(self):
        spans = parse_inline("see [docs](https://example.invalid/d) now")
        assert (spans[1].text, spans[1].href) == ("docs", "https://example.invalid/d")

    def test_plain_text_is_one_span(self):
        assert [s.text for s in parse_inline("nothing special")] == ["nothing special"]

    def test_bold_is_not_read_as_two_italics(self):
        assert parse_inline("**x**") == [Span("x", bold=True)]


class TestSplitRow:
    def test_outer_pipes_are_optional(self):
        assert split_row("| a | b |") == ["a", "b"]
        assert split_row("a | b") == ["a", "b"]


def test_block_defaults_are_independent():
    """``rows`` and ``lines`` are mutable defaults; a dataclass field factory is
    the only thing keeping two blocks from sharing one list."""
    first, second = Block(kind="table"), Block(kind="table")
    first.rows.append(["x"])
    assert second.rows == []
