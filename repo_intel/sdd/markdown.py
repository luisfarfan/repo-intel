from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarkdownSection:
    heading_path: list[str]
    title: str
    text: str


def parse_markdown_sections(content: str) -> list[MarkdownSection]:
    lines = content.splitlines()
    sections: list[MarkdownSection] = []
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[str] = []
    current_heading_path: list[str] = []
    current_title = "Document"

    def flush() -> None:
        nonlocal current_lines, current_heading_path, current_title
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(
                MarkdownSection(
                    heading_path=list(current_heading_path) or [current_title],
                    title=current_title,
                    text=text,
                )
            )
        current_lines = []

    for line in lines:
        heading = parse_heading(line)
        if heading:
            flush()
            level, title = heading
            heading_stack[:] = [(lvl, val) for lvl, val in heading_stack if lvl < level]
            heading_stack.append((level, title))
            current_heading_path = [title for _, title in heading_stack]
            current_title = title
            current_lines.append(line)
        else:
            current_lines.append(line)

    flush()
    if not sections and content.strip():
        sections.append(
            MarkdownSection(
                heading_path=["Document"],
                title="Document",
                text=content.strip(),
            )
        )
    return sections


def parse_heading(line: str) -> tuple[int, str] | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    hashes = len(stripped) - len(stripped.lstrip("#"))
    if hashes < 1 or hashes > 6:
        return None
    title = stripped[hashes:].strip()
    if not title:
        return None
    return hashes, title

