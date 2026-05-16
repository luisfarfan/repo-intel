from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


OVERVIEW_TERMS = {
    "que es",
    "qué es",
    "overview",
    "resumen",
    "producto",
    "organizado",
    "organizacion",
    "organización",
    "repos",
    "repositorios",
}

TECHNICAL_TERMS = {
    "arquitectura",
    "endpoint",
    "api",
    "flujo",
    "checkout",
    "pos",
    "offline",
    "facturacion",
    "facturación",
    "builder",
    "storefront",
    "adr",
    "contrato",
    "contract",
    "integracion",
    "integración",
}

NAVIGATION_TERMS = {
    "donde empiezo",
    "dónde empiezo",
    "por donde empiezo",
    "por dónde empiezo",
    "que documentos",
    "qué documentos",
    "donde esta",
    "dónde está",
    "donde encuentro",
    "dónde encuentro",
}

REPO_TERMS = {
    "repo",
    "repositorio",
    "proxima-api",
    "proxima-admin",
    "proxima-builder",
    "proxima-pos",
    "proxima-website",
    "proxima-infra",
    "proxima-qa",
    "proxima-intelligence",
}

DOMAIN_TERMS = {
    "billing",
    "facturacion",
    "facturación",
    "inventory",
    "inventario",
    "checkout",
    "commerce",
    "storefront",
    "builder",
    "pos",
    "analytics",
}

OVERVIEW_PATH_TERMS = {
    "project-brief.md",
    "readme.md",
    "product.md",
    "ai_index.md",
    "agent_start_here.md",
    "00-overview",
    "overview",
}

TECHNICAL_DOC_TYPES = {"architecture", "api-contract", "sdd-spec", "adr", "integration"}


@dataclass(frozen=True)
class QuestionIntent:
    name: str
    confidence: float
    signals: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RetrievalPlan:
    intent: QuestionIntent
    final_limit: int
    candidate_limit: int
    include_brief: bool
    overview_boost: float = 0.15
    technical_boost: float = 0.15
    keyword_boost: float = 0.2
    brief_boost: float = 0.2
    lexical_limit: int = 24


def classify_question(question: str) -> QuestionIntent:
    text = normalize(question)
    signals: list[str] = []

    if any(term in text for term in NAVIGATION_TERMS):
        signals.append("navigation-term")
        return QuestionIntent(name="navigation", confidence=0.85, signals=signals)

    repo_hits = [term for term in REPO_TERMS if contains_query_term(text, normalize(term))]
    if repo_hits:
        return QuestionIntent(name="repo_oriented", confidence=0.8, signals=repo_hits)

    domain_hits = [term for term in DOMAIN_TERMS if term in text]
    technical_hits = [term for term in TECHNICAL_TERMS if term in text]
    overview_hits = [term for term in OVERVIEW_TERMS if term in text]

    if overview_hits and not technical_hits:
        return QuestionIntent(name="overview", confidence=0.82, signals=overview_hits)
    if technical_hits:
        return QuestionIntent(name="technical", confidence=0.8, signals=technical_hits)
    if domain_hits:
        return QuestionIntent(name="domain_oriented", confidence=0.72, signals=domain_hits)
    return QuestionIntent(name="default", confidence=0.5, signals=[])


def build_retrieval_plan(intent: QuestionIntent, requested_limit: int | None, default_limit: int) -> RetrievalPlan:
    final_limit = requested_limit or default_limit
    final_limit = max(3, final_limit)
    return RetrievalPlan(
        intent=intent,
        final_limit=final_limit,
        candidate_limit=max(final_limit * 4, 16),
        include_brief=intent.name in {"overview", "navigation"},
    )


