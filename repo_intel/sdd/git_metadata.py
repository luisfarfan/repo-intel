from __future__ import annotations

from pathlib import Path

from git import InvalidGitRepositoryError, Repo

from repo_intel.domain.models import GitDocumentMetadata


class GitMetadataProvider:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path
        try:
            self.repo = Repo(repo_path, search_parent_directories=False)
        except (InvalidGitRepositoryError, OSError):
            self.repo = None

    def branch(self) -> str | None:
        if not self.repo:
            return None
        try:
            return self.repo.active_branch.name
        except TypeError:
            return None

    def current_commit(self) -> str | None:
        if not self.repo:
            return None
        try:
            return self.repo.head.commit.hexsha
        except ValueError:
            return None

    def status(self) -> str:
        if not self.repo:
            return "no-git"
        try:
            return "dirty" if self.repo.is_dirty(untracked_files=True) else "clean"
        except Exception:
            return "unknown"

    def document_metadata(self, path: Path) -> GitDocumentMetadata:
        current_commit = self.current_commit()
        metadata = GitDocumentMetadata(
            branch=self.branch(),
            commit_hash=current_commit,
        )
        if not self.repo:
            return metadata
        try:
            rel = path.relative_to(self.repo_path).as_posix()
        except ValueError:
            return metadata
        try:
            commits = list(self.repo.iter_commits(paths=rel, max_count=1))
        except Exception:
            commits = []
        if not commits:
            return metadata
        commit = commits[0]
        return GitDocumentMetadata(
            branch=metadata.branch,
            commit_hash=current_commit,
            last_modified_commit=commit.hexsha,
            author=str(commit.author),
            timestamp=commit.authored_datetime.isoformat(),
            commit_message=commit.message.strip().splitlines()[0] if commit.message else "",
        )

