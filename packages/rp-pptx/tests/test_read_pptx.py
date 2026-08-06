"""Reading decks: index, text, tables, images, notes, charts, comments, markdown.

The recurring theme is that indices count across the deck rather than across the
selection, and that a reader must not invent or lose information: a merged cell
reports its span, an unreadable chart reports what it can, and comments that
cannot be read raise rather than coming back empty.
"""

from __future__ import annotations

import pytest

from rp_core.errors import InputError
from rp_pptx.errors import UnsupportedFeatureError
from rp_pptx.pptx import read


class TestIndex:
    def test_it_counts_everything_on_the_deck(self, rich_deck):
        index = read.get_index(rich_deck)
        assert index.slide_count == 4
        assert index.table_count == 1
        assert index.image_count == 1
        assert index.chart_count == 1
        assert index.notes_count == 1

    def test_it_reports_geometry_and_layouts(self, rich_deck):
        index = read.get_index(rich_deck)
        assert index.aspect_ratio == "4:3"
        assert index.master_count == 1
        assert "Title Slide" in index.layout_names

    def test_titles_carry_their_layout(self, rich_deck):
        index = read.get_index(rich_deck)
        assert index.titles[0].index == 1
        assert index.titles[0].title == "Outline"
        assert index.titles[2].title is None, "a blank-layout slide has no title"

    def test_it_stays_total_on_a_deck_it_cannot_fully_read(self, modern_comments_deck):
        """Section 7: an index must never refuse a readable deck."""
        assert read.get_index(modern_comments_deck).slide_count == 3

    def test_a_deck_with_no_comments_reports_zero_not_null(self, simple_deck):
        assert read.get_index(simple_deck).comment_count == 0


class TestText:
    def test_it_returns_paragraphs_per_slide(self, rich_deck):
        first = read.get_text(rich_deck, slides="1")[0]
        assert first.title == "Outline"
        assert [(p.level, p.text) for p in first.paragraphs if p.text] == [
            (0, "Outline"),
            (0, "top level"),
            (1, "nested once"),
            (2, "nested twice"),
            (0, "back to top"),
        ]

    def test_runs_are_omitted_unless_asked_for(self, rich_deck):
        assert all(p.runs is None for p in read.get_text(rich_deck, slides="1")[0].paragraphs)

    def test_runs_carry_formatting_when_asked_for(self, runs_deck):
        slide = read.get_text(runs_deck, slides="1", runs=True)[0]
        runs = [run for para in slide.paragraphs if para.runs for run in para.runs]
        assert any(run.bold for run in runs)

    def test_table_text_belongs_to_get_tables_not_here(self, rich_deck):
        """Reporting cells in both places doubles every cell in get_markdown."""
        slide = read.get_text(rich_deck, slides="2")[0]
        assert not any("r2c1" in (p.text or "") for p in slide.paragraphs)

    def test_it_reaches_into_groups(self, rich_deck):
        slide = read.get_text(rich_deck, slides="3")[0]
        assert any(p.text == "text inside a group" for p in slide.paragraphs)

    def test_an_empty_placeholder_contributes_no_prompt_text(self, simple_deck):
        """Section 9: "Click to add title" lives in the layout, not the slide."""
        for slide in read.get_text(simple_deck):
            assert not any("Click to add" in (p.text or "") for p in slide.paragraphs)


class TestSelectors:
    def test_a_bad_spec_is_an_input_error_not_a_corrupt_file(self, simple_deck):
        with pytest.raises(InputError):
            read.get_text(simple_deck, slides="99")

    @pytest.mark.parametrize("spec,expected", [("1", [1]), ("2-3", [2, 3]), ("1,3", [1, 3])])
    def test_specs_select_what_they_say(self, simple_deck, spec, expected):
        assert [s.index for s in read.get_text(simple_deck, slides=spec)] == expected

    def test_tables_filter_by_slide(self, rich_deck):
        assert read.get_tables(rich_deck, slides="1") == []
        assert len(read.get_tables(rich_deck, slides="2")) == 1

    def test_comments_filter_by_slide(self, classic_comments_deck):
        assert [c.slide_index for c in read.get_comments(classic_comments_deck, slides="3")] == [3]

    def test_indices_count_across_the_deck_not_the_selection(self, rich_deck):
        """An index that renumbers when you filter is not an index."""
        whole = read.get_images(rich_deck)
        filtered = read.get_images(rich_deck, slides="3")
        assert [i.index for i in filtered] == [i.index for i in whole if i.slide_index == 3]