def rerank_results(question: str, results: list[dict], plan: RetrievalPlan) -> list[dict]:
    query_terms = extract_query_terms(question)
    question_keywords = query_terms["keywords"]
    question_phrases = query_terms["phrases"]
    ranked = []
    for result in results:
        metadata = result.get("metadata", {})
        distance = result.get("distance")
        base_score = 0.0 if distance is None else max(0.0, 1.0 - float(distance))
        score = base_score
        reasons = [f"base={base_score:.4f}"]

        path = normalize(str(metadata.get("path", "")))
        doc_type = normalize(str(metadata.get("doc_type", "")))
        section = normalize(str(metadata.get("section", "")))
        text = normalize(str(result.get("text", ""))[:1200])
        haystack = f"{path} {doc_type} {section} {text}"

        lexical_score = float(result.get("lexical_score", 0.0) or 0.0)
        if lexical_score:
            score += lexical_score
            reasons.append(f"lexical={lexical_score:.4f}")

        if plan.intent.name in {"overview", "navigation"} and is_overview_source(path, doc_type):
            score += plan.overview_boost
            reasons.append("overview_boost")

        if plan.intent.name in {"technical", "domain_oriented"} and doc_type in TECHNICAL_DOC_TYPES:
            score += plan.technical_boost
            reasons.append("technical_boost")

        overlap = [keyword for keyword in question_keywords if contains_query_term(haystack, keyword)]
        if overlap:
            score += plan.keyword_boost * min(1.5, len(overlap) / 2)
            reasons.append(f"keyword_overlap={','.join(overlap[:6])}")

        phrase_overlap = [phrase for phrase in question_phrases if phrase in haystack]
        if phrase_overlap:
            score += plan.keyword_boost * 1.5
            reasons.append(f"phrase_overlap={','.join(phrase_overlap[:4])}")

        if plan.intent.name in {"technical", "domain_oriented"} and is_low_value_doc_for_intent(
            path, doc_type
        ):
            score -= 0.2
            reasons.append("low_value_for_technical")

        enriched = dict(result)
        enriched["score"] = score
        enriched["score_reasons"] = reasons
        ranked.append(enriched)

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return dedupe_by_source(ranked)


def load_project_brief_context(workspace: Path) -> dict | None:
    path = workspace / ".repo-intel" / "briefs" / "project-brief.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        "id": "brief:project",
        "text": text,
        "metadata": {
            "repo": "project",
            "path": ".repo-intel/briefs/project-brief.md",
            "section": "Project Brief",
            "doc_type": "project-brief",
            "last_modified_commit": "",
        },
        "distance": 0.0,
        "score": 1.2,
        "score_reasons": ["brief_boost", "overview_context"],
    }


def build_answer_context(
    workspace: Path,
    question: str,
    candidates: list[dict],
    plan: RetrievalPlan,
) -> list[dict]:
    ranked = rerank_results(question, candidates, plan)
    selected: list[dict] = []
    if plan.include_brief:
        brief = load_project_brief_context(workspace)
        if brief:
            selected.append(brief)
        selected.extend(load_overview_chunks(workspace, limit=plan.final_limit))
    selected.extend(ranked)
    return dedupe_by_source(selected)[: plan.final_limit]


def retrieve_lexical_candidates(workspace: Path, question: str, limit: int = 24) -> list[dict]:
    chunks = load_chunk_artifact(workspace)
    if not chunks:
        return []

    query_terms = extract_query_terms(question)
    scored = []
    for order, chunk in enumerate(chunks):
        score, reasons = score_lexical_candidate(chunk, query_terms)
        if score <= 0:
            continue
        metadata = chunk.get("metadata", {}) or {}
        scored.append(
            {
                "id": chunk.get("id"),
                "text": chunk.get("text", ""),
                "metadata": metadata,
                "distance": None,
                "lexical_score": score,
                "score": score,
                "score_reasons": reasons,
                "source": "lexical",
                "_order": order,
            }
        )

    scored.sort(key=lambda item: (item["lexical_score"], -int(item["_order"])), reverse=True)
    return scored[:limit]


