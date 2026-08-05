"""Reading documents: index, text, tables, images, comments, tracked changes."""

from __future__ import annotations

import pytest

from rp_docx import ooxml
from rp_docx.docx import read
from rp_docx.errors import InvalidDocxError, MissingFileError


class TestProperties:
    def test_core_properties_are_read(self, rich_docx):
        props = read.get_properties(rich_docx)
        assert props.title == "Quarterly Report"
        assert props.author == "Test Author"
        assert props.category == "reports"
        assert props.keywords == "quarterly, revenue"

    def test_unset_properties_are_none_not_empty_strings(self, simple_docx):
        """JSON consumers branch on null; "" is a value that happens to be blank."""
        assert read.get_properties(simple_docx).category is None

    def test_a_missing_file_is_an_input_error(self, tmp_path):
        with pytest.raises(MissingFileError):
            read.get_properties(tmp_path / "nope.docx")

    def test_a_non_document_is_a_corrupt_file_error(self, not_a_docx):
        with pytest.raises(InvalidDocxError):
            read.get_properties(not_a_docx)


class TestIndex:
    def test_the_index_counts_everything(self, rich_docx):
        index = read.get_index(rich_docx)
        assert index.paragraph_count > 0
        assert index.word_count > 0
        assert index.section_count == 2
        assert index.table_count == 3  # two top level, one nested
        assert index.image_count == 1
        assert index.has_headers_footers is True

    def test_headings_carry_level_and_position(self, rich_docx):
        headings = read.get_index(rich_docx).headings
        assert [(h.level, h.text) for h in headings] == [
            (1, "Quarterly Report"),
            (2, "Regional detail"),
            (3, "Notes"),
            (2, "Appendix"),
        ]
        assert all(h.index >= 1 for h in headings)

    def test_heading_indices_point_at_the_right_paragraph(self, rich_docx):
        paragraphs = {p.index: p.text for p in read.get_text(rich_docx)}
        for heading in read.get_index(rich_docx).headings:
            assert paragraphs[heading.index] == heading.text

    def test_styles_used_lists_only_what_is_used(self, simple_docx):
        assert read.get_index(simple_docx).styles_used == ["Heading 1", "Heading 2", "Normal"]

    def test_an_empty_document_indexes_cleanly(self, empty_docx):
        index = read.get_index(empty_docx)
        assert index.paragraph_count == 0
        assert index.headings == []
        assert index.has_headers_footers is False

    def test_the_index_reports_comments_and_changes(self, comments_docx, tracked_changes_docx):
        assert read.get_index(comments_docx).comment_count == 2
        assert read.get_index(tracked_changes_docx).tracked_change_count == 3

    def test_a_dotx_can_be_indexed(self, house_like_template):
        """The .dotx path all the way through: python-docx would refuse this."""
        assert read.get_index(house_like_template).paragraph_count >= 1


class TestText:
    def test_paragraphs_are_numbered_from_one(self, simple_docx):
        paragraphs = read.get_text(simple_docx)
        assert [p.index for p in paragraphs] == [1, 2, 3, 4]
        assert paragraphs[0].text == "Title"

    def test_runs_are_omitted_unless_asked_for(self, rich_docx):
        assert all(p.runs is None for p in read.get_text(rich_docx))

    def test_runs_carry_formatting(self, rich_docx):
        paragraphs = read.get_text(rich_docx, runs_wanted=True)
        body = next(p for p in paragraphs if p.text.startswith("Revenue rose"))
        bold = [r for r in body.runs if r.bold]
        italic = [r for r in body.runs if r.italic]
        assert [r.text for r in bold] == ["sharply"]
        assert [r.text for r in italic] == ["quarter"]
        assert bold[0].size_pt == 14

    def test_a_style_filter_does_not_renumber_what_is_left(self, simple_docx):
        """A filtered result still says where each paragraph is in the document."""
        headings = read.get_text(simple_docx, style_filter="Heading 1")
        assert [(p.index, p.text) for p in headings] == [(1, "Title")]

    def test_a_style_filter_matching_nothing_returns_an_empty_list(self, simple_docx):
        assert read.get_text(simple_docx, style_filter="Nonexistent") == []

    def test_a_style_driven_list_reports_its_level(self, rich_docx):
        """python-docx's add_paragraph(style="List Bullet") attaches numbering to
        the style, not the paragraph — reading only the paragraph's own w:numPr
        reports every such list as not a list."""
        bullets = [p for p in read.get_text(rich_docx) if p.style == "List Bullet"]
        assert bullets and all(p.list_level == 1 for p in bullets)

    def test_a_plain_paragraph_has_no_list_level(self, simple_docx):
        assert all(p.list_level is None for p in read.get_text(simple_docx))


class TestMarkdown:
    def test_headings_and_body_convert(self, simple_docx):
        markdown = read.get_markdown(simple_docx)
        assert "# Title" in markdown
        # mammoth escapes Markdown punctuation, so the period arrives as "\.".
        assert "Alpha beta gamma" in markdown
        assert "## Section" in markdown

    def test_images_are_dropped_by_default(self, rich_docx):
        """A Markdown file referencing images that were never written is worse
        than one with none."""
        assert "data:image" not in read.get_markdown(rich_docx)

    def test_images_can_be_embedded(self, rich_docx):
        assert "data:image/png;base64," in read.get_markdown(rich_docx, embed_images=True)

    def test_a_dotx_converts(self, house_like_template):
        """mammoth reads the package itself, and rejects the template content
        type just as python-docx does."""
        assert isinstance(read.get_markdown(house_like_template), str)

    def test_a_non_document_is_a_corrupt_file_error(self, not_a_docx):
        with pytest.raises(InvalidDocxError):
            read.get_markdown(not_a_docx)


