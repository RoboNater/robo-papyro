"""Template resolution, inspection, manifests, and synthesis (spec sections 5, 11.2)."""

from __future__ import annotations

import json

import pytest

from rp_docx import ooxml, templates
from rp_docx.errors import TemplateError
from rp_docx.models import StyleMap, TemplateManifest


class TestResolution:
    def test_an_existing_path_is_used_as_given(self, house_like_template):
        assert templates.resolve_template(house_like_template) == house_like_template

    def test_a_bare_name_resolves_against_the_template_dir(
        self, templates_env, house_like_template
    ):
        assert templates.resolve_template("house_like") == house_like_template

    def test_dotx_wins_over_docx_for_the_same_name(
        self, templates_env, minimal_template, docx_twin_template
    ):
        """Spec section 5.1: a directory holding both means someone kept a
        working copy beside the template, and the template is what was asked for."""
        assert templates.resolve_template("minimal") == minimal_template
        assert minimal_template.suffix == ".dotx"
        assert docx_twin_template.is_file()

    def test_none_falls_back_to_the_bundled_default(self, templates_env):
        resolved = templates.resolve_template(None)
        assert resolved.is_file()
        assert resolved == templates.builtin_template()

    def test_none_honours_the_configured_default(
        self, templates_env, monkeypatch, house_like_template
    ):
        monkeypatch.setenv(templates.DEFAULT_TEMPLATE_ENV, "house_like")
        assert templates.resolve_template(None) == house_like_template

    def test_an_unknown_name_lists_what_is_available(self, templates_env):
        with pytest.raises(TemplateError) as exc:
            templates.resolve_template("letterhead")
        message = str(exc.value)
        assert "letterhead" in message
        assert "house_like" in message and "minimal" in message

    def test_an_unknown_name_is_an_input_error(self, templates_env):
        with pytest.raises(TemplateError) as exc:
            templates.resolve_template("letterhead")
        assert exc.value.exit_code == 1

    def test_a_wrong_path_is_reported_as_a_path(self, templates_env, tmp_path):
        """A path-shaped argument that does not exist is a wrong path, not a
        name — sending the user to hunt the template directories would be a
        wrong diagnosis."""
        with pytest.raises(TemplateError, match="No such template file"):
            templates.resolve_template(tmp_path / "drafts" / "memo.dotx")

    def test_template_dir_env_accepts_several_directories(
        self, monkeypatch, tmp_path, template_dir, house_like_template
    ):
        import os

        other = tmp_path / "other"
        other.mkdir()
        monkeypatch.setattr(templates, "repo_root", lambda start=None: None)
        monkeypatch.setenv(templates.TEMPLATE_DIR_ENV, f"{other}{os.pathsep}{template_dir}")
        assert templates.resolve_template("house_like") == house_like_template

    def test_list_templates_covers_the_directory(
        self, templates_env, minimal_template, house_like_template, hostile_template
    ):
        names = {info.name for info in templates.list_templates()}
        assert {"minimal", "house_like", "hostile"} <= names

    def test_list_templates_skips_an_unreadable_file(self, templates_env, template_dir):
        """One bad file in a shared template directory must not hide the rest."""
        (template_dir / "broken.dotx").write_text("not a package", encoding="utf-8")
        try:
            assert "broken" not in {info.name for info in templates.list_templates()}
        finally:
            (template_dir / "broken.dotx").unlink()


