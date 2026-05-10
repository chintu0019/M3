from m3.core.item_title import extract_title


def test_yaml_frontmatter_title():
    body = '---\ntitle: "Manoj Kesavulu"\nsource: telegram\n---\n\nbody here'
    assert extract_title(body, None) == "Manoj Kesavulu"


def test_yaml_frontmatter_title_unquoted():
    body = "---\ntitle: Manoj Kesavulu\n---\nbody"
    assert extract_title(body, None) == "Manoj Kesavulu"


def test_markdown_h1_when_no_frontmatter():
    body = "# Project PACIFIC\n\nThe launch timeline is..."
    assert extract_title(body, None) == "Project PACIFIC"


def test_first_non_empty_line_fallback():
    body = "\n\nHad a call with Aditya about the rollout.\nLong content..."
    assert extract_title(body, None) == "Had a call with Aditya about the rollout."


def test_first_line_caps_at_120_chars():
    body = "x" * 200
    assert extract_title(body, None) == "x" * 120


def test_filename_fallback_when_body_empty():
    assert extract_title("", "weekly-review-2026-q1.pdf") == "weekly review 2026 q1"
    assert extract_title(None, "notes.md") == "notes"


def test_returns_none_when_nothing_to_extract():
    assert extract_title(None, None) is None
    assert extract_title("", None) is None


def test_frontmatter_without_title_falls_through_to_body():
    body = "---\nsource: telegram\nauthor: someone\n---\nFirst real line"
    assert extract_title(body, None) == "First real line"


def test_markdown_h1_with_no_frontmatter_present():
    """The H1 path is exercised when there's no frontmatter at all."""
    body = "# Real Title\n\nrest of the document"
    assert extract_title(body, None) == "Real Title"
