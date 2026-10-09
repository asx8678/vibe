"""The headless `vibe -p` contract, driven as a process against the mock server.

Each test runs the installed `vibe` executable (the Rust TUI's headless mode over
the default Unified Harness runtime) and checks what a caller can observe: the
exit code and the requests the model endpoint received.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.common import run_vibe_headless, write_e2e_config
from tests.e2e.mock_server import ChatCompletionsRequestPayload, StreamingMockServer

pytestmark = [pytest.mark.timeout(90), pytest.mark.usefixtures("setup_e2e_env")]


def _text_reply(
    _request_index: int, _payload: ChatCompletionsRequestPayload
) -> list[dict[str, object]]:
    return [
        StreamingMockServer.build_chunk(
            created=100,
            delta={"role": "assistant", "content": "All done."},
            finish_reason=None,
        ),
        StreamingMockServer.build_chunk(
            created=101,
            delta={},
            finish_reason="stop",
            usage={"prompt_tokens": 3, "completion_tokens": 4},
        ),
    ]


@pytest.mark.parametrize("streaming_mock_server", [_text_reply], indirect=True)
@pytest.mark.parametrize("backend", ["generic", "mistral"])
def test_model_request_carries_the_configured_top_p_and_output_cap(
    streaming_mock_server: StreamingMockServer, e2e_workdir: Path, backend: str
) -> None:
    """*Prepare*: A model configured with `top_p` and `max_output_tokens`, behind
    either backend adapter.
    *Do*: Run `vibe -p`.
    *Assert*: The model request carries both values.
    """
    # Prepare
    write_e2e_config(
        Path(os.environ["VIBE_HOME"]),
        streaming_mock_server.api_base,
        backend=backend,
        model_settings=["top_p = 0.9", "max_output_tokens = 123"],
    )

    # Do
    result = run_vibe_headless(e2e_workdir, ["-p", "hello"])

    # Assert
    assert result.returncode == 0, result.stderr
    request: dict[str, Any] = dict(streaming_mock_server.requests[0])
    assert request["top_p"] == 0.9
    assert request["max_tokens"] == 123