class TestInspection:
    def test_house_like_reports_its_own_style_names(self, house_like_template, house_styles):
        info = templates.inspect_template(house_like_template)
        names = {style.name for style in info.styles}
        assert set(house_styles.values()) <= names

    def test_a_non_ascii_style_name_survives(self, house_like_template):
        info = templates.inspect_template(house_like_template)
        assert "Résumé Heading" in {style.name for style in info.styles}

    def test_house_like_is_a4_and_has_a_letterhead(self, house_like_template):
        info = templates.inspect_template(house_like_template)
        assert info.page_size == "A4"
        assert info.has_letterhead is True
        assert info.format == "dotx"

    def test_minimal_is_letter_with_no_letterhead(self, minimal_template):
        info = templates.inspect_template(minimal_template)
        assert info.page_size == "Letter"
        assert info.has_letterhead is False

    def test_inspection_does_not_create_a_header_part(self, minimal_template):
        """Reading section.header through python-docx *creates* the part when it
        is absent, so inspecting a template would otherwise modify it."""
        before = ooxml.part_names(minimal_template)
        templates.inspect_template(minimal_template)
        assert ooxml.part_names(minimal_template) == before

    def test_custom_styles_are_not_builtin(self, house_like_template, house_styles):
        info = templates.inspect_template(house_like_template)
        by_name = {style.name: style for style in info.styles}
        assert by_name[house_styles["body"]].builtin is False
        assert by_name["Normal"].builtin is True

    def test_base_styles_are_recorded(self, house_like_template, house_styles):
        info = templates.inspect_template(house_like_template)
        by_name = {style.name: style for style in info.styles}
        assert by_name[house_styles["h1"]].base_style == "Heading 1"

    def test_a_linked_character_style_is_reported_as_a_character_style(self, house_like_template):
        info = templates.inspect_template(house_like_template)
        by_name = {style.name: style for style in info.styles}
        assert by_name["RP Body Text Char"].type == "character"

    def test_ooxml_names_the_list_style_type_numbering(self, minimal_template):
        """python-docx spells it LIST; the file says `numbering`, and the models
        report what is in the file."""
        info = templates.inspect_template(minimal_template)
        assert {style.type for style in info.styles} <= {
            "paragraph",
            "character",
            "table",
            "numbering",
        }


class TestStyleMap:
    def test_a_template_without_a_stylemap_gets_the_builtin_defaults(self, minimal_template):
        assert templates.load_stylemap(minimal_template) == StyleMap()

    def test_house_like_loads_its_own_stylemap(self, house_like_template, house_styles):
        loaded = templates.load_stylemap(house_like_template)
        assert loaded.h1 == house_styles["h1"]
        assert loaded.body == house_styles["body"]
        assert loaded.h3 == "Résumé Heading"

    def test_a_malformed_stylemap_raises_rather_than_falling_back(self, minimal_template, tmp_path):
        """A stylemap exists because the defaults are wrong for this template.
        Quietly using them would produce the mis-styled document the file was
        added to prevent."""
        copy = tmp_path / "m.dotx"
        copy.write_bytes(minimal_template.read_bytes())
        templates.stylemap_path(copy).write_text("{not json", encoding="utf-8")
        with pytest.raises(TemplateError, match="not readable JSON"):
            templates.load_stylemap(copy)

    def test_a_wrongly_typed_stylemap_raises(self, minimal_template, tmp_path):
        copy = tmp_path / "m.dotx"
        copy.write_bytes(minimal_template.read_bytes())
        templates.stylemap_path(copy).write_text('{"h1": 3}', encoding="utf-8")
        with pytest.raises(TemplateError, match="not a valid stylemap"):
            templates.load_stylemap(copy)


class TestRequireStyle:
    def test_a_present_style_passes_through(self, minimal_template):
        with ooxml.opened(minimal_template) as document:
            assert templates.require_style(document, "h1", "Heading 1") == "Heading 1"

    def test_a_missing_style_names_itself_and_lists_alternatives(self, hostile_template):
        """Spec section 5.1: never a silent fallback."""
        with ooxml.opened(hostile_template) as document:
            with pytest.raises(TemplateError) as exc:
                templates.require_style(document, "h1", "Heading 1")
        message = str(exc.value)
        assert "'Heading 1'" in message
        assert "h1" in message
        assert "Heading 2" in message  # what the template does have

    def test_the_available_list_names_what_the_template_has(self, minimal_template):
        with ooxml.opened(minimal_template) as document:
            with pytest.raises(TemplateError) as exc:
                templates.require_style(document, "code", "Source Code")
        assert "Heading 1" in str(exc.value)

    def test_the_available_list_is_capped(self, tmp_path):
        """A template can define hundreds of styles; the message must stay
        readable rather than printing all of them."""
        import docx
        from docx.enum.style import WD_STYLE_TYPE

        document = docx.Document()
        for index in range(60):
            document.styles.add_style(f"Extra {index:03d}", WD_STYLE_TYPE.PARAGRAPH)
        with pytest.raises(TemplateError) as exc:
            templates.require_style(document, "code", "Source Code")
        assert "more" in str(exc.value)

    def test_word_has_no_builtin_code_style(self, minimal_template):
        """Which is why style resolution is checked at the point of use, not
        eagerly over the whole StyleMap: an eager check would reject
        python-docx's own default template for a role most documents never use."""
        with ooxml.opened(minimal_template) as document:
            assert "Source Code" not in templates.style_names(document, "paragraph")

    def test_case_differing_style_names_do_not_match_each_other(self, hostile_template):
        with ooxml.opened(hostile_template) as document:
            assert templates.require_style(document, "body", "House Body") == "House Body"
            assert templates.require_style(document, "body", "house body") == "house body"


