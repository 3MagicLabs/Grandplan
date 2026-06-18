"""Tests for resource extraction (URLs / images / files / placeholders) from a capture."""

from __future__ import annotations

import pytest

from grandplan.core.resources import Resource, ResourceKind, extract_resources


def test_extracts_an_external_link() -> None:
    assert extract_resources("see https://example.com/page for context") == (
        Resource(ResourceKind.LINK, "https://example.com/page"),
    )


def test_image_url_is_classified_as_image() -> None:
    assert extract_resources("logo at https://cdn.site/img.PNG") == (
        Resource(ResourceKind.IMAGE, "https://cdn.site/img.PNG"),
    )


def test_trailing_punctuation_is_trimmed_from_a_url() -> None:
    (resource,) = extract_resources("visit https://example.com.")
    assert resource.ref == "https://example.com"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("the doc is /Users/me/plan.pdf here", Resource(ResourceKind.FILE, "/Users/me/plan.pdf")),
        ("pic ~/photos/cat.jpg", Resource(ResourceKind.IMAGE, "~/photos/cat.jpg")),
        ("draft ./notes/spec.md today", Resource(ResourceKind.FILE, "./notes/spec.md")),
        (r"open C:\docs\plan.docx", Resource(ResourceKind.FILE, r"C:\docs\plan.docx")),
    ],
)
def test_extracts_file_paths(text: str, expected: Resource) -> None:
    assert extract_resources(text) == (expected,)


def test_url_slashes_are_not_re_extracted_as_a_path() -> None:
    # A URL containing a path-with-extension must yield ONE link, not also a phantom file resource.
    assert extract_resources("download https://x.com/a/b.pdf now") == (
        Resource(ResourceKind.LINK, "https://x.com/a/b.pdf"),
    )


def test_duplicate_references_are_deduped() -> None:
    assert extract_resources("https://x.com and again https://x.com") == (
        Resource(ResourceKind.LINK, "https://x.com"),
    )


@pytest.mark.parametrize(
    ("text", "ref"),
    [
        ("I need to make a resume website", "resume"),
        ("write a report on the launch", "report"),
        ("create a landing page for the product", "page"),
    ],
)
def test_creation_intent_yields_a_placeholder(text: str, ref: str) -> None:
    assert extract_resources(text) == (Resource(ResourceKind.PLACEHOLDER, ref),)


@pytest.mark.parametrize(
    "text",
    ["make sure the page loads", "just a passing thought", "I read a great document yesterday"],
)
def test_no_false_placeholder(text: str) -> None:
    assert all(r.kind is not ResourceKind.PLACEHOLDER for r in extract_resources(text))


def test_plain_text_has_no_resources() -> None:
    assert extract_resources("a perfectly ordinary note about coffee") == ()
