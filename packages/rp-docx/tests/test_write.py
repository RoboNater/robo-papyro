"""Creating and editing documents: markdown, replacement, properties, revisions."""

from __future__ import annotations

import pytest

from rp_docx import ooxml, templates
from rp_docx.docx import read, write
from rp_docx.errors import RpDocxError, TemplateError
from rp_docx.models import CoreProperties


class TestMarkdownParsing:
    def test_headings_cap_at_four(self):
        blocks = write.parse_markdown("# a\n\n## b\n\n### c\n\n#### d\n\n##### e")
        assert [(b.kind, b.level) for b in blocks] == [
            ("heading", 1),
            ("heading", 2),
            ("heading", 3),
            ("heading", 4),
            ("heading", 4),
        ]

    def test_a_wrapped_paragraph_is_one_paragraph(self):
        blocks = write.parse_markdown("one line\nand its continuation\n\nsecond")
        assert [b.text for b in blocks] == ["one line and its continuation", "second"]

    def test_bullets_and_numbers(self):
        blocks = write.parse_markdown("- a\n- b\n\n1. c\n2. d")
        assert [b.kind for b in blocks] == ["bullet", "bullet", "numbered", "numbered"]

    def test_nested_list_levels(self):
        blocks = write.parse_markdown("- top\n  - nested")
        assert [b.level for b in blocks] == [1, 2]

    def test_a_pipe_table_needs_its_divider(self):
        """Without the divider it is a paragraph that happens to contain pipes."""
        table = write.parse_markdown("| a | b |\n|---|---|\n| 1 | 2 |")
        assert table[0].kind == "table"
        assert table[0].rows == [["a", "b"], ["1", "2"]]
        assert write.parse_markdown("a | b")[0].kind == "paragraph"

    def test_horizontal_rules(self):
        assert [b.kind for b in write.parse_markdown("---\n\n***\n\n___")] == [
            "rule",
            "rule",
            "rule",
        ]

    def test_a_fenced_code_block_keeps_its_lines_verbatim(self):
        blocks = write.parse_markdown("```\n  indented\n# not a heading\n```")
        assert blocks[0].kind == "code"
        assert blocks[0].lines == ["  indented", "# not a heading"]

    def test_blank_input_produces_no_blocks(self):
        assert write.parse_markdown("\n\n   \n") == []


class TestInlineParsing:
    def test_bold_italic_and_code(self):
        spans = write.parse_inline("plain **b** and *i* and `c`")
        assert [(s.text, s.bold, s.italic, s.code) for s in spans] == [
            ("plain ", False, False, False),
            ("b", True, False, False),
            (" and ", False, False, False),
            ("i", False, True, False),
            (" and ", False, False, False),
            ("c", False, False, True),
        ]

    def test_bold_is_not_read_as_two_italics(self):
        assert [(s.text, s.bold) for s in write.parse_inline("**x**")] == [("x", True)]

    def test_underscore_emphasis(self):
        assert [(s.text, s.bold, s.italic) for s in write.parse_inline("__b__ _i_")] == [
            ("b", True, False),
            (" ", False, False),
            ("i", False, True),
        ]

    def test_links_carry_their_href(self):
        spans = write.parse_inline("see [docs](https://example.invalid/d) now")
        assert spans[1].text == "docs"
        assert spans[1].href == "https://example.invalid/d"

    def test_plain_text_is_one_span(self):
        assert [s.text for s in write.parse_inline("nothing special")] == ["nothing special"]


