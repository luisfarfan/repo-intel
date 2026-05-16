from __future__ import annotations

from pathlib import Path

from repo_intel.core.models import DocumentInfo, Evidence, Relationship, RepoInfo


def build_relationships(repos: list[RepoInfo], docs: list[DocumentInfo]) -> list[Relationship]:
    relationships: list[Relationship] = []

    for doc in docs:
        if doc.repo_id:
            relationships.append(
                Relationship(
                    source=doc.repo_id,
                    target=doc.id,
                    kind="has_document",
                    confidence=1.0,
                    evidence=[Evidence(source=doc.path, reason="document is inside repository path")],
                )
            )

    relationships.extend(infer_repo_relationships(repos, docs))
    return dedupe_relationships(relationships)


def infer_repo_relationships(repos: list[RepoInfo], docs: list[DocumentInfo]) -> list[Relationship]:
    relationships: list[Relationship] = []
    by_id = {repo.id: repo for repo in repos}

    for source in repos:
        source_docs = [doc for doc in docs if doc.repo_id == source.id]
        doc_text = " ".join(Path(doc.relative_path).name.lower() for doc in source_docs)
        source_tokens = repo_tokens(source)

        for target in repos:
            if source.id == target.id:
                continue
            target_name = target.name.lower()
            target_tokens = repo_tokens(target)
            shared_domains = sorted(set(source.domains) & set(target.domains))

            if target_name in doc_text:
                relationships.append(
                    Relationship(
                        source=source.id,
                        target=target.id,
                        kind="mentions_repo",
                        confidence=0.72,
                        evidence=[
                            Evidence(
                                source=source.path,
                                reason=f"document filenames or paths mention {target.name}",
                            )
                        ],
                    )
                )

            if shared_domains:
                relationships.append(
                    Relationship(
                        source=source.id,
                        target=target.id,
                        kind="shares_domain",
                        confidence=0.55,
                        evidence=[
                            Evidence(
                                source=f"{source.path} -> {target.path}",
                                reason=f"shared domains: {', '.join(shared_domains)}",
                            )
                        ],
                    )
                )

            if source_tokens & target_tokens:
                shared = sorted(source_tokens & target_tokens)
                if shared and shared != ["proxima"]:
                    relationships.append(
                        Relationship(
                            source=source.id,
                            target=target.id,
                            kind="name_affinity",
                            confidence=0.45,
                            evidence=[
                                Evidence(
                                    source=f"{source.name} -> {target.name}",
                                    reason=f"shared name tokens: {', '.join(shared)}",
                                )
                            ],
                        )
                    )

    # Specific deterministic architecture hints from common stack pairings.
    frontend_repos = [
        repo
        for repo in repos
        if any(stack.name in {"Angular", "React", "Astro", "Next.js"} for stack in repo.stacks)
    ]
    api_repos = [
        repo
        for repo in repos
        if any(stack.name in {"FastAPI", "NestJS"} for stack in repo.stacks) or "api" in repo.domains
    ]
    for frontend in frontend_repos:
        for api in api_repos:
            if frontend.id == api.id:
                continue
            relationships.append(
                Relationship(
                    source=frontend.id,
                    target=api.id,
                    kind="likely_consumes_api",
                    confidence=0.5,
                    evidence=[
                        Evidence(
                            source=f"{frontend.path} -> {api.path}",
                            reason="frontend stack paired with API/backend stack",
                        )
                    ],
                )
            )

    return [rel for rel in relationships if rel.source in by_id and rel.target in by_id]


def repo_tokens(repo: RepoInfo) -> set[str]:
    return {token for token in repo.name.lower().replace("_", "-").split("-") if token}


def dedupe_relationships(relationships: list[Relationship]) -> list[Relationship]:
    deduped: dict[tuple[str, str, str], Relationship] = {}
    for relationship in relationships:
        key = (relationship.source, relationship.target, relationship.kind)
        current = deduped.get(key)
        if current is None or relationship.confidence > current.confidence:
            deduped[key] = relationship
    return sorted(deduped.values(), key=lambda item: (item.kind, item.source, item.target))


def build_graph_json(repos: list[RepoInfo], docs: list[DocumentInfo], relationships: list[Relationship]) -> dict:
    nodes = []
    for repo in repos:
        nodes.append(
            {
                "id": repo.id,
                "type": "repo",
                "label": repo.name,
                "path": repo.relative_path,
                "stacks": [stack.name for stack in repo.stacks],
                "domains": repo.domains,
            }
        )
    for doc in docs:
        nodes.append(
            {
                "id": doc.id,
                "type": "document",
                "label": doc.title,
                "path": doc.relative_path,
                "doc_type": doc.doc_type,
                "tags": doc.tags,
            }
        )
    edges = [
        {
            "source": relationship.source,
            "target": relationship.target,
            "kind": relationship.kind,
            "confidence": relationship.confidence,
            "method": relationship.method,
        }
        for relationship in relationships
    ]
    return {"nodes": nodes, "edges": edges}

