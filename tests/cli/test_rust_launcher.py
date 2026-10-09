from __future__ import annotations

import pytest

import vibe.cli.launcher as launcher


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["some", "args"],
        ["-c"],
        ["update"],
        ["--check-upgrade"],
        ["--setup"],
        ["--", "update"],
        ["--prompt", "update"],
        ["--prompt=--check-upgrade"],
        ["mcp", "list"],
    ],
)
def test_launcher_hands_every_invocation_to_rust(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    # The launcher only rewrites its own process, so the passthrough args reach
    # the Rust binary untouched (a leading bare `update` is rewritten there).
    monkeypatch.setattr("sys.argv", ["vibe", *args])

    called_with: list[list[str]] = []

    def _record_rust(passthrough: list[str]) -> None:
        called_with.append(passthrough)
        raise SystemExit(0)  # os.execvpe never returns in production

    monkeypatch.setattr("vibe.cli._rust.exec_rust_cli", _record_rust)

    with pytest.raises(SystemExit):
        launcher.main()

    assert called_with == [args]


def test_python_selector_no_longer_selects_a_python_tui(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_CLI", "python")
    monkeypatch.setattr("sys.argv", ["vibe"])

    launched: list[list[str]] = []

    def _record_rust(passthrough: list[str]) -> None:
        launched.append(passthrough)
        raise SystemExit(0)

    monkeypatch.setattr("vibe.cli._rust.exec_rust_cli", _record_rust)

    with pytest.raises(SystemExit):
        launcher.main()

    assert launched == [[]]
