import os
from pathlib import Path
import subprocess

import pytest

from server.tools.api import file_read_tool


def test_read_local_file_rejects_symlink_that_escapes_allowed_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "outside-secret.txt"
    secret.write_text("outside secret", encoding="utf-8")
    link = allowed / "linked-outside"
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            check=True,
            capture_output=True,
        )
    else:
        link.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(file_read_tool, "ALLOWED_BASE", str(allowed))

    result = file_read_tool.read_local_file.invoke(
        {"file_path": str(link / "outside-secret.txt")}
    )

    assert result.startswith("安全限制：")
    assert "outside secret" not in result
