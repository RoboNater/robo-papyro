"""``{{ placeholder }}`` substitution (spec section 8).

The syntax is deliberately tiny, so most of what is worth testing is the edges
around it: what counts as unresolved, what strict mode does *to the filesystem*
when it fails, and that a placeholder split across runs is found at all.
"""

from __future__ import annotations

import pytest

from rp_core.errors import InputError
from rp_pptx.pptx import read, write
from rp_pptx.pptx.template import fill_template, flatten


@pytest.fixture
def deck(tmp_path):
    """A template deck carrying placeholders in several shapes."""
    source = tmp_path / "template.pptx"
    write.create(
        source,
        markdown=(
            "# {{ title }}\n{{ subtitle }}\n\n"
            "## Details\n- Owner: {{ owner.name }}\n- Team: {{ owner.team }}\n"
        ),
    )
    return source


class TestFlatten:
    def test_nested_dicts_become_dotted_keys(self):
        assert flatten({"user": {"name": "Ada"}}) == {"user.name": "Ada"}

    def test_nesting_goes_as_deep_as_it_arrives(self):
        assert flatten({"a": {"b": {"c": 1}}}) == {"a.b.c": "1"}

    def test_values_are_stringified(self):
        assert flatten({"n": 3, "flag": True}) == {"n": "3", "flag": "True"}

    def test_none_becomes_empty_rather_than_the_word_none(self):
        assert flatten({"x": None}) == {"x": ""}


class TestFilling:
    def test_it_fills_flat_and_dotted_keys(self, deck, tmp_path):
        result = fill_template(
            deck,
            {"title": "Q3", "subtitle": "Review", "owner": {"name": "Ada", "team": "Core"}},
            tmp_path / "out.pptx",
        )
        assert result.unresolved == []
        texts = [p.text for s in read.get_text(result.output) for p in s.paragraphs if p.text]
        assert "Q3" in texts
        assert "Owner: Ada" in texts
        assert "Team: Core" in texts

    def test_a_bare_template_name_resolves(self, template_env, tmp_path):
        """Section 5.1's resolution applies here exactly as it does to create."""
        result = fill_template(
            "house_like", {}, tmp_path / "out.pptx", strict=False
        )
        assert result.output.is_file()

    def test_a_missing_template_is_an_input_error(self, template_env, tmp_path):
        with pytest.raises(InputError):
            fill_template("nonexistent", {}, tmp_path / "out.pptx", strict=False)

    def test_a_placeholder_split_across_runs_is_found(self, runs_deck, tmp_path):
        result = fill_template(
            runs_deck, {"name": "Ada", "role": "Engineer"}, tmp_path / "out.pptx"
        )
        assert result.unresolved == []
        assert "Hello Ada and Engineer here" in [
            p.text for s in read.get_text(result.output) for p in s.paragraphs
        ]

    def test_it_reaches_tables_groups_and_notes(self, runs_deck, tmp_path):
        """Section 8 inherits section 6's scope."""
        result = fill_template(
            runs_deck, {"name": "Ada", "role": "Eng"}, tmp_path / "out.pptx"
        )
        tables = read.get_tables(result.output)
        assert tables[0].data[0][0] == "cell Ada"
        assert "Ada" in read.get_notes(result.output)[0].text


class TestStrictness:
    def test_strict_raises_on_an_unresolved_key(self, deck, tmp_path):
        with pytest.raises(InputError, match="extra"):
            fill_template(
                deck,
                {"title": "T", "subtitle": "S", "owner": {"name": "A", "team": "B"}, "extra": "x"},
                tmp_path / "out.pptx",
            )

    def test_strict_failure_writes_nothing(self, deck, tmp_path):
        """A half-filled deck left behind is worse than no strict mode: the next
        step in a pipeline cannot tell it from success."""
        out = tmp_path / "out.pptx"
        with pytest.raises(InputError):
            fill_template(deck, {"extra": "x"}, out)
        assert not out.exists()

    def test_lax_reports_rather_than_raising(self, deck, tmp_path):
        result = fill_template(
            deck,
            {"title": "T", "subtitle": "S", "owner": {"name": "A", "team": "B"}, "extra": "x"},
            tmp_path / "out.pptx",
            strict=False,
        )
        assert result.unresolved == ["extra"]
        assert result.output.is_file()

    def test_filled_and_unresolved_are_disjoint(self, deck, tmp_path):
        result = fill_template(
            deck,
            {"title": "T", "subtitle": "S", "owner": {"name": "A", "team": "B"}, "extra": "x"},
            tmp_path / "out.pptx",
            strict=False,
        )
        assert set(result.filled) & set(result.unresolved) == set()
        assert "extra" not in result.filled

    def test_unresolved_uses_the_bare_key_not_the_decorated_form(self, deck, tmp_path):
        result = fill_template(deck, {"extra": "x"}, tmp_path / "out.pptx", strict=False)
        assert result.unresolved == ["extra"]

    def test_an_unfilled_placeholder_is_left_in_place(self, deck, tmp_path):
        result = fill_template(deck, {"title": "T"}, tmp_path / "out.pptx", strict=False)
        texts = [p.text for s in read.get_text(result.output) for p in s.paragraphs]
        assert "{{ subtitle }}" in texts, "lax mode leaves what it could not fill"


class TestNoExpressionEvaluation:
    """Section 8: no expression evaluation, no Jinja. A value is a value."""

    def test_a_value_that_looks_like_a_placeholder_is_not_re_expanded(self, deck, tmp_path):
        result = fill_template(
            deck,
            {
                "title": "{{ subtitle }}",
                "subtitle": "S",
                "owner": {"name": "A", "team": "B"},
            },
            tmp_path / "out.pptx",
        )
        texts = [p.text for s in read.get_text(result.output) for p in s.paragraphs]
        assert "{{ subtitle }}" in texts, "the literal value, not a second substitution"
