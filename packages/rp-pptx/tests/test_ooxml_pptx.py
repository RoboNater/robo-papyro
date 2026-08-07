"""The OOXML layer: the error boundary, the package zip, and namespaces.

The error-boundary tests are the important ones. ``opened()`` used to guard its
own ``yield``, which meant it caught every exception raised by a caller's ``with``
body and re-labelled it a corrupt file — so a mistyped slide selector reported
exit 3 on a healthy deck, and a genuine bug in read code arrived disguised as a
damaged file. These pin the boundary in both directions.
"""

from __future__ import annotations

import pytest

from rp_core.errors import CorruptFileError, InputError
from rp_pptx import ooxml
from rp_pptx.errors import InvalidPptxError, MissingFileError, RpPptxError


class TestErrorBoundary:
    def test_an_exception_from_the_with_body_keeps_its_type(self, simple_deck):
        class Marker(Exception):
            pass

        with pytest.raises(Marker):
            with ooxml.opened(simple_deck):
                raise Marker("from the caller's body")

    def test_an_input_error_from_the_body_is_not_relabelled(self, simple_deck):
        with pytest.raises(InputError):
            with ooxml.opened(simple_deck):
                raise InputError("a bad selector, say")

    def test_a_genuinely_unopenable_file_is_a_corrupt_file_error(self, tmp_path):
        import zipfile

        broken = tmp_path / "broken.pptx"
        with zipfile.ZipFile(broken, "w") as archive:
            archive.writestr("nothing.txt", "this is a zip, but not a deck")
        with pytest.raises(InvalidPptxError):
            with ooxml.opened(broken):
                pass


class TestCheckReadable:
    def test_a_missing_file_is_an_input_error(self, tmp_path):
        with pytest.raises(MissingFileError) as error:
            ooxml.check_readable(tmp_path / "nope.pptx")
        assert error.value.exit_code == 1

    def test_a_directory_is_an_input_error(self, tmp_path):
        with pytest.raises(MissingFileError):
            ooxml.check_readable(tmp_path)

    def test_a_non_zip_is_a_corrupt_file_error(self, tmp_path):
        broken = tmp_path / "fake.pptx"
        broken.write_text("not a zip", encoding="utf-8")
        with pytest.raises(InvalidPptxError) as error:
            ooxml.check_readable(broken)
        assert error.value.exit_code == 3
        assert ".ppt" in str(error.value), "says what a legacy binary .ppt means"


class TestErrorHierarchy:
    """Two axes: who raised it, and what kind of failure it is."""

    @pytest.mark.parametrize("kind", [MissingFileError, InvalidPptxError])
    def test_every_error_is_an_rp_pptx_error(self, kind):
        assert issubclass(kind, RpPptxError)

    def test_exit_codes_come_from_the_core_base(self):
        assert MissingFileError("x").exit_code == 1
        assert InvalidPptxError("x").exit_code == 3

    def test_the_unsupported_feature_error_is_a_corrupt_file_error(self):
        from rp_pptx.errors import UnsupportedFeatureError

        assert issubclass(UnsupportedFeatureError, RpPptxError)
        assert issubclass(UnsupportedFeatureError, CorruptFileError)
        assert UnsupportedFeatureError("x").exit_code == 3

    def test_errors_serialize_to_the_one_envelope_shape(self):
        envelope = InvalidPptxError("broken").to_envelope()
        assert envelope.error.type == "InvalidPptxError"
        assert envelope.error.exit_code == 3


class TestPackageParts:
    def test_part_names_lists_the_archive(self, simple_deck):
        names = ooxml.part_names(simple_deck)
        assert "[Content_Types].xml" in names
        assert "ppt/presentation.xml" in names

    def test_a_missing_part_reads_as_none(self, simple_deck):
        assert ooxml.read_part(simple_deck, "ppt/nothing.xml") is None

    def test_parsing_a_missing_part_is_none(self, simple_deck):
        assert ooxml.parse_part(simple_deck, "ppt/nothing.xml") is None

    def test_malformed_xml_becomes_a_corrupt_file_error(self, simple_deck, tmp_path):
        broken = ooxml.repack(
            simple_deck, tmp_path / "broken.pptx", {"ppt/presentation.xml": b"<not well formed"}
        )
        with pytest.raises(InvalidPptxError):
            ooxml.parse_part(broken, "ppt/presentation.xml")

    def test_repack_can_add_a_part(self, simple_deck, tmp_path):
        out = ooxml.repack(simple_deck, tmp_path / "o.pptx", {"ppt/extra.xml": b"<x/>"})
        assert "ppt/extra.xml" in ooxml.part_names(out)

    def test_repack_can_drop_a_part(self, simple_deck, tmp_path):
        out = ooxml.repack(simple_deck, tmp_path / "o.pptx", {}, omit={"docProps/thumbnail.jpeg"})
        assert "docProps/thumbnail.jpeg" not in ooxml.part_names(out)

    def test_repack_preserves_the_other_parts(self, simple_deck, tmp_path):
        out = ooxml.repack(simple_deck, tmp_path / "o.pptx", {})
        assert ooxml.part_names(out) == ooxml.part_names(simple_deck)


class TestNamespaces:
    def test_qn_expands_a_known_prefix(self):
        assert ooxml.qn("p:sldId").startswith("{http")

    def test_an_unknown_prefix_says_where_to_add_it(self):
        with pytest.raises(KeyError, match="rp_pptx.ooxml.NS"):
            ooxml.qn("zz:thing")

    def test_xpath_binds_the_full_namespace_map(self, simple_deck):
        """python-pptx overrides ``_Element.xpath`` with its own incomplete map;
        going through the compiled helper is what makes an expression behave the
        same wherever the element came from."""
        presentation = ooxml.parse_part(simple_deck, ooxml.PRESENTATION_PART)
        assert len(ooxml.xpath(presentation, "./p:sldIdLst/p:sldId")) == 3

    def test_attr_reads_a_namespaced_attribute(self, simple_deck):
        presentation = ooxml.parse_part(simple_deck, ooxml.PRESENTATION_PART)
        first = ooxml.xpath(presentation, "./p:sldIdLst/p:sldId")[0]
        assert ooxml.attr(first, "r:id").startswith("rId")


class TestCopyForEdit:
    def test_it_requires_an_output(self, simple_deck):
        with pytest.raises(InputError, match="never overwrites implicitly"):
            ooxml.copy_for_edit(simple_deck, None)

    def test_the_copy_is_detached_from_its_source(self, simple_deck, tmp_path):
        """python-pptx deserializes eagerly, which is what makes staging in a
        temp directory safe — but if that ever changed, this fails."""
        presentation, target = ooxml.copy_for_edit(simple_deck, tmp_path / "o.pptx")
        presentation.slides._sldIdLst.remove(presentation.slides._sldIdLst[0])
        ooxml.save(presentation, target)
        assert len(ooxml.part_names(simple_deck)) > 0, "the source is untouched"
        with ooxml.opened(target) as edited:
            assert len(edited.slides) == 2
