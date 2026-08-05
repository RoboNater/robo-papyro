"""The run-spanning problem (spec section 6) — the package's highest-risk code.

Unit tests against hand-built paragraphs, so a failure here points at the
algorithm rather than at anything that uses it. The four cases spec section 6
requires are all present: a placeholder split across three runs, a match
spanning a formatting boundary, a match inside a table cell, and overlapping
candidate matches.
"""

from __future__ import annotations

from lxml import etree

from rp_docx.docx import runs
from rp_docx.ooxml import NS, qn

W = NS["w"]


def paragraph(*pieces: str, bold_from: int | None = None) -> etree._Element:
    """A ``w:p`` whose text is split across one run per piece.

    ``bold_from`` makes that run and everything after it bold, which is how a
    formatting boundary lands mid-word in a real document.
    """
    root = etree.Element(qn("w:p"), nsmap={"w": W})
    for index, piece in enumerate(pieces):
        run = etree.SubElement(root, qn("w:r"))
        if bold_from is not None and index >= bold_from:
            properties = etree.SubElement(run, qn("w:rPr"))
            etree.SubElement(properties, qn("w:b"))
        text = etree.SubElement(run, qn("w:t"))
        text.text = piece
    return root


def text_of(element) -> str:
    return "".join(node.text or "" for node in element.iter(qn("w:t")))


class TestOffsetMapping:
    def test_spans_cover_the_concatenated_text(self):
        element = paragraph("Dear {{ ", "clie", "nt.na", "me }},")
        spans = runs.text_spans(element)
        assert [(s.start, s.end) for s in spans] == [(0, 8), (8, 12), (12, 17), (17, 23)]
        assert runs.paragraph_text(element) == "Dear {{ client.name }},"

    def test_an_empty_paragraph_has_no_spans(self):
        element = etree.Element(qn("w:p"), nsmap={"w": W})
        assert runs.text_spans(element) == []
        assert runs.paragraph_text(element) == ""

    def test_deleted_text_is_not_part_of_the_paragraph(self):
        """Tracked deletions hold their text in w:delText. Replacing inside one
        would resurrect text the author removed."""
        element = paragraph("Kept ")
        deletion = etree.SubElement(element, qn("w:del"))
        run = etree.SubElement(deletion, qn("w:r"))
        etree.SubElement(run, qn("w:delText")).text = "removed"
        assert runs.paragraph_text(element) == "Kept "

    def test_a_nested_paragraph_is_not_this_paragraph(self):
        """A text box is a w:p living inside a run of the outer paragraph. Its
        text belongs to it, and it is visited separately."""
        element = paragraph("Outer ")
        box = etree.SubElement(element.find(qn("w:r")), qn("w:txbxContent"))
        inner = etree.SubElement(box, qn("w:p"))
        inner_run = etree.SubElement(inner, qn("w:r"))
        etree.SubElement(inner_run, qn("w:t")).text = "inner"
        assert runs.paragraph_text(element) == "Outer "
        assert runs.paragraph_text(inner) == "inner"