class TestTables:
    def test_tables_are_read_row_major(self, rich_docx, table_data):
        tables = read.get_tables(rich_docx)
        assert tables[0].data == table_data
        assert (tables[0].rows, tables[0].cols) == (3, 3)

    def test_nested_tables_are_found(self, rich_docx):
        """python-docx's document.tables is top level only, so a table inside a
        cell is invisible to it — and that is where a caller tends to find
        nothing."""
        assert [t.index for t in read.get_tables(rich_docx)] == [1, 2, 3]
        assert any(t.data == [["nested", "cell"]] for t in read.get_tables(rich_docx))

    def test_a_table_index_selects_one(self, rich_docx):
        selected = read.get_tables(rich_docx, table_index=1)
        assert len(selected) == 1 and selected[0].index == 1

    def test_an_out_of_range_index_returns_nothing(self, rich_docx):
        assert read.get_tables(rich_docx, table_index=99) == []

    def test_section_context_names_the_nearest_preceding_heading(self, rich_docx):
        assert read.get_tables(rich_docx)[0].section_context == "Notes"

    def test_the_table_style_is_reported(self, rich_docx):
        assert read.get_tables(rich_docx)[0].style == "Table Grid"

    def test_a_document_with_no_tables(self, simple_docx):
        assert read.get_tables(simple_docx) == []


class TestImages:
    def test_images_are_reported_without_extracting(self, rich_docx):
        """A caller asking what a document contains should not have to extract
        it to find out."""
        images = read.get_images(rich_docx)
        assert len(images) == 1
        assert images[0].extracted_path is None
        assert images[0].content_type == "image/png"

    def test_dimensions_are_read(self, rich_docx, image_size):
        assert (
            read.get_images(rich_docx)[0].width_px,
            read.get_images(rich_docx)[0].height_px,
        ) == (image_size)

    def test_alt_text_is_read(self, rich_docx):
        assert read.get_images(rich_docx)[0].alt_text == "Company logo"

    def test_images_are_written_when_a_directory_is_given(self, rich_docx, tmp_path):
        images = read.get_images(rich_docx, output_dir=tmp_path / "out")
        assert images[0].extracted_path.is_file()
        assert images[0].extracted_path.stat().st_size > 0

    def test_a_document_with_no_images(self, simple_docx):
        assert read.get_images(simple_docx) == []


class TestComments:
    def test_comments_are_read_with_authors(self, comments_docx):
        comments = read.get_comments(comments_docx)
        assert [(c.id, c.author, c.initials) for c in comments] == [
            ("0", "Ada Lovelace", "AL"),
            ("1", "Grace Hopper", "GH"),
        ]

    def test_comment_text_is_read(self, comments_docx):
        assert read.get_comments(comments_docx)[0].text == "Please clarify this."

    def test_comment_dates_are_parsed(self, comments_docx):
        assert read.get_comments(comments_docx)[0].date.year == 2024

    def test_anchor_text_is_the_range_the_comment_covers(self, comments_docx):
        assert read.get_comments(comments_docx)[0].anchor_text == "Anchored sentence."

    def test_resolved_state_comes_from_commentsextended(self, comments_docx):
        resolved = {c.id: c.resolved for c in read.get_comments(comments_docx)}
        assert resolved == {"0": False, "1": True}

    def test_a_document_with_no_comments_part_returns_an_empty_list(self, simple_docx):
        """The part is optional; its absence means "no comments", not "cannot
        tell"."""
        assert read.get_comments(simple_docx) == []

    def test_a_missing_commentsextended_part_means_nothing_resolved(self, comments_docx, tmp_path):
        stripped = tmp_path / "no_ext.docx"
        import zipfile

        with (
            zipfile.ZipFile(comments_docx) as source,
            zipfile.ZipFile(stripped, "w") as target,
        ):
            for item in source.infolist():
                if item.filename != ooxml.COMMENTS_EXTENDED_PART:
                    target.writestr(item, source.read(item.filename))
        assert all(not c.resolved for c in read.get_comments(stripped))


class TestTrackedChanges:
    def test_insertions_and_deletions_are_read(self, tracked_changes_docx):
        changes = read.get_tracked_changes(tracked_changes_docx)
        by_type = {c.type: c for c in changes if c.type != "format"}
        assert by_type["insertion"].text == "inserted words "
        assert by_type["insertion"].author == "Ada Lovelace"
        assert by_type["deletion"].author == "Grace Hopper"

    def test_deleted_text_comes_from_deltext_not_t(self, tracked_changes_docx):
        """A reader that looks only for w:t reports every deletion as empty —
        and looks like it works."""
        deletion = next(
            c for c in read.get_tracked_changes(tracked_changes_docx) if c.type == "deletion"
        )
        assert deletion.text == "removed words "

    def test_a_paragraph_mark_insertion_is_a_format_change(self, tracked_changes_docx):
        """A w:ins inside run properties records that the paragraph mark itself
        was inserted — Word shows it as a formatting change, not as new text."""
        changes = read.get_tracked_changes(tracked_changes_docx)
        assert [c.type for c in changes].count("format") == 1

    def test_changes_carry_their_paragraph_index(self, tracked_changes_docx):
        changes = read.get_tracked_changes(tracked_changes_docx)
        assert {c.paragraph_index for c in changes} == {1, 2}

    def test_dates_are_parsed(self, tracked_changes_docx):
        changes = read.get_tracked_changes(tracked_changes_docx)
        assert all(c.date is not None for c in changes)

    def test_a_clean_document_has_no_changes(self, simple_docx):
        assert read.get_tracked_changes(simple_docx) == []
