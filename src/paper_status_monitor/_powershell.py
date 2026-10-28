"""Run Windows PowerShell scripts without a console window (Windows only).

Values are passed to the scripts through environment variables, never interpolated
into the script text, so they need no escaping.
"""

from __future__ import annotations

import base64
import os
import subprocess
from collections.abc import Mapping


class PowerShellError(RuntimeError):
    """PowerShell could not be started or the script failed."""


def run_script(
    script: str, variables: Mapping[str, str] | None = None, *, timeout: float | None = None
) -> str:
    """Run *script* with ``powershell.exe`` and return its standard output.

    Args:
        script: PowerShell code; it reads its inputs as ``$env:NAME``.
        variables: Environment variables added for the script.
        timeout: Seconds to wait for the script (``None`` = no limit).

    Raises:
        PowerShellError: If PowerShell cannot be started, times out or fails.
    """
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    environment = {**os.environ, **(variables or {})}
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise PowerShellError(f"PowerShell did not finish within {timeout} seconds.") from exc
    except OSError as exc:
        raise PowerShellError(f"Could not run PowerShell: {exc}") from exc
    if completed.returncode != 0:
        message = (completed.stderr or "").strip()
        raise PowerShellError(message or f"PowerShell exited with code {completed.returncode}")
    return completed.stdout or ""
