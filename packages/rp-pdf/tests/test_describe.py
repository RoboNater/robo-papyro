"""Job descriptions: what the user is told before an expensive run starts.

These are pure functions over the resolved-options dict the CLI builds, so they
are tested directly rather than through a subprocess. The assertions are about
the two things a description is for: reporting what *is* switched on, and
naming the flag for what is not — "did I forget --ocr?" is the question.
"""

from __future__ import annotations

from pathlib import Path

from rp_pdf import describe

FILE = Path("report.pdf")


def rows(entries) -> dict[str, str]:
    return dict(entries)


class TestMarkdown:
    defaults = {
        "pages": "all",
        "physical": False,
        "engine": "poppler",
        "images_dir": None,
        "ai": False,
        "ocr": False,
        "model": None,
        "base_url": None,
        "organization": None,
        "jobs": 1,
        "dpi": 150,
        "outline_headings": False,
        "outline_context": False,
        "full": False,
        "cache": True,
        "cache_dir": None,
        "out": None,
    }

    def describe_with(self, **overrides):
        title, entries = describe.markdown_job(FILE, {**self.defaults, **overrides})
        return title, rows(entries)

    def test_title_names_the_command_and_the_file(self):
        title, _ = self.describe_with()
        assert title == "rp-pdf markdown — report.pdf"

    def test_everything_off_says_how_to_turn_it_on(self):
        _, r = self.describe_with()
        assert r["AI review"].startswith("off")
        assert "--ai" in r["AI review"]
        assert "--ai --ocr" in r["OCR"]  # OCR needs both, and says so
        assert "--images-dir" in r["images"]
        assert "--outline-headings" in r["outline"]

    def test_the_ai_row_names_the_model_and_the_endpoint(self):
        _, r = self.describe_with(
            ai=True, model="gpt-4o-mini", base_url="https://openrouter.ai/api/v1", jobs=4
        )
        assert "gpt-4o-mini" in r["AI review"]
        assert "openrouter.ai" in r["AI review"]
        assert "4 concurrent" in r["AI review"]
        assert "150 dpi" in r["AI review"]

    def test_an_unset_model_is_called_out_rather_than_omitted(self):
        """The commonest first-run failure. Silence here reads as 'configured'."""
        _, r = self.describe_with(ai=True)
        assert "unset" in r["AI review"]
        assert "RP_PDF_VLM_MODEL" in r["AI review"]

    def test_ocr_on_needs_no_hint(self):
        _, r = self.describe_with(ai=True, model="m", ocr=True)
        assert r["OCR"].startswith("on")
        assert "--ocr" not in r["OCR"]

    def test_the_cache_row_appears_only_when_the_ai_pass_runs(self):
        assert "cache" not in self.describe_with()[1]
        _, r = self.describe_with(ai=True, model="m")
        assert "~/.cache/rp-pdf" in r["cache"]
        _, off = self.describe_with(ai=True, model="m", cache=False)
        assert off["cache"].startswith("off")

    def test_numbering_is_explained_only_when_a_page_spec_needs_it(self):
        """'all' means the same either way, so the row would be noise."""
        assert "numbering" not in self.describe_with()[1]
        assert "page labels" in self.describe_with(pages="4-9")[1]["numbering"]
        assert "physical" in self.describe_with(pages="4-9", physical=True)[1]["numbering"]

    def test_output_says_where_the_markdown_goes(self):
        assert "stdout" in self.describe_with()[1]["output"]
        assert self.describe_with(out=Path("out.md"))[1]["output"] == "out.md"

    def test_the_engine_row_flags_the_word_spacing_risk(self):
        assert "issue #1" in self.describe_with(engine="pypdf")[1]["engine"]
        assert "pdftotext" in self.describe_with()[1]["engine"]


class TestOtherCommands:
    def test_text(self):
        title, entries = describe.text_job(
            FILE,
            {"pages": "all", "physical": False, "engine": "poppler", "layout": True, "plain": True},
        )
        r = rows(entries)
        assert title == "rp-pdf text — report.pdf"
        assert r["layout"] == "preserved"
        assert r["output"] == "raw text"

    def test_tables_without_csv_says_where_the_output_goes(self):
        r = rows(describe.tables_job(FILE, {"pages": "all", "physical": False, "csv": None})[1])
        assert "--csv" in r["output"]
        r = rows(
            describe.tables_job(FILE, {"pages": "all", "physical": False, "csv": Path("out")})[1]
        )
        assert r["output"] == "out"

    def test_search_quotes_the_query_and_names_the_mode(self):
        title, entries = describe.search_job(
            FILE,
            "widget",
            {
                "pages": "all",
                "physical": False,
                "regex": True,
                "case_sensitive": False,
                "max": 25,
                "engine": "poppler",
            },
        )
        r = rows(entries)
        assert "'widget'" in r["query"] and "regex" in r["query"]
        assert r["matching"] == "case-insensitive"
        assert r["limit"] == "25 hits"

    def test_images_warns_when_nothing_will_be_written(self):
        r = rows(describe.images_job(FILE, {"pages": "all", "physical": False, "out": None})[1])
        assert "metadata only" in r["output"]

    def test_render(self):
        r = rows(
            describe.render_job(
                FILE,
                {
                    "pages": "1-5",
                    "physical": True,
                    "dpi": 300,
                    "format": "jpeg",
                    "out": Path("pages"),
                },
            )[1]
        )
        assert r["format"] == "jpeg at 300 dpi"
        assert r["output"] == "pages"
