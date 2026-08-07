"""Slide deletion and reordering — ``p:sldIdLst`` surgery (spec section 7).

Deck order is the order of ``p:sldId`` elements, so both operations are element
moves rather than content edits. The integrity assertions matter more than usual
here: a deck that reads back with the right *count* can still be structurally
broken, so each test reopens the result and checks the surviving parts agree with
the id list.
"""

from __future__ import annotations

import pytest

from rp_core.errors import InputError
from rp_pptx import ooxml
from rp_pptx.pptx import read
from rp_pptx.pptx.slides import delete_slides, reorder_slides


def titles(path):
    return [title.title for title in read.get_index(path).titles]


def sldidlst_matches_parts(path) -> bool:
    """Every ``p:sldId`` resolves to a slide part that is really in the package.

    The check that catches a half-done deletion: dropping the relationship but
    leaving the id, or the reverse, both still open in python-pptx.
    """
    presentation = ooxml.parse_part(path, ooxml.PRESENTATION_PART)
    rels = ooxml.parse_part(path, ooxml.rels_path(ooxml.PRESENTATION_PART))
    targets = {r.get("Id"): r.get("Target") for r in rels}
    parts = set(ooxml.part_names(path))
    for entry in ooxml.xpath(presentation, "./p:sldIdLst/p:sldId"):
        rel_id = ooxml.attr(entry, "r:id")
        if rel_id not in targets:
            return False
        if f"ppt/{targets[rel_id]}" not in parts:
            return False
    return True


class TestDelete:
    def test_it_removes_the_named_slide(self, simple_deck, tmp_path):
        result = delete_slides(simple_deck, "2", output=tmp_path / "o.pptx")
        assert result.slide_count == 2
        assert titles(tmp_path / "o.pptx") == ["Alpha", "Gamma"]

    def test_it_removes_several(self, simple_deck, tmp_path):
        delete_slides(simple_deck, "1,3", output=tmp_path / "o.pptx")
        assert titles(tmp_path / "o.pptx") == ["Beta"]

    def test_a_range_works(self, simple_deck, tmp_path):
        delete_slides(simple_deck, "2-3", output=tmp_path / "o.pptx")
        assert titles(tmp_path / "o.pptx") == ["Alpha"]

    def test_deleting_every_slide_is_refused(self, simple_deck, tmp_path):
        """Section 7: an empty deck is a corner nothing downstream is tested
        against, and "delete all" is likelier a range-spec mistake than intent."""
        with pytest.raises(InputError, match="every slide"):
            delete_slides(simple_deck, "all", output=tmp_path / "o.pptx")

    def test_deleting_all_but_one_succeeds(self, simple_deck, tmp_path):
        result = delete_slides(simple_deck, "1-2", output=tmp_path / "o.pptx")
        assert result.slide_count == 1

    def test_the_result_reopens_cleanly(self, simple_deck, tmp_path):
        delete_slides(simple_deck, "2", output=tmp_path / "o.pptx")
        with ooxml.opened(tmp_path / "o.pptx") as presentation:
            assert len(presentation.slides) == 2

    def test_the_id_list_matches_the_surviving_parts(self, simple_deck, tmp_path):
        delete_slides(simple_deck, "2", output=tmp_path / "o.pptx")
        assert sldidlst_matches_parts(tmp_path / "o.pptx")

    def test_a_bad_spec_is_an_input_error(self, simple_deck, tmp_path):
        with pytest.raises(InputError):
            delete_slides(simple_deck, "99", output=tmp_path / "o.pptx")

    def test_it_requires_an_output(self, simple_deck):
        with pytest.raises(InputError):
            delete_slides(simple_deck, "2")


class TestReorder:
    def test_it_reorders(self, simple_deck, tmp_path):
        reorder_slides(simple_deck, [3, 1, 2], output=tmp_path / "o.pptx")
        assert titles(tmp_path / "o.pptx") == ["Gamma", "Alpha", "Beta"]

    def test_the_identity_permutation_is_a_no_op(self, simple_deck, tmp_path):
        reorder_slides(simple_deck, [1, 2, 3], output=tmp_path / "o.pptx")
        assert titles(tmp_path / "o.pptx") == ["Alpha", "Beta", "Gamma"]

    def test_content_travels_with_the_slide(self, rich_deck, tmp_path):
        """Reordering must move slides, not retitle them."""
        before = read.get_text(rich_deck, slides="1")[0]
        reorder_slides(rich_deck, [2, 1, 3, 4], output=tmp_path / "o.pptx")
        after = read.get_text(tmp_path / "o.pptx", slides="2")[0]
        assert [p.text for p in after.paragraphs] == [p.text for p in before.paragraphs]

    def test_notes_travel_with_the_slide(self, rich_deck, tmp_path):
        reorder_slides(rich_deck, [2, 1, 3, 4], output=tmp_path / "o.pptx")
        notes = read.get_notes(tmp_path / "o.pptx")
        assert [n.slide_index for n in notes] == [2]

    def test_an_incomplete_permutation_names_what_is_missing(self, simple_deck, tmp_path):
        """Section 4: a partial spec silently guessing where unlisted slides go
        is exactly the surprise section 10 exists to prevent."""
        with pytest.raises(InputError) as error:
            reorder_slides(simple_deck, [1, 2], output=tmp_path / "o.pptx")
        assert "3" in str(error.value)

    def test_a_duplicated_index_names_the_duplicate(self, simple_deck, tmp_path):
        with pytest.raises(InputError) as error:
            reorder_slides(simple_deck, [1, 1, 2], output=tmp_path / "o.pptx")
        assert "1" in str(error.value)

    def test_an_out_of_range_index_is_rejected(self, simple_deck, tmp_path):
        with pytest.raises(InputError):
            reorder_slides(simple_deck, [1, 2, 5], output=tmp_path / "o.pptx")

    def test_the_result_reopens_cleanly(self, simple_deck, tmp_path):
        reorder_slides(simple_deck, [3, 2, 1], output=tmp_path / "o.pptx")
        with ooxml.opened(tmp_path / "o.pptx") as presentation:
            assert len(presentation.slides) == 3

    def test_the_id_list_matches_the_parts(self, simple_deck, tmp_path):
        reorder_slides(simple_deck, [3, 2, 1], output=tmp_path / "o.pptx")
        assert sldidlst_matches_parts(tmp_path / "o.pptx")

    def test_it_requires_an_output(self, simple_deck):
        with pytest.raises(InputError):
            reorder_slides(simple_deck, [1, 2, 3])