def load_chunk_artifact(workspace: Path) -> list[dict]:
    path = workspace / ".repo-intel" / "artifacts" / "chunks.json"
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def score_lexical_candidate(chunk: dict, query_terms: dict[str, list[str]]) -> tuple[float, list[str]]:
    metadata = chunk.get("metadata", {}) or {}
    path = normalize(str(metadata.get("path", "")))
    section = normalize(str(metadata.get("section", "")))
    heading = normalize(str(metadata.get("heading_path", "")))
    doc_type = normalize(str(metadata.get("doc_type", "")))
    tags = normalize(str(metadata.get("tags", "")))
    text = normalize(str(chunk.get("text", "")))

    weighted_fields = [
        (path, 0.28, "path"),
        (section, 0.34, "section"),
        (heading, 0.28, "heading"),
        (doc_type, 0.1, "doc_type"),
        (tags, 0.1, "tags"),
        (text, 0.18, "text"),
    ]

    score = 0.0
    reasons: list[str] = []
    for phrase in query_terms["phrases"]:
        matches = [name for value, _, name in weighted_fields if phrase in value]
        if matches:
            boost = 0.45 + sum(weight for value, weight, _ in weighted_fields if phrase in value)
            score += boost
            reasons.append(f"phrase:{phrase}@{','.join(matches[:3])}")

    for keyword in query_terms["keywords"]:
        matches = [name for value, _, name in weighted_fields if contains_query_term(value, keyword)]
        if matches:
            boost = sum(
                weight for value, weight, _ in weighted_fields if contains_query_term(value, keyword)
            )
            score += boost
            reasons.append(f"keyword:{keyword}@{','.join(matches[:3])}")

    matched_keywords = {
        keyword
        for keyword in query_terms["keywords"]
        if any(contains_query_term(value, keyword) for value, _, _ in weighted_fields)
    }
    if len(matched_keywords) >= 2:
        score += min(0.3, len(matched_keywords) * 0.06)
        reasons.append(f"coverage={len(matched_keywords)}")

    if score and is_structural_doc_path(path):
        score += 0.15
        reasons.append("structural_doc")

    return (round(score, 4), reasons)


