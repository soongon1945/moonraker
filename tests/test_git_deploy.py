import pytest

from moonraker.components.update_manager.git_deploy import (
    _is_china_timezone,
    _select_update_remote,
)


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
    "timezone, remotes, tracked_remote, expected",
    [
        ("Asia/Shanghai", ["origin", "gitee"], "origin", "gitee"),
        ("Asia/Shanghai", ["origin"], "origin", "origin"),
        ("America/Chicago", ["origin", "gitee"], "origin", "origin"),
        ("Asia/Shanghai", ["upstream"], "upstream", "upstream"),
    ],
)
def test_select_update_remote(
        timezone, remotes, tracked_remote, expected
):
    assert _select_update_remote(
        timezone, remotes, tracked_remote
    ) == expected