class TestCreate:
    def test_creating_from_markdown(self, tmp_path, markdown_source):
        out = write.create(tmp_path / "out.docx", markdown=markdown_source)
        headings = read.get_index(out).headings
        assert [(h.level, h.text) for h in headings][:3] == [
            (1, "Report Title"),
            (2, "Findings"),
            (3, "Detail"),
        ]

    def test_the_table_survives_the_round_trip(self, tmp_path, markdown_source):
        out = write.create(tmp_path / "out.docx", markdown=markdown_source)
        tables = read.get_tables(out)
        assert tables[0].data == [["Region", "Units"], ["North", "120"], ["South", "95"]]

    def test_inline_formatting_survives_the_round_trip(self, tmp_path):
        out = write.create(tmp_path / "out.docx", markdown="Some **bold** and *italic*.")
        paragraph = next(p for p in read.get_text(out, runs_wanted=True) if "bold" in p.text)
        assert any(r.bold and r.text == "bold" for r in paragraph.runs)
        assert any(r.italic and r.text == "italic" for r in paragraph.runs)

    def test_a_hyperlink_becomes_a_real_relationship(self, tmp_path):
        """A document whose links only look like links is the kind of near-miss
        that survives review."""
        out = write.create(tmp_path / "out.docx", markdown="see [docs](https://example.invalid/d)")
        root = ooxml.parse_part(out, ooxml.DOCUMENT_PART)
        assert ooxml.xpath(root, ".//w:hyperlink")
        rels = ooxml.read_part(out, "word/_rels/document.xml.rels").decode("utf-8")
        assert "https://example.invalid/d" in rels

    def test_a_horizontal_rule_becomes_a_border(self, tmp_path):
        out = write.create(tmp_path / "out.docx", markdown="a\n\n---\n\nb")
        root = ooxml.parse_part(out, ooxml.DOCUMENT_PART)
        assert ooxml.xpath(root, ".//w:pBdr/w:bottom")

    def test_the_title_is_set_as_a_core_property(self, tmp_path):
        out = write.create(tmp_path / "out.docx", title="Annual Review")
        assert read.get_properties(out).title == "Annual Review"

    def test_page_size_defaults_to_letter(self, tmp_path):
        out = write.create(tmp_path / "out.docx")
        assert templates.inspect_template(out).page_size == "Letter"

    def test_page_size_a4(self, tmp_path):
        out = write.create(tmp_path / "out.docx", page_size="a4")
        assert templates.inspect_template(out).page_size == "A4"

    def test_an_unknown_page_size_is_an_error(self, tmp_path):
        with pytest.raises(RpDocxError, match="Unknown page size"):
            write.create(tmp_path / "out.docx", page_size="foolscap")

    def test_a4_from_the_template_beats_the_letter_default(
        self, tmp_path, house_like_template, markdown_source
    ):
        """Spec section 11.2: a house template that is A4 is A4 whatever the
        default says."""
        out = write.create(
            tmp_path / "out.docx", markdown="# Report Title", template=house_like_template
        )
        assert templates.inspect_template(out).page_size == "A4"

    def test_the_house_template_round_trips_its_styles(
        self, tmp_path, house_like_template, house_styles
    ):
        """Spec section 11.2: create → read → house styles preserved."""
        out = write.create(
            tmp_path / "out.docx",
            markdown="# Title\n\nBody paragraph.\n\n- a bullet",
            template=house_like_template,
        )
        styles = {p.style for p in read.get_text(out)}
        assert house_styles["h1"] in styles
        assert house_styles["body"] in styles
        assert house_styles["bullet"] in styles

    def test_the_header_and_section_survive(self, tmp_path, house_like_template):
        out = write.create(tmp_path / "out.docx", template=house_like_template)
        assert templates.inspect_template(out).has_letterhead is True
        assert read.get_index(out).has_headers_footers is True

    def test_a_hostile_template_fails_loudly(self, tmp_path, hostile_template):
        """Spec section 11.2: never a silent fallback. hostile has no
        "Heading 1", so markdown with an H1 must name the missing style and list
        what the template does have."""
        with pytest.raises(TemplateError) as exc:
            write.create(tmp_path / "out.docx", markdown="# Title", template=hostile_template)
        message = str(exc.value)
        assert "'Heading 1'" in message
        assert "Heading 2" in message

    def test_a_hostile_template_still_works_for_content_it_can_style(
        self, tmp_path, hostile_template
    ):
        """The check is per style at the point of use — a document with no H1
        does not need an H1 style."""
        out = write.create(
            tmp_path / "out.docx", markdown="Just a paragraph.", template=hostile_template
        )
        assert any(p.text == "Just a paragraph." for p in read.get_text(out))

    def test_a_code_block_works_without_a_code_style(self, tmp_path):
        """Word ships no code style, so an unset `code` role means the template
        has none — code renders in the body style with a monospace font rather
        than failing. Spec section 3 defaults this to "Source Code", which is a
        LibreOffice name and makes every code block fail on Word's defaults."""
        out = write.create(tmp_path / "out.docx", markdown="```\nprint('x')\n```")
        paragraph = next(p for p in read.get_text(out, runs_wanted=True) if "print" in p.text)
        assert paragraph.style == "Normal"
        assert paragraph.runs[0].font == write.CODE_FONT

    def test_a_code_style_is_used_when_the_stylemap_names_one(
        self, tmp_path, house_like_template, house_styles
    ):
        out = write.create(
            tmp_path / "out.docx", markdown="```\nx\n```", template=house_like_template
        )
        assert any(p.style == house_styles["code"] for p in read.get_text(out))

    def test_a_named_but_missing_code_style_still_fails_loudly(self, tmp_path, minimal_template):
        """Optional means "may be unset", not "may be wrong"."""
        copy = tmp_path / "m.dotx"
        copy.write_bytes(minimal_template.read_bytes())
        templates.stylemap_path(copy).write_text('{"code": "Nonexistent"}', encoding="utf-8")
        with pytest.raises(TemplateError, match="Nonexistent"):
            write.create(tmp_path / "out.docx", markdown="```\nx\n```", template=copy)

    def test_creating_from_a_dotx_writes_a_document(self, tmp_path, minimal_template):
        out = write.create(tmp_path / "out.docx", template=minimal_template)
        assert not ooxml.is_template(out)

    def test_creating_a_dotx_writes_a_template(self, tmp_path, minimal_template):
        out = write.create(tmp_path / "out.dotx", template=minimal_template)
        assert ooxml.is_template(out)

    def test_an_unknown_template_name_is_reported(self, tmp_path, templates_env):
        with pytest.raises(TemplateError, match="No template called"):
            write.create(tmp_path / "out.docx", template="nonexistent")


