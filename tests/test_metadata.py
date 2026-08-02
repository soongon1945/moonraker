from __future__ import annotations

import base64
import builtins
import errno
import os
from pathlib import Path
from typing import Any

import pytest

from moonraker.components.file_manager.metadata import BaseSlicer


def test_read_only_thumbnail_cache_is_nonfatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = base64.b64encode(b"thumbnail-data").decode()
    gcode = (
        f"; thumbnail begin 48x48 {len(payload)}\n"
        f"; {payload}\n"
        "; thumbnail end\n"
    )
    gcode_path = tmp_path.joinpath("model.gcode")
    thumb_dir = tmp_path.joinpath(".thumbs")
    thumb_dir.mkdir()
    real_open = builtins.open

    def open_read_only(
        path: Any,
        mode: str = "r",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if mode == "wb" and Path(os.fspath(path)).parent == thumb_dir:
            raise OSError(
                errno.EROFS,
                "Read-only file system",
                os.fspath(path),
            )
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", open_read_only)
    slicer = BaseSlicer(str(gcode_path), len(gcode), gcode)

    assert slicer.parse_thumbnails() is None
