# Unit tests for the update_manager git_repo deployment helper
#
# Copyright (C) 2026  Aleksei Sviridkin <f@lex.la>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from moonraker.components.update_manager import git_deploy
from moonraker.components.update_manager.common import Channel
from moonraker.components.update_manager.git_deploy import (
    GitRepo,
    _get_system_timezone,
    _is_china_timezone,
    _is_git_corruption_error,
    _select_update_remote,
)


def test_get_system_timezone_prefers_localtime(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    original_resolve = Path.resolve
    original_read_text = Path.read_text

    def resolve(path, *args, **kwargs):
        if path == Path("/etc/localtime"):
            return Path("/usr/share/zoneinfo/Asia/Shanghai")
        return original_resolve(path, *args, **kwargs)

    def read_text(path, *args, **kwargs):
        if path == Path("/etc/timezone"):
            return "Etc/UTC\n"
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(git_deploy.pathlib.Path, "resolve", resolve)
    monkeypatch.setattr(git_deploy.pathlib.Path, "read_text", read_text)

    assert _get_system_timezone() == "Asia/Shanghai"


@pytest.mark.parametrize(
    "timezone, expected",
    [
        ("Asia/Shanghai", True),
        (":Asia/Urumqi", True),
        ("Asia/Hong_Kong", True),
        ("America/Chicago", False),
        ("UTC", False),
    ],
)
def test_is_china_timezone(timezone, expected):
    assert _is_china_timezone(timezone) is expected


@pytest.mark.parametrize(
    "message, expected",
    [
        (
            "fatal: unable to access repository: Connection reset by peer",
            False,
        ),
        ("fatal: Authentication failed", False),
        ("fatal: ambiguous argument 'gitee/master'", False),
        ("error: object file abc is empty", True),
        ("fatal: loose object abc is corrupt", True),
        ("fatal: bad object HEAD", True),
    ],
)
def test_is_git_corruption_error(message, expected):
    assert _is_git_corruption_error(message) is expected


@pytest.mark.parametrize(
    "timezone, remotes, tracked_remote, remote_branches, branch, expected",
    [
        (
            "Asia/Shanghai", ["origin", "gitee"], "origin",
            None, None, "gitee"
        ),
        (
            "Asia/Shanghai", ["origin", "gitee"], "origin",
            ["origin/master", "gitee/master"], "master", "gitee"
        ),
        (
            "Asia/Shanghai", ["origin", "gitee"], "origin",
            ["origin/master"], "master", "origin"
        ),
        (
            "Asia/Shanghai", ["origin"], "origin",
            None, None, "origin"
        ),
        (
            "America/Chicago", ["origin", "gitee"], "origin",
            None, None, "origin"
        ),
        (
            "Asia/Shanghai", ["upstream"], "upstream",
            None, None, "upstream"
        ),
    ],
)
def test_select_update_remote(
        timezone, remotes, tracked_remote, remote_branches, branch, expected
):
    assert _select_update_remote(
        timezone, remotes, tracked_remote, remote_branches, branch
    ) == expected


def make_repo_for_update_command(channel=Channel.DEV, pinned_commit=None):
    repo = object.__new__(GitRepo)
    repo.channel = channel
    repo.pinned_commit = pinned_commit
    repo.update_remote = "gitee"
    repo.git_branch = "master"
    repo.upstream_commit = "01234567"
    repo.head_detached = False
    repo.git_operation_lock = asyncio.Lock()
    repo.server = SimpleNamespace(is_debug_enabled=lambda: False)
    repo._verify_repo = lambda *args, **kwargs: None
    return repo


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel, pinned_commit, expected_ref",
    [
        (Channel.DEV, None, "master"),
        (Channel.BETA, None, "01234567"),
        (Channel.DEV, "01234567", "01234567"),
    ],
)
async def test_pull_uses_update_remote(channel, pinned_commit, expected_ref):
    repo = make_repo_for_update_command(channel, pinned_commit)
    repo._run_git_cmd_async = AsyncMock()

    await repo.pull()

    repo._run_git_cmd_async.assert_awaited_once_with(
        f"pull gitee {expected_ref} --progress"
    )


@pytest.mark.asyncio
async def test_reset_uses_update_remote():
    repo = make_repo_for_update_command()
    repo._run_git_cmd = AsyncMock()

    await repo.reset()

    repo._run_git_cmd.assert_awaited_once_with(
        "reset --hard gitee/master", attempts=2
    )


@pytest.mark.asyncio
async def test_checkout_uses_update_remote():
    repo = make_repo_for_update_command()
    repo._run_git_cmd = AsyncMock()

    await repo.checkout()

    repo._run_git_cmd.assert_awaited_once_with("checkout -q gitee/master")


