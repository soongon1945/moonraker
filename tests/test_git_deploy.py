import asyncio
from pathlib import Path
from types import SimpleNamespace

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

# Unit tests for the update_manager git_repo deployment helper
#
# Copyright (C) 2026  Aleksei Sviridkin <f@lex.la>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock
from moonraker.components.update_manager.git_deploy import GitRepo


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