class TestAppend:
    def test_appending_leaves_the_original_alone(self, simple_docx, tmp_path):
        before = len(read.get_text(simple_docx))
        out = write.append_markdown(simple_docx, "## Added", output=tmp_path / "out.docx")
        assert len(read.get_text(simple_docx)) == before
        assert len(read.get_text(out)) == before + 1

    def test_appending_uses_the_documents_own_styles(self, simple_docx, tmp_path):
        out = write.append_markdown(simple_docx, "## Added", output=tmp_path / "out.docx")
        assert read.get_text(out)[-1].style == "Heading 2"

    def test_appending_in_place(self, simple_docx, tmp_path):
        copy = tmp_path / "copy.docx"
        copy.write_bytes(simple_docx.read_bytes())
        before = len(read.get_text(copy))
        write.append_markdown(copy, "Extra.")
        assert len(read.get_text(copy)) == before + 1


class TestReplace:
    def test_a_placeholder_split_across_runs_is_replaced(self, split_runs_docx, tmp_path):
        result = write.replace_text(
            split_runs_docx, {"{{ client.name }}": "Ada"}, output=tmp_path / "out.docx"
        )
        assert result.replacements["{{ client.name }}"] == 2  # body and table cell
        assert "Dear Ada, welcome." in [p.text for p in read.get_text(result.output)]

    def test_replacement_reaches_table_cells_headers_and_footers(self, split_runs_docx, tmp_path):
        """Body-only replacement is the classic silent bug (spec section 6)."""
        result = write.replace_text(
            split_runs_docx,
            {"{{ client.name }}": "Ada", "{{ city }}": "Bath"},
            output=tmp_path / "out.docx",
        )
        assert "body" in result.locations
        assert any(loc.startswith("table:") for loc in result.locations)
        assert any(loc.startswith("header:") for loc in result.locations)
        assert any(loc.startswith("footer:") for loc in result.locations)

    def test_header_and_footer_text_is_actually_rewritten(self, split_runs_docx, tmp_path):
        out = write.replace_text(
            split_runs_docx, {"{{ city }}": "Bath"}, output=tmp_path / "out.docx"
        ).output
        headers = [n for n in ooxml.part_names(out) if n.startswith("word/header")]
        text = ooxml.read_part(out, headers[0]).decode("utf-8")
        assert "Head Bath" in text.replace("</w:t><w:t>", "").replace(
            '</w:t><w:t xml:space="preserve">', ""
        )

    def test_a_key_that_matched_nothing_is_reported_as_zero(self, simple_docx, tmp_path):
        """A caller checking whether its replacement landed should not have to
        know whether a missing key means "absent" or "not attempted"."""
        result = write.replace_text(
            simple_docx, {"{{ absent }}": "x"}, output=tmp_path / "out.docx"
        )
        assert result.replacements == {"{{ absent }}": 0}
        assert result.locations == []

    def test_case_insensitive_replacement(self, simple_docx, tmp_path):
        result = write.replace_text(
            simple_docx, {"alpha": "ALPHA"}, output=tmp_path / "out.docx", match_case=False
        )
        assert result.replacements["alpha"] == 1

    def test_case_sensitive_by_default(self, simple_docx, tmp_path):
        result = write.replace_text(simple_docx, {"ALPHA": "x"}, output=tmp_path / "out.docx")
        assert result.replacements["ALPHA"] == 0

    def test_formatting_is_inherited_from_the_first_spanned_run(self, split_runs_docx, tmp_path):
        out = write.replace_text(
            split_runs_docx, {"{{ amount }}": "£40"}, output=tmp_path / "out.docx"
        ).output
        paragraph = next(
            p for p in read.get_text(out, runs_wanted=True) if p.text.startswith("Total")
        )
        receiving = next(r for r in paragraph.runs if "£40" in r.text)
        assert receiving.bold is False  # the first spanned run was the plain one

    def test_replacing_in_place(self, split_runs_docx, tmp_path):
        copy = tmp_path / "copy.docx"
        copy.write_bytes(split_runs_docx.read_bytes())
        result = write.replace_text(copy, {"{{ client.name }}": "Ada"})
        assert result.output == copy
        assert "Dear Ada, welcome." in [p.text for p in read.get_text(copy)]

    def test_the_input_is_untouched_when_an_output_is_given(self, split_runs_docx, tmp_path):
        before = split_runs_docx.read_bytes()
        write.replace_text(
            split_runs_docx, {"{{ client.name }}": "Ada"}, output=tmp_path / "out.docx"
        )
        assert split_runs_docx.read_bytes() == before


