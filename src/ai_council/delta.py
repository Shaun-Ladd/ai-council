"""Delta revisions: SEARCH/REPLACE edit blocks applied by the orchestrator.

Instead of regenerating the entire proposal each round, the architect may
emit targeted edit blocks:

    <<<<<<< SEARCH
    exact text copied from the current proposal
    =======
    replacement text
    >>>>>>> REPLACE

The ORCHESTRATOR applies the edits deterministically to the current version
and assembles the complete new document itself — which is then hashed and
stored immutably exactly like a fully regenerated proposal, so the
version/hash/consensus contract is unchanged. An edit block with an empty
SEARCH section appends to the end of the document.

Application is strict: every SEARCH must match exactly once. Failures raise
:class:`PatchError` with a precise reason so the architect can be asked to
correct its edits (bounded), with full-document regeneration as the final
fallback.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_BLOCK_RE = re.compile(
    r"^<{4,9}[ \t]*SEARCH[ \t]*\n(?P<search>.*?)^={4,9}[ \t]*\n(?P<replace>.*?)^>{4,9}[ \t]*REPLACE[ \t]*$",
    re.DOTALL | re.MULTILINE,
)


class PatchError(Exception):
    pass


@dataclass
class EditBlock:
    search: str
    replace: str


def _trim_one_newline(text: str) -> str:
    return text[:-1] if text.endswith("\n") else text


def has_edit_blocks(text: str) -> bool:
    return _BLOCK_RE.search(text) is not None


def extract_edit_blocks(text: str) -> list[EditBlock]:
    return [
        EditBlock(
            search=_trim_one_newline(m.group("search")),
            replace=_trim_one_newline(m.group("replace")),
        )
        for m in _BLOCK_RE.finditer(text)
    ]


def apply_edits(document: str, blocks: list[EditBlock]) -> str:
    """Apply edit blocks in order; each SEARCH must match exactly once."""
    if not blocks:
        raise PatchError("no edit blocks found in the response")
    doc = document
    for i, block in enumerate(blocks, 1):
        if not block.search.strip():
            addition = block.replace.strip("\n")
            if addition:
                doc = doc.rstrip("\n") + "\n\n" + addition + "\n"
            continue
        count = doc.count(block.search)
        if count == 0:
            snippet = block.search.strip().splitlines()[0][:80]
            raise PatchError(
                f"edit block {i}: SEARCH text not found in the current proposal "
                f"(starts with: {snippet!r}). SEARCH must be copied EXACTLY, "
                "character for character, from the current proposal."
            )
        if count > 1:
            raise PatchError(
                f"edit block {i}: SEARCH text matches {count} locations; "
                "include more surrounding lines to make it unique."
            )
        doc = doc.replace(block.search, block.replace, 1)
    return doc


def resolve_revision_document(body: str, current_document: str) -> str:
    """Turn an architect revision body into the complete new document.

    Delta mode when edit blocks are present (surrounding prose is treated as
    commentary and ignored); otherwise the body IS the full document."""
    if has_edit_blocks(body):
        return apply_edits(current_document, extract_edit_blocks(body))
    return body
