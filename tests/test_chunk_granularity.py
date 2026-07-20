"""Regression tests for chunk granularity.

Guards the defect found while validating retrieval against the real corpus: a guardrail
buried in a long, heterogeneous section was indexed and embedded, yet unreachable — a query
quoting it almost verbatim did not return it. Root cause was not indexing and not a
chunk/vector misalignment (both verified fine); it was that the whole section became ONE
chunk, so a single vector had to represent four unrelated rules and matched none of them
sharply. Measured with nomic-embed-text on the real text: the full 1749-char section scored
0.684 against an Alembic-revision-id query, the 702-char fragment carrying only that rule
scored 0.783.
"""

from repo_intel.sdd.chunking import MAX_CHUNK_CHARS, _split_blocks, split_large_section
from repo_intel.sdd.markdown import MarkdownSection


def _section(text: str) -> MarkdownSection:
    return MarkdownSection(title="Convenciones de código", heading_path=["Convenciones"], text=text)


# Shape of the real AGENTS.md section that exposed the bug: consecutive top-level bullets,
# no blank lines between them, one of them multi-line.
GUARDRAIL_SECTION = "\n".join(
    [
        "- Todos los métodos de repositorio son `async def`",
        "- Las excepciones del use case usan prefijos en el mensaje para routing en el router",
        "- Los schemas Pydantic usan `model_validator(mode=\"after\")` para validaciones cross-field",
        "- **Migraciones — revision IDs únicos (CRÍTICO):** los IDs existentes siguen un patrón",
        "  hex secuencial. NUNCA inventes un ID siguiendo ese patrón — colisiona con revisiones",
        "  ancestrales existentes y corrompe el grafo (aparecen múltiples heads).",
    ]
)


def test_consecutive_bullets_are_separate_blocks():
    """The original splitter only broke on blank lines, so this list stayed a single block."""
    blocks = _split_blocks(GUARDRAIL_SECTION)
    assert len(blocks) == 4, f"expected one block per top-level bullet, got {len(blocks)}"


def test_multiline_bullet_keeps_its_continuation_lines():
    """A rule must never be cut in half: indented continuations belong to their bullet."""
    blocks = _split_blocks(GUARDRAIL_SECTION)
    migration = [b for b in blocks if "Migraciones" in b]
    assert len(migration) == 1
    # The premise, the prohibition and the consequence must all survive in one piece.
    assert "hex secuencial" in migration[0]
    assert "NUNCA inventes" in migration[0]
    assert "múltiples heads" in migration[0]


def test_blank_lines_still_split():
    """Paragraph splitting must keep working — bullets are an additional boundary, not a
    replacement."""
    assert len(_split_blocks("Primer párrafo.\n\nSegundo párrafo.")) == 2


def test_prose_without_bullets_is_untouched():
    """A single prose paragraph is one block; no spurious splitting."""
    assert _split_blocks("Una sola línea de prosa sin viñetas.") == [
        "Una sola línea de prosa sin viñetas."
    ]


def test_ceiling_is_tight_enough_to_split_grab_bag_sections():
    """The ceiling is the other half of the fix.

    At the previous 4200 the real 1749-char section was never split at all, so the smarter
    block splitting would never have run for it.
    """
    assert MAX_CHUNK_CHARS <= 1200
    assert len(GUARDRAIL_SECTION) < 4200, "fixture must be under the OLD ceiling"


def test_large_section_splits_on_bullet_boundaries():
    """End-to-end through the public entry point, with a section over the ceiling."""
    filler = "- " + ("relleno " * 40) + "\n"
    big = filler * 12 + GUARDRAIL_SECTION
    assert len(big) > MAX_CHUNK_CHARS

    parts = split_large_section(_section(big))
    assert len(parts) > 1
    for part in parts:
        assert len(part) <= MAX_CHUNK_CHARS, "no part may exceed the ceiling"

    # The guardrail must survive intact inside exactly one part, not straddle two.
    carrying = [p for p in parts if "NUNCA inventes" in p]
    assert len(carrying) == 1
    assert "múltiples heads" in carrying[0]