class TestManifest:
    def test_a_manifest_carries_no_document_text(self, house_like_template, secret_text):
        """Spec section 5.2: redaction is a correctness property.

        house_like's body *and* its header contain SECRET_TEXT. A manifest of it
        must contain neither, anywhere in its serialized form.
        """
        manifest = templates.build_manifest(house_like_template)
        serialized = manifest.model_dump_json()
        assert secret_text not in serialized
        for word in secret_text.split():
            assert word not in serialized

    def test_a_manifest_carries_no_path_beyond_the_basename(self, house_like_template):
        manifest = templates.build_manifest(house_like_template)
        serialized = manifest.model_dump_json()
        assert str(house_like_template.parent) not in serialized
        assert manifest.name == "house_like"

    def test_a_manifest_records_the_shape(self, house_like_template):
        manifest = templates.build_manifest(house_like_template)
        assert manifest.format == "dotx"
        assert manifest.page_size == "A4"
        assert manifest.has_letterhead is True
        assert manifest.header_image_count == 1
        assert manifest.section_count == 1
        assert manifest.page_margins_twips["left"] == 1417

    def test_a_manifest_records_the_header_and_footer_distances(self, house_like_template):
        """python-docx spells these header_distance/footer_distance, not
        *_margin. Reading them as if they were *_margin records a template's
        header position as absent rather than as what it is."""
        margins = templates.build_manifest(house_like_template).page_margins_twips
        assert {"top", "bottom", "left", "right", "header", "footer"} <= set(margins)

    def test_a_manifest_records_the_default_paragraph_style(self, minimal_template):
        """Read from w:style/@w:default; python-docx exposes no accessor for it,
        so an unread flag would silently report every template as having none."""
        assert templates.build_manifest(minimal_template).default_paragraph_style == "Normal"

    def test_a_manifest_carries_the_stylemap_when_one_sits_beside_it(
        self, house_like_template, house_styles
    ):
        manifest = templates.build_manifest(house_like_template)
        assert manifest.stylemap is not None
        assert manifest.stylemap.h1 == house_styles["h1"]

    def test_a_manifest_without_a_stylemap_says_so(self, hostile_template):
        assert templates.build_manifest(hostile_template).stylemap is None

    def test_a_manifest_round_trips_through_json(self, house_like_template, tmp_path):
        manifest = templates.build_manifest(house_like_template)
        path = tmp_path / "house_like.manifest.json"
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        assert templates.load_manifest(path) == manifest

    def test_load_manifest_rejects_junk(self, tmp_path):
        path = tmp_path / "bad.manifest.json"
        path.write_text('{"name": "x"}', encoding="utf-8")
        with pytest.raises(TemplateError, match="not a valid template manifest"):
            templates.load_manifest(path)

    def test_load_manifest_reports_a_missing_file(self, tmp_path):
        with pytest.raises(TemplateError, match="No such manifest"):
            templates.load_manifest(tmp_path / "nope.json")