class TestTables:
    def test_a_merge_origin_carries_the_value_and_spanned_cells_are_empty(self, rich_deck):
        table = read.get_tables(rich_deck)[0]
        assert table.data[0] == ["origin", "", "c3"]

    def test_merges_are_reported(self, rich_deck):
        table = read.get_tables(rich_deck)[0]
        assert [(m.row, m.col, m.row_span, m.col_span) for m in table.merges] == [(1, 1, 1, 2)]

    def test_dimensions_are_the_grid_not_the_visible_cells(self, rich_deck):
        table = read.get_tables(rich_deck)[0]
        assert (table.rows, table.cols) == (3, 3)

    def test_the_index_filter_selects_one_table(self, rich_deck):
        assert len(read.get_tables(rich_deck, table_index=1)) == 1
        assert read.get_tables(rich_deck, table_index=99) == []


class TestImages:
    def test_alt_text_is_the_descr_not_the_shape_name(self, rich_deck):
        image = read.get_images(rich_deck)[0]
        assert image.alt_text == "A red rectangle"

    def test_dimensions_are_read_from_the_bytes(self, rich_deck):
        image = read.get_images(rich_deck)[0]
        assert (image.width_px, image.height_px) == (48, 32)

    def test_it_reports_the_relationship_id(self, rich_deck):
        assert read.get_images(rich_deck)[0].rel_id.startswith("rId")

    def test_extraction_writes_the_bytes(self, rich_deck, tmp_path):
        images = read.get_images(rich_deck, output_dir=tmp_path / "out")
        assert images[0].extracted_path.is_file()
        assert images[0].extracted_path.read_bytes()[:4] == b"\x89PNG"

    def test_nothing_is_extracted_without_an_output_dir(self, rich_deck):
        assert read.get_images(rich_deck)[0].extracted_path is None


class TestNotes:
    def test_only_slides_with_notes_are_reported(self, rich_deck):
        notes = read.get_notes(rich_deck)
        assert [n.slide_index for n in notes] == [1]
        assert notes[0].text == "Speaker notes for the outline slide"

    def test_reading_notes_does_not_add_notes_parts(self, simple_deck):
        """``notes_slide`` *creates* the part on access; ``has_notes_slide``
        is what keeps a read from quietly growing the package."""
        from rp_pptx import ooxml

        before = [n for n in ooxml.part_names(simple_deck) if "notesSlide" in n]
        read.get_notes(simple_deck)
        after = [n for n in ooxml.part_names(simple_deck) if "notesSlide" in n]
        assert before == after


class TestCharts:
    def test_categories_and_series_are_read(self, rich_deck):
        chart = read.get_charts(rich_deck)[0]
        assert chart.categories == ["East", "West"]
        assert chart.series[0].name == "Revenue"
        assert chart.series[0].values == [11.0, 22.0]
        assert chart.data_available is True

    def test_the_title_is_read(self, rich_deck):
        assert read.get_charts(rich_deck)[0].title == "Revenue by region"

    def test_the_type_is_reported(self, rich_deck):
        assert "COLUMN_CLUSTERED" in read.get_charts(rich_deck)[0].chart_type


class TestComments:
    def test_classic_comments_are_read_with_their_authors(self, classic_comments_deck):
        comments = read.get_comments(classic_comments_deck)
        assert [(c.author, c.text) for c in comments] == [
            ("Ada Lovelace", "First thought"),
            ("Grace Hopper", "Second"),
            ("Ada Lovelace", "On the third slide"),
        ]

    def test_initials_and_dates_are_read(self, classic_comments_deck):
        first = read.get_comments(classic_comments_deck)[0]
        assert first.initials == "AL"
        assert first.date.year == 2026

    def test_classic_comments_never_thread(self, classic_comments_deck):
        """Section 7 normalizes both generations onto one model; parent_id is
        None throughout for classic comments, which have no threading."""
        assert all(c.parent_id is None for c in read.get_comments(classic_comments_deck))

    def test_the_count_is_reported_in_the_index(self, classic_comments_deck):
        assert read.get_index(classic_comments_deck).comment_count == 3


