from pathlib import Path

import pytest

from moonraker.components.update_manager import git_deploy
from moonraker.components.update_manager.git_deploy import (
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
