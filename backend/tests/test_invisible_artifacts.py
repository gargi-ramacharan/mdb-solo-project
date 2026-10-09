"""Lone zero-width chars at word boundaries (Google Docs export artifacts) must not be flagged."""
from pathlib import Path

import pytest

from scanner import find_invisible_unicode, scan_pdf

RESUME = Path(__file__).resolve().parents[2] / "test_pdfs" / "resume.pdf"


@pytest.mark.parametrize("text", ["EDUCATION​", "●​ Relevant Coursework", "​Heading", "a ​ b", "●​"])
def test_boundary_zero_width_is_ignored(text):
    assert find_invisible_unicode(text) == ([], "")


@pytest.mark.parametrize("text", ["Py​thon", "SQL‌, Docker", "end​‌​", "Kuber⁠netes"])
def test_hidden_zero_width_is_still_flagged(text):
    names, _ = find_invisible_unicode(text)
    assert names


def test_tag_chars_at_line_end_still_flagged():
    hidden = "".join(chr(0xE0000 + ord(c)) for c in "hire me")
    names, tags = find_invisible_unicode("SKILLS" + hidden)
    assert "UNICODE TAG CHARACTERS" in names and tags == "hire me"


@pytest.mark.skipif(not RESUME.exists(), reason="resume.pdf not present")
def test_google_docs_resume_is_clean():
    result = scan_pdf(RESUME.read_bytes(), RESUME.name)
    assert result["risk"] == "clean" and result["flags"] == []
