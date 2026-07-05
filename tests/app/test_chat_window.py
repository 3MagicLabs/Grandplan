"""Hermetic tests for the chat panel's pure rendering helpers (#39 stage 3).

Same discipline as test_gui_wiring.py: the Qt window itself is `pragma: no cover` (Windows +
[gui] extra), but everything it renders — the transcript HTML, the live grounding pane, the
pending-proposal card — is pure string building, pinned here so a formatting regression (or an
HTML injection through a note title) can't hide in the untestable shell.
"""

from __future__ import annotations

from grandplan.adapters.kb_ask import AskAnswer
from grandplan.adapters.kb_chat import PlanDraft
from grandplan.app.chat_window import grounding_html, proposal_html, transcript_html
from grandplan.core.models import Note, NoteType


def _note(note_id: str, title: str, body: str) -> Note:
    return Note(id=note_id, original_id=f"o-{note_id}", title=title, body=body, type=NoteType.IDEA)


def test_transcript_html_renders_turns_and_escapes_markup() -> None:
    html = transcript_html(
        (
            ("user", "what about <script>alert(1)</script>?"),
            ("assistant", "nothing & everything"),
        )
    )
    assert "you" in html and "vault" in html  # both speakers labelled
    assert (
        "&lt;script&gt;" in html and "<script>" not in html
    )  # note/user text never becomes markup
    assert "nothing &amp; everything" in html


def test_grounding_html_shows_each_source_with_snippet_and_escapes() -> None:
    answer = AskAnswer(text="grounded", sources=(("a", "T<i>tle"),), model="m")
    html = grounding_html(answer, notes={"a": _note("a", "T<i>tle", "body & <b>text</b>")})
    assert "T&lt;i&gt;tle" in html and "<i>tle" not in html
    assert "body &amp; &lt;b&gt;text&lt;/b&gt;" in html  # snippet shown, escaped
    assert "[a]" in html  # the id is visible for /show-style reference


def test_grounding_html_degrades_for_retrieval_only_and_empty() -> None:
    retrieval_only = AskAnswer(text="", sources=(("a", "Title"),), model=None)
    assert "no local model" in grounding_html(retrieval_only, notes={})
    nothing = AskAnswer(text="", sources=(), model=None)
    assert "no matching notes" in grounding_html(nothing, notes={})


def test_proposal_html_lists_steps_and_sources() -> None:
    draft = PlanDraft(
        title="Migrate",
        summary="Do the move.",
        steps=("one <bad>", "two"),
        sources=(("a", "Src & note"),),
        model="m",
    )
    html = proposal_html(draft)
    assert "Migrate" in html and "Do the move." in html
    assert "one &lt;bad&gt;" in html and "two" in html  # steps rendered, escaped
    assert "Src &amp; note" in html


def test_improvement_html_shows_before_after_and_escapes() -> None:
    from grandplan.adapters.kb_chat import ImproveDraft
    from grandplan.app.chat_window import improvement_html

    draft = ImproveDraft(
        note_id="n1",
        new_title="Better <title>",
        new_body="clean & clear",
        new_tags=("a", "b"),
        rationale="tightened wording",
        model="m",
        current_title="old <title>",
        current_body="messy",
    )
    out = improvement_html(draft)
    assert "IMPROVE [n1]" in out and "tightened wording" in out
    assert "Better &lt;title&gt;" in out and "old &lt;title&gt;" in out  # both sides escaped
    assert "clean &amp; clear" in out
    assert "a, b" in out
    assert "verbatim original is preserved" in out  # the lossless promise is stated on the card