class TestModernCommentDeferral:
    """Section 7's deferral path. The error *is* the interface here, so the
    envelope is what gets asserted."""

    def test_it_raises_rather_than_returning_empty(self, modern_comments_deck):
        with pytest.raises(UnsupportedFeatureError):
            read.get_comments(modern_comments_deck)

    def test_the_envelope_names_the_affected_slides_and_exits_three(self, modern_comments_deck):
        with pytest.raises(UnsupportedFeatureError) as error:
            read.get_comments(modern_comments_deck)
        envelope = error.value.to_envelope()
        assert envelope.error.exit_code == 3
        assert "slide(s) 2" in envelope.error.message
        assert "deferred" in (envelope.error.hint or "")

    def test_the_index_reports_null_rather_than_a_wrong_count(self, modern_comments_deck):
        assert read.get_index(modern_comments_deck).comment_count is None

    def test_a_mixed_deck_raises_too(self, mixed_comments_deck):
        """Partial results are sacrificed for an error that cannot be mistaken
        for a complete read."""
        with pytest.raises(UnsupportedFeatureError):
            read.get_comments(mixed_comments_deck)

    def test_a_mixed_deck_reports_null_too(self, mixed_comments_deck):
        assert read.get_index(mixed_comments_deck).comment_count is None

    def test_classic_only_decks_are_unaffected(self, classic_comments_deck):
        assert len(read.get_comments(classic_comments_deck)) == 3


class TestMarkdown:
    def test_slides_are_separated_by_a_thematic_break(self, simple_deck):
        assert read.get_markdown(simple_deck).count("\n---\n") == 2

    def test_titles_become_second_level_headings(self, simple_deck):
        assert "## Alpha" in read.get_markdown(simple_deck)

    def test_nesting_becomes_indentation(self, rich_deck):
        body = read.get_markdown(rich_deck, slides="1")
        assert "- top level" in body
        assert "  - nested once" in body
        assert "    - nested twice" in body

    def test_notes_become_html_comments(self, rich_deck):
        """The dialect create() reads back, not a decorative prefix."""
        assert "<!-- Speaker notes for the outline slide -->" in read.get_markdown(rich_deck)

    def test_notes_can_be_suppressed(self, rich_deck):
        assert "<!--" not in read.get_markdown(rich_deck, notes=False)

    def test_tables_become_pipe_tables(self, rich_deck):
        body = read.get_markdown(rich_deck, slides="2")
        assert "| origin |  | c3 |" in body
        assert "|---|---|---|" in body

    def test_images_are_linked_when_extracted(self, rich_deck, tmp_path):
        body = read.get_markdown(rich_deck, slides="3", images_dir=tmp_path / "img")
        assert "![A red rectangle](" in body
        assert (tmp_path / "img").is_dir()

    def test_a_deck_round_trips_back_through_create(self, rich_deck, tmp_path):
        """The point of matching dialects: markdown out, deck back in."""
        from rp_pptx.pptx import write

        body = read.get_markdown(rich_deck, slides="1")
        write.create(tmp_path / "again.pptx", markdown=body)
        again = read.get_text(tmp_path / "again.pptx")
        assert again[0].title == "Outline"
        assert [(p.level, p.text) for p in again[0].paragraphs if p.text] == [
            (0, "Outline"),
            (0, "top level"),
            (1, "nested once"),
            (2, "nested twice"),
            (0, "back to top"),
        ]
        assert read.get_notes(tmp_path / "again.pptx")[0].text == (
            "Speaker notes for the outline slide"
        )


class TestProperties:
    def test_properties_are_read(self, tmp_path):
        from rp_pptx.models import CoreProperties
        from rp_pptx.pptx import write

        source = tmp_path / "p.pptx"
        write.create(source, markdown="# T\n")
        write.set_properties(
            source, CoreProperties(title="A title", author="Ada"), output=tmp_path / "q.pptx"
        )
        props = read.get_properties(tmp_path / "q.pptx")
        assert (props.title, props.author) == ("A title", "Ada")

    def test_none_means_leave_alone_not_clear(self, tmp_path):
        from rp_pptx.models import CoreProperties
        from rp_pptx.pptx import write

        source = tmp_path / "p.pptx"
        write.create(source, markdown="# T\n")
        write.set_properties(source, CoreProperties(author="Ada"), output=tmp_path / "q.pptx")
        write.set_properties(
            tmp_path / "q.pptx", CoreProperties(title="Later"), output=tmp_path / "r.pptx"
        )
        props = read.get_properties(tmp_path / "r.pptx")
        assert props.author == "Ada"
        assert props.title == "Later"