@pytest.mark.asyncio
async def test_refresh_selects_current_timezone_before_fetch(monkeypatch):
    repo = object.__new__(GitRepo)
    repo.alias = "moonraker"
    repo.refresh_lock = asyncio.Lock()
    repo.git_messages = []
    repo.git_remote = "origin"
    repo.update_remote = "gitee"
    repo.git_branch = "master"
    repo.rollback_commit = "current"
    repo.rollback_branch = "master"
    repo.commits_behind_count = 0
    repo.repo_corrupt = True
    repo._check_repo_status = AsyncMock(return_value=True)
    repo._verify_repo = lambda *args, **kwargs: None
    repo._find_current_branch = AsyncMock()
    repo._check_moved_origin = AsyncMock(return_value=False)
    repo.list_remote_branches = AsyncMock(
        return_value=["origin/master", "gitee/master"]
    )
    repo.check_diverged = AsyncMock(return_value=False)
    repo.rev_parse = AsyncMock(return_value="current")
    repo.describe = AsyncMock(return_value="v0.0.0-0-g00000000")
    repo._get_upstream_version = AsyncMock(return_value=SimpleNamespace())
    repo._set_versions = AsyncMock()
    repo._check_warnings = lambda: None
    repo.log_repo_info = lambda: None

    async def remote(args="", ignore_errors=False):
        if not args:
            return "origin\ngitee"
        if args == "get-url origin":
            return "https://github.com/example/moonraker.git"
        if args == "get-url gitee":
            return "https://gitee.com/example/moonraker.git"
        raise AssertionError(f"Unexpected remote command: {args}")

    fetched_remotes = []

    async def fetch():
        fetched_remotes.append(repo.update_remote)

    repo.remote = remote
    repo.fetch = fetch
    monkeypatch.setattr(
        git_deploy, "_get_system_timezone", lambda: "America/Chicago"
    )

    await repo.refresh_repo_state()

    # A persisted mirror from the previous timezone must not be fetched before
    # the current timezone has selected the active update remote.
    assert fetched_remotes == ["origin"]


def test_mirror_url_is_not_reported_as_unofficial():
    repo = object.__new__(GitRepo)
    repo.repo_warnings = []
    repo.repo_anomalies = []
    repo.pinned_commit = None
    repo.pinned_commit_valid = True
    repo.valid_git_repo = True
    repo.repo_corrupt = False
    repo.git_branch = repo.primary_branch = "master"
    repo.git_remote = "origin"
    repo.update_remote = "gitee"
    repo.upstream_url = "https://gitee.com/example/moonraker.git"
    repo.origin_url = "https://github.com/example/moonraker.git"
    repo.recovery_url = repo.origin_url
    repo.git_owner = "example"
    repo.git_repo_name = "moonraker"
    repo.untracked_files = []
    repo.diverged = False
    repo.head_detached = False
    version = SimpleNamespace(
        dirty=False, short_version="v1", full_version="v1"
    )
    repo.current_version = version
    repo.upstream_version = version
    repo.rollback_version = version
    repo.current_commit = "current"
    repo.upstream_commit = "upstream"
    repo.commits_behind = []
    repo.commits_behind_count = 0
    repo.git_messages = []
    repo.server = SimpleNamespace(is_debug_enabled=lambda: False)
    repo._generate_warn_msg = lambda: ""

    repo._check_warnings()

    assert not any(
        warning.startswith("Unofficial remote url")
        for warning in repo.repo_anomalies
    )
    status = repo.get_repo_status(rpt_anomalies=True)
    assert status["remote_alias"] == "gitee"
    assert status["remote_url"] == repo.upstream_url


def make_repo(
    branch_lines: list[str],
    remotes: str = "origin",
    tracking_remote: str | None = None,
    git_remote: str = "?",
    git_branch: str = "?",
) -> GitRepo:
    # Build a bare GitRepo without running __init__ and stub the async git
    # helpers that _find_current_branch depends on, so the branch parsing
    # logic can be exercised in isolation.
    repo = GitRepo.__new__(GitRepo)
    repo.alias = "klipper"
    repo.git_remote = git_remote
    repo.git_branch = git_branch
    repo.head_detached = False
    repo.branches = []
    repo.list_branches = AsyncMock(return_value=branch_lines)
    repo.remote = AsyncMock(return_value=remotes)
    repo.config_get = AsyncMock(return_value=tracking_remote)
    return repo


@pytest.mark.asyncio
async def test_find_current_branch_on_branch() -> None:
    repo = make_repo(["* master", "  dev"], tracking_remote="origin")
    await repo._find_current_branch()
    assert repo.head_detached is False
    assert repo.git_branch == "master"
    assert repo.git_remote == "origin"
    assert repo.branches == ["master", "dev"]
    repo.config_get.assert_awaited_once_with("branch.master.remote")


@pytest.mark.asyncio
async def test_find_current_branch_detached_at_remote_branch() -> None:
    # git spells out the remote branch in the ref, so it is recovered.
    repo = make_repo(["* (HEAD detached at origin/master)", "  master"])
    await repo._find_current_branch()
    assert repo.head_detached is True
    assert repo.git_branch == "master"
    assert repo.git_remote == "origin"
    repo.config_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_find_current_branch_detached_at_tag() -> None:
    # A detached checkout on a bare tag carries no remote in the ref.  With no
    # previously tracked remote the value stays "?" -- it is not inferred.
    repo = make_repo(["* (HEAD detached at v0.13.0)", "  master"])
    await repo._find_current_branch()
    assert repo.head_detached is True
    assert repo.git_remote == "?"
    repo.config_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_find_current_branch_no_branch() -> None:
    # git renders some detached states as "(no branch)".  This must be treated
    # as detached, never as a literal branch name (which would build the
    # invalid key "branch.(no branch).remote").
    repo = make_repo(["* (no branch)"])
    await repo._find_current_branch()
    assert repo.head_detached is True
    assert repo.git_remote == "?"
    assert repo.branches == []
    repo.config_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_find_current_branch_no_branch_keeps_previous_tracking() -> None:
    # When a remote/branch was previously detected they are kept, mirroring the
    # existing detached-HEAD behavior.  No inference, no crash.
    repo = make_repo(
        ["* (no branch)"], git_remote="origin", git_branch="master"
    )
    await repo._find_current_branch()
    assert repo.head_detached is True
    assert repo.git_remote == "origin"
    assert repo.git_branch == "master"
    repo.config_get.assert_not_awaited()
