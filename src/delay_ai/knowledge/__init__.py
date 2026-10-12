"""Expert context in Markdown files, given to the LLM whole (no retrieval)."""

from pathlib import Path

FOLDER = Path(__file__).parent
FILES = ("construction.md", "scheduling.md", "playbook.md")


def load(*names: str) -> str:
    """The named files (all of them by default), joined into one prompt section."""
    return "\n\n".join((FOLDER / name).read_text().strip() for name in names or FILES)