class TestSynthesis:
    def test_synthesis_reproduces_the_style_set(self, house_like_template, tmp_path):
        """Spec section 11.2: synthesize(build_manifest(t)) produces a template
        whose TemplateInfo.styles equals the original's. This is what lets CI
        exercise a confidential template's shape from a committed JSON file."""
        original = templates.inspect_template(house_like_template)
        rebuilt = templates.inspect_template(
            templates.synthesize(templates.build_manifest(house_like_template), tmp_path / "s.dotx")
        )
        assert rebuilt.styles == original.styles

    def test_synthesis_reproduces_page_size_and_letterhead(self, house_like_template, tmp_path):
        rebuilt = templates.inspect_template(
            templates.synthesize(templates.build_manifest(house_like_template), tmp_path / "s.dotx")
        )
        assert rebuilt.page_size == "A4"
        assert rebuilt.has_letterhead is True

    def test_synthesis_reproduces_margins(self, house_like_template, tmp_path):
        source = templates.build_manifest(house_like_template)
        rebuilt = templates.build_manifest(templates.synthesize(source, tmp_path / "s.dotx"))
        assert rebuilt.page_margins_twips == source.page_margins_twips

    def test_synthesis_emits_a_genuine_dotx(self, minimal_template, tmp_path):
        written = templates.synthesize(
            templates.build_manifest(minimal_template), tmp_path / "out.dotx"
        )
        assert ooxml.is_template(written)

    def test_synthesis_carries_no_content_from_the_original(
        self, house_like_template, secret_text, tmp_path
    ):
        """The whole point: the rebuilt template has the original's shape and
        none of its text, because the manifest never held any."""
        written = templates.synthesize(
            templates.build_manifest(house_like_template), tmp_path / "s.dotx"
        )
        root = ooxml.parse_part(written, ooxml.DOCUMENT_PART)
        assert secret_text not in ooxml.read_part(written, ooxml.DOCUMENT_PART).decode(
            "utf-8", "replace"
        )
        assert root is not None

    def test_synthesis_writes_the_stylemap_beside_the_template(
        self, house_like_template, house_styles, tmp_path
    ):
        written = templates.synthesize(
            templates.build_manifest(house_like_template), tmp_path / "s.dotx"
        )
        beside = templates.stylemap_path(written)
        assert beside.is_file()
        assert json.loads(beside.read_text(encoding="utf-8"))["h1"] == house_styles["h1"]

    def test_synthesis_reproduces_the_section_count(self, tmp_path):
        manifest = TemplateManifest(
            name="multi", format="dotx", styles=[], page_size="Letter", section_count=3
        )
        written = templates.synthesize(manifest, tmp_path / "multi.dotx")
        assert templates.build_manifest(written).section_count == 3

    def test_synthesis_handles_an_unnamed_page_size(self, tmp_path):
        manifest = TemplateManifest(
            name="odd", format="dotx", styles=[], page_size="9000x13000 twips"
        )
        written = templates.synthesize(manifest, tmp_path / "odd.dotx")
        assert templates.inspect_template(written).page_size == "9000x13000 twips"


class TestStyleMapScaffold:
    def test_an_exact_name_match_wins(self, house_like_template):
        """house_like keeps the built-ins as base styles, so both "Heading 1"
        and "House Heading 1" are present. An exact match is the safer guess:
        a template that still defines "Heading 1" almost certainly means it."""
        scaffold = templates.scaffold_stylemap(house_like_template)
        assert scaffold.h1 == "Heading 1"

    def test_the_scaffold_finds_a_house_name_when_there_is_no_builtin(self, hostile_template):
        """hostile has no "Heading 1" at all, so h1 falls to the closest
        substring match rather than to a style that does not exist."""
        scaffold = templates.scaffold_stylemap(hostile_template)
        assert scaffold.h1 != "Heading 1"
        assert scaffold.h1 in {s.name for s in templates.inspect_template(hostile_template).styles}

    def test_the_scaffold_matches_a_table_style(self, house_like_template):
        assert templates.scaffold_stylemap(house_like_template).table == "Table Grid"

    def test_the_scaffold_is_only_a_guess(self, house_like_template):
        """ "Résumé Heading" matches no h3 pattern, so the scaffold gets it wrong
        — the h3 role is the one this template renamed, and the scaffold cannot
        know that. Exactly why the CLI marks its output as needing review rather
        than as authoritative (spec section 10)."""
        scaffold = templates.scaffold_stylemap(house_like_template)
        assert scaffold.h3 != "Résumé Heading"

    def test_the_scaffold_falls_back_to_the_default_for_an_unmatched_role(self, minimal_template):
        scaffold = templates.scaffold_stylemap(minimal_template)
        assert scaffold.h1 == "Heading 1"
