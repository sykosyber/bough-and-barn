from pathlib import Path
import subprocess

import pytest

from barn.workspace import GitWorkspaceManager


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "barn@example.test")
    git(repo, "config", "user.name", "Barn Test")
    (repo / "README.md").write_text("base\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    return repo


def test_prepare_creates_deterministic_agent_worktree_and_is_idempotent(git_repo: Path):
    manager = GitWorkspaceManager(git_repo)

    first = manager.prepare(run_id="run:alpha", agent_id="agent/architect", base_ref="HEAD")
    second = manager.prepare(run_id="run:alpha", agent_id="agent/architect", base_ref="HEAD")

    assert first == second
    assert first.path.exists()
    assert first.path.is_dir()
    assert first.branch.startswith("barn/")
    assert git(first.path, "branch", "--show-current") == first.branch
    assert git(first.path, "rev-parse", "HEAD") == git(git_repo, "rev-parse", "HEAD")
    exclude = Path(git(git_repo, "rev-parse", "--git-path", "info/exclude"))
    if not exclude.is_absolute():
        exclude = git_repo / exclude
    assert ".barn/" in exclude.read_text()


def test_two_agents_receive_isolated_worktrees_and_branches(git_repo: Path):
    manager = GitWorkspaceManager(git_repo)
    one = manager.prepare(run_id="run-1", agent_id="agent-one")
    two = manager.prepare(run_id="run-1", agent_id="agent-two")

    assert one.path != two.path
    assert one.branch != two.branch

    (one.path / "agent-one.txt").write_text("only one\n")
    assert (one.path / "agent-one.txt").exists()
    assert not (two.path / "agent-one.txt").exists()
    assert not (git_repo / "agent-one.txt").exists()

    status = manager.status(one)
    assert "agent-one.txt" in status.porcelain
    assert status.branch == one.branch
    assert status.head_sha == git(one.path, "rev-parse", "HEAD")
