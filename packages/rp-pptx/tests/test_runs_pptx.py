from rp_pptx.pptx.runs import replace_in_paragraph


class _Run:
    def __init__(self, text):
        self.text = text


class _Paragraph:
    def __init__(self, *parts):
        self.runs = [_Run(part) for part in parts]


def test_replacement_spans_runs():
    paragraph = _Paragraph("{{ na", "me }}", "!")
    assert replace_in_paragraph(paragraph, "{{ name }}", "Ada") == 1
    assert "".join(run.text for run in paragraph.runs) == "Ada!"