def merge_candidates(semantic_candidates: list[dict], lexical_candidates: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for item in semantic_candidates:
        item_id = str(item.get("id", ""))
        enriched = dict(item)
        enriched.setdefault("source", "semantic")
        merged[item_id] = enriched

    for item in lexical_candidates:
        item_id = str(item.get("id", ""))
        if item_id in merged:
            current = merged[item_id]
            current["lexical_score"] = max(
                float(current.get("lexical_score", 0.0) or 0.0),
                float(item.get("lexical_score", 0.0) or 0.0),
            )
            current["source"] = "hybrid"
            current["score_reasons"] = list(current.get("score_reasons", [])) + list(
                item.get("score_reasons", [])
            )
            continue
        merged[item_id] = item
    return list(merged.values())


def load_overview_chunks(workspace: Path, limit: int) -> list[dict]:
    chunks = load_chunk_artifact(workspace)

    results = []
    for order, chunk in enumerate(chunks):
        metadata = chunk.get("metadata", {})
        source_path = normalize(str(metadata.get("path", "")))
        doc_type = normalize(str(metadata.get("doc_type", "")))
        if not is_overview_source(source_path, doc_type):
            continue
        results.append(
            {
                "id": chunk.get("id"),
                "text": chunk.get("text", ""),
                "metadata": metadata,
                "distance": 0.0,
                "score": 1.0,
                "score_reasons": ["deterministic_overview_source"],
                "_order": order,
            }
        )

    results.sort(key=overview_chunk_priority)
    return results[:limit]


def overview_chunk_priority(result: dict) -> tuple[int, str]:
    metadata = result.get("metadata", {})
    path = normalize(str(metadata.get("path", "")))
    order = int(result.get("_order", 0))
    if path == "product.md":
        return (0, f"{order:08d}")
    if path == "readme.md":
        return (1, f"{order:08d}")
    if path == "ai_index.md":
        return (2, f"{order:08d}")
    if path == "agent_start_here.md":
        return (3, f"{order:08d}")
    if "00-overview" in path:
        return (4, f"{order:08d}")
    return (10, path)


def write_answer_plan_debug(
    workspace: Path,
    question: str,
    plan: RetrievalPlan,
    candidates: list[dict],
    selected: list[dict],
    semantic_candidates: list[dict] | None = None,
    lexical_candidates: list[dict] | None = None,
    cache_hit: bool = False,
    cache_id: str | None = None,
) -> None:
    artifact_dir = workspace / ".repo-intel" / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "question": question,
        "intent": {
            "name": plan.intent.name,
            "confidence": plan.intent.confidence,
            "signals": plan.intent.signals,
        },
        "candidate_limit": plan.candidate_limit,
        "final_limit": plan.final_limit,
        "include_brief": plan.include_brief,
        "cache_hit": cache_hit,
        "cache_id": cache_id,
        "semantic_candidates": [debug_result(item) for item in semantic_candidates or []],
        "lexical_candidates": [debug_result(item) for item in lexical_candidates or []],
        "candidates": [debug_result(item) for item in candidates],
        "selected": [debug_result(item) for item in selected],
    }
    (artifact_dir / "last-answer-plan.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def debug_result(result: dict) -> dict[str, Any]:
    metadata = result.get("metadata", {})
    return {
        "id": result.get("id"),
        "repo": metadata.get("repo", ""),
        "path": metadata.get("path", ""),
        "section": metadata.get("section", ""),
        "doc_type": metadata.get("doc_type", ""),
        "distance": result.get("distance"),
        "lexical_score": result.get("lexical_score"),
        "source": result.get("source"),
        "score": result.get("score"),
        "score_reasons": result.get("score_reasons", []),
    }


def dedupe_by_source(results: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    deduped = []
    for result in results:
        metadata = result.get("metadata", {})
        key = (
            str(metadata.get("repo", "")),
            str(metadata.get("path", "")),
            str(metadata.get("section", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def is_overview_source(path: str, doc_type: str) -> bool:
    return doc_type in {"readme", "product", "ai-index", "agent-guide", "overview"} or any(
        term in path for term in OVERVIEW_PATH_TERMS
    )


def is_structural_doc_path(path: str) -> bool:
    return any(
        term in path
        for term in {
            "00-overview",
            "01-architecture",
            "02-architecture",
            "02-bounded",
            "03-domain",
            "04-application",
            "05-integration",
            "06-api",
            "11-roadmap",
            "architecture",
            "adr",
            "handoff",
            "roadmap",
            "implementation",
            "plan",
        }
    )


def is_low_value_doc_for_intent(path: str, doc_type: str) -> bool:
    if doc_type in {"qa"}:
        return True
    return "/test_cases/" in path or "/roles/" in path or "qa" in path


def extract_query_terms(question: str) -> dict[str, list[str]]:
    keywords = extract_keywords(question)
    phrases = extract_phrases(keywords)
    return {"keywords": keywords, "phrases": phrases}


def extract_phrases(keywords: list[str]) -> list[str]:
    phrases: list[str] = []
    for size in (3, 2):
        for start in range(0, max(0, len(keywords) - size + 1)):
            phrase = " ".join(keywords[start : start + size])
            if phrase not in phrases:
                phrases.append(phrase)
    return phrases


def extract_keywords(question: str) -> list[str]:
    text = normalize(question)
    words = re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text)
    stopwords = {
        "como",
        "cual",
        "cuales",
        "donde",
        "para",
        "sobre",
        "este",
        "esta",
        "estos",
        "estas",
        "funciona",
        "explica",
        "proyecto",
        "proxima",
        "que",
        "qué",
        "una",
        "uno",
        "los",
        "las",
        "del",
        "rol",
        "cumple",
        "usan",
        "usa",
        "uso",
        "con",
        "sin",
        "and",
        "the",
        "what",
        "how",
        "why",
        "when",
        "where",
        "does",
        "work",
        "works",
        "explain",
    }
    keywords: list[str] = []
    for word in words:
        if word in stopwords or word in keywords:
            continue
        keywords.append(word)
    return keywords


def contains_query_term(value: str, term: str) -> bool:
    if not term:
        return False
    if len(term) > 4 and ("-" in term or "_" in term):
        return term in value
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", value) is not None


def normalize(value: str) -> str:
    value = value.lower()
    value = "".join(
        char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char)
    )
    return value