class TestMatching:
    def test_a_simple_match(self):
        found = runs.find_matches("Hello world", {"world": "there"})
        assert [(m.start, m.end, m.replacement) for m in found] == [(6, 11, "there")]

    def test_overlapping_candidates_resolve_to_the_longer(self):
        """Spec section 6's fourth required case. Picking arbitrarily would make
        the result depend on dict ordering, which no caller can see."""
        found = runs.find_matches("xabcy", {"ab": "1", "abc": "2"})
        assert [(m.key, m.start, m.end) for m in found] == [("abc", 1, 4)]

    def test_the_longer_wins_whichever_order_the_keys_arrive_in(self):
        one = runs.find_matches("xabcy", {"abc": "2", "ab": "1"})
        two = runs.find_matches("xabcy", {"ab": "1", "abc": "2"})
        assert [m.key for m in one] == [m.key for m in two] == ["abc"]

    def test_a_shorter_key_still_matches_where_the_longer_does_not(self):
        found = runs.find_matches("ab abc", {"ab": "1", "abc": "2"})
        assert [(m.key, m.start) for m in found] == [("ab", 0), ("abc", 3)]

    def test_matches_are_non_overlapping(self):
        found = runs.find_matches("aaaa", {"aa": "b"})
        assert [(m.start, m.end) for m in found] == [(0, 2), (2, 4)]

    def test_ignore_case(self):
        assert runs.find_matches("Hello", {"hello": "x"}) == []
        assert len(runs.find_matches("Hello", {"hello": "x"}, ignore_case=True)) == 1

    def test_a_regex_metacharacter_in_a_key_is_a_literal(self):
        """Keys are literals, not patterns — `{{ a.b }}` must not match `{{ axb }}`."""
        assert runs.find_matches("{{ axb }}", {"{{ a.b }}": "v"}) == []
        assert len(runs.find_matches("{{ a.b }}", {"{{ a.b }}": "v"})) == 1

    def test_an_empty_key_is_ignored(self):
        assert runs.find_matches("text", {"": "x"}) == []


class TestReplacement:
    def test_a_placeholder_split_across_three_runs(self):
        """Spec section 6's first required case, and the one a naive
        run.text.replace() fails silently on."""
        element = paragraph("Dear {{ ", "clie", "nt.na", "me }},")
        counts = runs.replace_in_paragraph(element, {"{{ client.name }}": "Ada"})
        assert counts == {"{{ client.name }}": 1}
        assert text_of(element) == "Dear Ada,"

    def test_the_naive_approach_would_have_found_nothing(self):
        """States the premise, so the fixture cannot quietly stop being split."""
        element = paragraph("Dear {{ ", "clie", "nt.na", "me }},")
        assert not any("{{ client.name }}" in (n.text or "") for n in element.iter(qn("w:t")))

    def test_a_match_spanning_a_formatting_boundary(self):
        """Spec section 6's second required case. The replacement inherits the
        first spanned run's formatting — documented behavior, not an accident."""
        element = paragraph("Total: {{ amo", "unt }} due", bold_from=1)
        runs.replace_in_paragraph(element, {"{{ amount }}": "£40"})
        assert text_of(element) == "Total: £40 due"
        first_run = element.findall(qn("w:r"))[0]
        assert first_run.find(qn("w:rPr")) is None  # the plain run received it

    def test_preserve_formatting_false_strips_the_receiving_run(self):
        element = paragraph("Total: ", "{{ amount }}", " due", bold_from=1)
        runs.replace_in_paragraph(element, {"{{ amount }}": "£40"}, preserve_formatting=False)
        assert text_of(element) == "Total: £40 due"
        assert element.findall(qn("w:r"))[1].find(qn("w:rPr")) is None

    def test_the_tail_runs_are_blanked_not_removed(self):
        element = paragraph("a{{ k", " }}b")
        runs.replace_in_paragraph(element, {"{{ k }}": "V"})
        assert text_of(element) == "aVb"
        assert len(element.findall(qn("w:r"))) == 2

    def test_several_matches_in_one_paragraph(self):
        element = paragraph("{{ a }} and ", "{{ a }} and {{ b }}")
        counts = runs.replace_in_paragraph(element, {"{{ a }}": "1", "{{ b }}": "2"})
        assert counts == {"{{ a }}": 2, "{{ b }}": 1}
        assert text_of(element) == "1 and 1 and 2"

    def test_replacement_is_applied_right_to_left_without_corrupting_offsets(self):
        """A longer replacement earlier in the string must not shift a later one."""
        element = paragraph("{{ a }}", "-", "{{ b }}")
        runs.replace_in_paragraph(element, {"{{ a }}": "LONGER VALUE", "{{ b }}": "X"})
        assert text_of(element) == "LONGER VALUE-X"

    def test_leading_and_trailing_space_survives(self):
        """Without xml:space="preserve" Word strips it, and words run together
        in the rendered document while the XML still looks right."""
        element = paragraph("A", "{{ k }}", "B")
        runs.replace_in_paragraph(element, {"{{ k }}": " spaced "})
        node = element.findall(qn("w:r"))[1].find(qn("w:t"))
        assert node.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"
        assert text_of(element) == "A spaced B"

    def test_the_preserve_attribute_is_dropped_when_no_longer_needed(self):
        element = paragraph("A", "{{ k }}", "B")
        runs.replace_in_paragraph(element, {"{{ k }}": " x "})
        runs.replace_in_paragraph(element, {" x ": "y"})
        node = element.findall(qn("w:r"))[1].find(qn("w:t"))
        assert node.get("{http://www.w3.org/XML/1998/namespace}space") is None

    def test_replacing_with_the_empty_string(self):
        element = paragraph("keep ", "{{ drop }}", " keep")
        runs.replace_in_paragraph(element, {"{{ drop }}": ""})
        assert text_of(element) == "keep  keep"

    def test_no_match_changes_nothing(self):
        element = paragraph("untouched")
        assert runs.replace_in_paragraph(element, {"{{ k }}": "v"}) == {}
        assert text_of(element) == "untouched"

    def test_a_match_wholly_inside_one_run(self):
        element = paragraph("a {{ k }} b")
        runs.replace_in_paragraph(element, {"{{ k }}": "V"})
        assert text_of(element) == "a V b"


