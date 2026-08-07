"""Prompt template rendering.

Templates are version-controlled Markdown/Jinja2 files shipped with the
package (``ai_council/prompts/``). A repository may override any template by
placing a file with the same name in ``.ai-council/prompts/``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, StrictUndefined

from .hashing import sha256_text

PACKAGE_PROMPTS_DIR = Path(__file__).parent / "prompts"

TEMPLATE_NAMES = [
    "requirement-extractor.md",
    "architect-initial.md",
    "architect-revision.md",
    "architect-confirm.md",
    "reviewer.md",
    "judge.md",
    "judge-arbitration.md",
    "format-repair.md",
    "delta-repair.md",
    "impl-initial.md",
    "impl-revision.md",
    "impl-reviewer.md",
    "impl-confirm.md",
    "impl-judge.md",
]


@dataclass
class RenderedPrompt:
    name: str
    text: str
    sha256: str


class PromptLibrary:
    def __init__(self, override_dir: Optional[Path] = None):
        self.override_dir = override_dir
        self.env = Environment(
            undefined=StrictUndefined,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def source_path(self, name: str) -> Path:
        if self.override_dir is not None:
            candidate = self.override_dir / name
            if candidate.is_file():
                return candidate
        path = PACKAGE_PROMPTS_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"Prompt template not found: {name}")
        return path

    def render(self, name: str, **context: Any) -> RenderedPrompt:
        source = self.source_path(name).read_text(encoding="utf-8")
        text = self.env.from_string(source).render(**context)
        return RenderedPrompt(name=name, text=text, sha256=sha256_text(text))