class TestProperties:
    def test_setting_a_property(self, simple_docx, tmp_path):
        out = write.set_properties(
            simple_docx, CoreProperties(title="New Title"), output=tmp_path / "out.docx"
        )
        assert read.get_properties(out).title == "New Title"

    def test_none_means_leave_alone_not_clear(self, rich_docx, tmp_path):
        """Clearing an author because the caller only wanted the title would be a
        surprise no flag asked for."""
        out = write.set_properties(
            rich_docx, CoreProperties(title="Changed"), output=tmp_path / "out.docx"
        )
        assert read.get_properties(out).author == "Test Author"


class TestRevisions:
    def test_accepting_promotes_insertions_and_drops_deletions(
        self, tracked_changes_docx, tmp_path
    ):
        out = write.accept_changes(tracked_changes_docx, output=tmp_path / "out.docx")
        assert read.get_tracked_changes(out) == []
        text = " ".join(p.text for p in read.get_text(out))
        assert "inserted words" in text
        assert "removed words" not in text

    def test_rejecting_drops_insertions_and_restores_deletions(
        self, tracked_changes_docx, tmp_path
    ):
        out = write.reject_changes(tracked_changes_docx, output=tmp_path / "out.docx")
        assert read.get_tracked_changes(out) == []
        text = " ".join(p.text for p in read.get_text(out))
        assert "inserted words" not in text
        assert "removed words" in text

    def test_restored_deletions_become_visible_text(self, tracked_changes_docx, tmp_path):
        """Text left as w:delText outside a w:del is invisible in Word — which
        looks exactly like the deletion having been accepted instead."""
        out = write.reject_changes(tracked_changes_docx, output=tmp_path / "out.docx")
        root = ooxml.parse_part(out, ooxml.DOCUMENT_PART)
        assert not ooxml.xpath(root, ".//w:delText")

    def test_no_revision_markup_remains(self, tracked_changes_docx, tmp_path):
        out = write.accept_changes(tracked_changes_docx, output=tmp_path / "out.docx")
        root = ooxml.parse_part(out, ooxml.DOCUMENT_PART)
        assert not ooxml.xpath(root, ".//w:ins | .//w:del")

    def test_an_author_filter_leaves_everyone_else_tracked(self, tracked_changes_docx, tmp_path):
        out = write.accept_changes(
            tracked_changes_docx, output=tmp_path / "out.docx", authors=["Grace Hopper"]
        )
        remaining = read.get_tracked_changes(out)
        assert {c.author for c in remaining} == {"Ada Lovelace"}

    def test_accepting_a_document_with_no_changes_is_a_copy(self, simple_docx, tmp_path):
        out = write.accept_changes(simple_docx, output=tmp_path / "out.docx")
        assert out.is_file()
        assert [p.text for p in read.get_text(out)] == [p.text for p in read.get_text(simple_docx)]

    def test_revisions_can_be_resolved_in_place(self, tracked_changes_docx, tmp_path):
        copy = tmp_path / "copy.docx"
        copy.write_bytes(tracked_changes_docx.read_bytes())
        write.accept_changes(copy)
        assert read.get_tracked_changes(copy) == []


class TestRevisableParts:
    def test_every_part_that_can_hold_text_is_listed(self, split_runs_docx):
        labels = dict(write.revisable_parts(split_runs_docx))
        assert labels[ooxml.DOCUMENT_PART] == "body"
        assert "header:1" in labels.values()
        assert "footer:1" in labels.values()

    def test_a_document_with_no_header_lists_only_the_body(self, simple_docx):
        assert [label for _, label in write.revisable_parts(simple_docx)] == ["body"]