def part(body_xml: str) -> etree._Element:
    return etree.fromstring(f'<w:document xmlns:w="{W}"><w:body>{body_xml}</w:body></w:document>')


class TestWalking:
    TABLE = (
        "<w:p><w:r><w:t>before</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc>"
        "<w:p><w:r><w:t>Cell {{ k }}</w:t></w:r></w:p>"
        "</w:tc></w:tr></w:tbl>"
        "<w:p><w:r><w:t>after</w:t></w:r></w:p>"
    )

    def test_a_match_inside_a_table_cell(self):
        """Spec section 6's third required case. Body-only replacement is the
        classic silent bug."""
        root = part(self.TABLE)
        counts, locations = runs.replace_in_part(root, {"{{ k }}": "V"})
        assert counts == {"{{ k }}": 1}
        assert locations == ["table:1"]
        assert "Cell V" in "".join(n.text or "" for n in root.iter(qn("w:t")))

    def test_paragraphs_are_labelled_by_where_they_are(self):
        root = part(self.TABLE)
        assert [where for where, _ in runs.iter_paragraphs(root)] == [
            "body",
            "table:1",
            "body",
        ]

    def test_nested_tables_get_their_own_index(self):
        root = part(
            "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>outer</w:t></w:r></w:p>"
            "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>inner</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
            "</w:tc></w:tr></w:tbl>"
        )
        assert [where for where, _ in runs.iter_paragraphs(root)] == ["table:1", "table:2"]

    def test_the_location_label_is_configurable_for_other_parts(self):
        root = etree.fromstring(
            f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>x {{{{ k }}}}</w:t></w:r></w:p></w:hdr>'
        )
        counts, locations = runs.replace_in_part(root, {"{{ k }}": "V"}, location="header:1")
        assert counts == {"{{ k }}": 1}
        assert locations == ["header:1"]

    def test_a_text_box_paragraph_is_walked(self):
        root = part(
            "<w:p><w:r><w:txbxContent><w:p><w:r><w:t>Box {{ k }}</w:t></w:r></w:p>"
            "</w:txbxContent></w:r></w:p>"
        )
        counts, _ = runs.replace_in_part(root, {"{{ k }}": "V"})
        assert counts == {"{{ k }}": 1}

    def test_collect_text_reads_every_paragraph(self):
        root = part(self.TABLE)
        assert runs.collect_text(root) == ["before", "Cell {{ k }}", "after"]
