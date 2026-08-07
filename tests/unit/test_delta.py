import pytest

from ai_council.delta import (
    PatchError,
    apply_edits,
    extract_edit_blocks,
    has_edit_blocks,
    resolve_revision_document,
)

DOC = """# Design

The importer validates rows.

## Coverage

- REQ-001: validated pre-write.
- REQ-002: upsert by SKU.
"""

EDIT = """Commentary the applier should ignore.

<<<<<<< SEARCH
- REQ-002: upsert by SKU.
=======
- REQ-002: upsert by SKU with a unique constraint.
>>>>>>> REPLACE
"""


def test_extract_and_apply():
    blocks = extract_edit_blocks(EDIT)
    assert len(blocks) == 1
    assert blocks[0].search == "- REQ-002: upsert by SKU."
    result = apply_edits(DOC, blocks)
    assert "unique constraint" in result
    assert "- REQ-001: validated pre-write." in result  # rest untouched


def test_has_edit_blocks():
    assert has_edit_blocks(EDIT)
    assert not has_edit_blocks(DOC)


def test_multiple_blocks_apply_in_order():
    text = (
        "<<<<<<< SEARCH\n# Design\n=======\n# Design v2\n>>>>>>> REPLACE\n"
        "<<<<<<< SEARCH\n- REQ-001: validated pre-write.\n=======\n"
        "- REQ-001: validated twice.\n>>>>>>> REPLACE\n"
    )
    result = apply_edits(DOC, extract_edit_blocks(text))
    assert "# Design v2" in result and "validated twice" in result


def test_empty_search_appends():
    text = "<<<<<<< SEARCH\n=======\n## Rollback\n\nBatches roll back.\n>>>>>>> REPLACE\n"
    result = apply_edits(DOC, extract_edit_blocks(text))
    assert result.endswith("## Rollback\n\nBatches roll back.\n")


def test_search_not_found():
    text = "<<<<<<< SEARCH\nthis text does not exist\n=======\nx\n>>>>>>> REPLACE\n"
    with pytest.raises(PatchError, match="not found"):
        apply_edits(DOC, extract_edit_blocks(text))


def test_ambiguous_search():
    doc = "same line\nother\nsame line\n"
    text = "<<<<<<< SEARCH\nsame line\n=======\nnew\n>>>>>>> REPLACE\n"
    with pytest.raises(PatchError, match="matches 2 locations"):
        apply_edits(doc, extract_edit_blocks(text))


def test_no_blocks_is_error():
    with pytest.raises(PatchError, match="no edit blocks"):
        apply_edits(DOC, [])


def test_resolve_falls_back_to_full_document():
    assert resolve_revision_document("# A whole new doc\n", DOC) == "# A whole new doc\n"
    assert "unique constraint" in resolve_revision_document(EDIT, DOC)
