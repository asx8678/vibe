from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import re
import subprocess
import sys

VIBE_EXECUTABLE = str(Path(sys.executable).with_name("vibe"))


def run_vibe_headless(
    workdir: Path, args: Sequence[str], *, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the installed `vibe` in `workdir` to completion, as a caller would."""
    return subprocess.run(
        [VIBE_EXECUTABLE, "--workdir", str(workdir), *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
        env=os.environ.copy(),
        check=False,
    )


def ansi_tolerant_pattern(text: str) -> re.Pattern[str]:
    ansi = r"(?:\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\r|\n)*"
    return re.compile(ansi.join(re.escape(char) for char in text))


def write_e2e_config(
    vibe_home: Path,
    api_base: str,
    *,
    provider_name: str = "mock-provider",
    backend: str = "generic",
    settings: Sequence[str] = (),
    model_settings: Sequence[str] = (),
) -> None:
    """Write a config routing `mock-model` to `api_base`.

    `settings` are extra top-level TOML lines; `model_settings` are extra lines
    of the `mock-model` table.
    """
    vibe_home.mkdir(parents=True, exist_ok=True)
    (vibe_home / "config.toml").write_text(
        "\n".join([
            'active_model = "mock-model"',
            "enable_update_checks = false",
            "disable_welcome_banner_animation = true",
            *settings,
            "",
            "[[providers]]",
            f'name = "{provider_name}"',
            f'api_base = "{api_base}"',
            'api_key_env_var = "MISTRAL_API_KEY"',
            f'backend = "{backend}"',
            "",
            "[[models]]",
            'name = "mock-model"',
            f'provider = "{provider_name}"',
            'alias = "mock-model"',
            *model_settings,
        ]),
        encoding="utf-8",
    )


# Waiting on the backend must always drain the child, never just sleep on the
# predicate. Textual's writer thread has a 30-slot queue and blocks on a full one, so
# a pty nobody reads eventually stalls the app's event loop: it stops handling input,
# never dispatches the turn, and the request the caller is waiting for never arrives.
# The startup burst alone is ~26KB against a 64KB Linux pty buffer.
