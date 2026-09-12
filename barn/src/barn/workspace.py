from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import subprocess


class GitWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitWorkspace:
    repo_root: Path
    path: Path
    branch: str
    run_id: str
    agent_id: str


@dataclass(frozen=True)
class GitWorkspaceStatus:
    branch: str
    head_sha: str
    porcelain: str


class GitWorkspaceManager:
    def __init__(self, repo_root: str | Path, workspace_root: str | Path | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        if not self.repo_root.exists():
            raise GitWorkspaceError(f"repository path does not exist: {self.repo_root}")
        try:
            top = self._git("rev-parse", "--show-toplevel")
        except GitWorkspaceError as exc:
            raise GitWorkspaceError(f"not a git repository: {self.repo_root}") from exc
        self.repo_root = Path(top).resolve()
        self.workspace_root = (
            Path(workspace_root).resolve()
            if workspace_root is not None
            else self.repo_root / ".barn" / "worktrees"
        )

    def prepare(self, *, run_id: str, agent_id: str, base_ref: str = "HEAD") -> GitWorkspace:
        run_slug = _slug(run_id)
        agent_slug = _slug(agent_id)
        branch = f"barn/{run_slug}/{agent_slug}"
        path = self.workspace_root / run_slug / agent_slug
        workspace = GitWorkspace(
            repo_root=self.repo_root,
            path=path,
            branch=branch,
            run_id=run_id,
            agent_id=agent_id,
        )

        if path.exists():
            current = self._git_at(path, "branch", "--show-current")
            if current != branch:
                raise GitWorkspaceError(
                    f"workspace path already exists on unexpected branch: {path} ({current})"
                )
            return workspace

        self._ensure_internal_workspace_ignored()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._git("worktree", "prune")

        branch_exists = self._run_git(
            self.repo_root,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
            check=False,
        ).returncode == 0
        if branch_exists:
            self._git("worktree", "add", str(path), branch)
        else:
            self._git("worktree", "add", "-b", branch, str(path), base_ref)
        return workspace

    def status(self, workspace: GitWorkspace) -> GitWorkspaceStatus:
        if workspace.repo_root.resolve() != self.repo_root:
            raise GitWorkspaceError("workspace belongs to a different repository")
        if not workspace.path.exists():
            raise GitWorkspaceError(f"workspace missing: {workspace.path}")
        branch = self._git_at(workspace.path, "branch", "--show-current")
        head_sha = self._git_at(workspace.path, "rev-parse", "HEAD")
        porcelain = self._git_at(workspace.path, "status", "--porcelain=v1", "--untracked-files=all")
        return GitWorkspaceStatus(branch=branch, head_sha=head_sha, porcelain=porcelain)

    def _ensure_internal_workspace_ignored(self) -> None:
        # `info/exclude` is host-local and avoids editing a user's project .gitignore.
        raw_path = self._git("rev-parse", "--git-path", "info/exclude")
        exclude_path = Path(raw_path)
        if not exclude_path.is_absolute():
            exclude_path = self.repo_root / exclude_path
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        text = exclude_path.read_text() if exclude_path.exists() else ""
        lines = {line.strip() for line in text.splitlines()}
        if ".barn/" not in lines:
            with exclude_path.open("a", encoding="utf-8") as handle:
                if text and not text.endswith("\n"):
                    handle.write("\n")
                handle.write(".barn/\n")

    def _git(self, *args: str) -> str:
        return self._git_at(self.repo_root, *args)

    def _git_at(self, cwd: Path, *args: str) -> str:
        return self._run_git(cwd, *args).stdout.strip()

    @staticmethod
    def _run_git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(cwd), *args],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise GitWorkspaceError(f"unable to execute git: {exc}") from exc
        if check and result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "git command failed"
            raise GitWorkspaceError(message)
        return result


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "id"
    normalized = normalized[:32]
    digest = sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{normalized}-{digest}"
