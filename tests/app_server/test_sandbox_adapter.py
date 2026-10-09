"""Sessions whose workspace lives behind a Sandbox Adapter.

The adapter here runs every command in a real subprocess and reads files from
disk, so a sandboxed session and a host session over the same directory must
see the same workspace. What differs is the path the data takes, which the
adapter records.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from typing import Any

import pytest

pytest.importorskip("mistralai_vibe_local_harness.vibe")

from mistralai_vibe_local_harness.protocol import (
    RustHookToolCall,
    RustPostToolCallHookInput,
    RustPostToolCallHookResult,
    RustRuntimeBuiltinToolCall,
    RustRuntimeBuiltinToolName,
    RustTextContentBlock,
    RustToolSuccessResult,
)
from mistralai_vibe_local_harness.vibe import HookContext, LocalRuntimeAdapterConfig
from tests.stubs.local_sandbox import SUB_DOC, RecordingSandbox, build_trusted_project
from vibe.app_server._agents_md_hooks import agents_md_hook
from vibe.app_server._runtime import HarnessProcess
from vibe.app_server.run_export import HeadlessUsageError
from vibe.core.config.harness_files import HarnessFilesManager

pytestmark = [
    # Whole sessions with subprocess tools: slower than a unit test under load.
    pytest.mark.timeout(60),
    pytest.mark.skipif(
        sys.platform == "win32", reason="the sandbox runs POSIX command lines"
    ),
]


# Each task's tool calls, in order, before its final answer. The parent reads
# with a direct call, whose result the AGENTS.md hook extends.


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return build_trusted_project(tmp_path / "project", monkeypatch)


def test_a_sandboxed_session_never_loads_project_files(tmp_path: Path) -> None:
    """*Prepare*: Project config, skills and hooks would come from the host's disk.
    *Do*: Build a sandboxed harness process that asks for them, and one on the legacy harness.
    *Assert*: Both are refused.
    """
    sandbox = RecordingSandbox(tmp_path)

    with pytest.raises(HeadlessUsageError, match="cannot load project files"):
        HarnessProcess(
            HarnessFilesManager(sources=("user", "project")),
            experimental_harness=True,
            sandbox=sandbox,
        )
    with pytest.raises(HeadlessUsageError, match="requires the Unified Harness"):
        HarnessProcess(legacy_harness=True, sandbox=sandbox)


@pytest.mark.asyncio
async def test_the_agents_md_hook_reads_subdirectory_docs_through_the_adapter(
    project: Path,
) -> None:
    """*Prepare*: The AGENTS.md hook on a host session and on a sandboxed one.
    *Do*: Read a file in a subdirectory twice in each session.
    *Assert*: Both append the same doc once, and the sandboxed one read it through the adapter.
    """
    # Prepare
    sandbox = RecordingSandbox(project)
    hook = agents_md_hook(HarnessFilesManager(sources=("user", "project")))
    host = LocalRuntimeAdapterConfig.at(cwd=project, roots=(project,))
    sandboxed = LocalRuntimeAdapterConfig.at(
        cwd=project, roots=(project,), sandbox=sandbox
    )

    # Do
    results = []
    for session_id, config in (("host", host), ("sandbox", sandboxed)):
        context = HookContext(config=config, messages=(), session_id=session_id)
        for _ in range(2):
            result = await hook(_read_input("sub/notes.txt"), context)
            results.append([
                block.text
                for block in result.output.tool_result.content
                if isinstance(block, RustTextContentBlock)
            ])

    # Assert
    host_first, host_second, sandbox_first, sandbox_second = results
    assert sandbox_first == host_first
    assert SUB_DOC in sandbox_first[-1]
    assert host_second == sandbox_second == ["first note"]
    assert sandbox.reads == [str(project / "sub" / "AGENTS.md")]


@pytest.mark.parametrize(
    ("write_tool", "write_arguments"),
    [
        (
            "file_system.write_file",
            {"path": "pkg/mod/AGENTS.md", "content": "# Module rules"},
        ),
        (
            "file_system.search_replace",
            {
                "file_path": "pkg/mod/AGENTS.md",
                "content": [{"old_str": "", "new_str": "# Module rules"}],
            },
        ),
    ],
    ids=["write_file", "search_replace"],
)
@pytest.mark.asyncio
async def test_the_agents_md_hook_looks_in_each_sandbox_directory_once(
    project: Path,
    write_tool: RustRuntimeBuiltinToolName,
    write_arguments: dict[str, Any],
) -> None:
    """*Prepare*: A sandboxed session over a tree with no AGENTS.md below its root.
    *Do*: Read files in it repeatedly, between Vibe's own writes of AGENTS.md
    files and bash commands, one naming AGENTS.md.
    *Assert*: The sandbox is asked for each directory's doc once, and again
    only after a write of that doc or a command naming one; the docs written
    are appended.
    """
    # Prepare
    deep = project / "pkg" / "mod"
    deep.mkdir(parents=True)
    for name in ("a.py", "b.py"):
        (deep / name).write_text("x\n", encoding="utf-8")
    sandbox = RecordingSandbox(project)
    hook = agents_md_hook(HarnessFilesManager(sources=("user",)))
    config = LocalRuntimeAdapterConfig.at(
        cwd=project, roots=(project,), sandbox=sandbox
    )
    context = HookContext(config=config, messages=(), session_id="sandbox")
    pkg_doc, mod_doc = str(project / "pkg" / "AGENTS.md"), str(deep / "AGENTS.md")

    # Do
    for read in ("pkg/mod/a.py", "pkg/mod/b.py", "pkg/mod/a.py", "pkg/x.py"):
        assert _appended(await hook(_read_input(read), context)) == []
    first_lookups = list(sandbox.reads)
    (deep / "AGENTS.md").write_text("# Module rules", encoding="utf-8")
    await hook(_call_input(write_tool, write_arguments), context)
    after_write = _appended(await hook(_read_input("pkg/mod/a.py"), context))
    lookups_after_write = sandbox.reads[len(first_lookups) :]
    await hook(_call_input("file_system.bash", {"command": "ls pkg"}), context)
    await hook(_read_input("pkg/mod/b.py"), context)
    lookups_after_other_command = sandbox.reads[
        len(first_lookups) + len(lookups_after_write) :
    ]
    (project / "pkg" / "AGENTS.md").write_text("# Package rules", encoding="utf-8")
    await hook(
        _call_input(
            "file_system.bash", {"command": "echo '# Package rules' > pkg/AGENTS.md"}
        ),
        context,
    )
    seen = len(sandbox.reads)
    after_command = _appended(await hook(_read_input("pkg/mod/b.py"), context))
    lookups_after_command = sandbox.reads[seen:]

    # Assert
    assert sorted(first_lookups) == [pkg_doc, mod_doc]
    assert lookups_after_write == [mod_doc]
    assert len(after_write) == 1 and "# Module rules" in after_write[0]
    assert lookups_after_other_command == []
    assert sorted(lookups_after_command) == [pkg_doc, mod_doc]
    assert len(after_command) == 1 and "# Package rules" in after_command[0]
    assert "# Module rules" not in after_command[0]


class _HeldReadsSandbox(RecordingSandbox):
    """A Recording Sandbox whose file reads answer only once ``release`` is
    set, with the file as it was when they were asked.
    """

    def __init__(self, workspace: Path) -> None:
        super().__init__(workspace)
        self.release = asyncio.Event()
        self.waiting = asyncio.Event()

    async def read_file(self, path: str, max_bytes: int) -> bytes | None:
        content = await super().read_file(path, max_bytes)
        self.waiting.set()
        await self.release.wait()
        return content


class _FailingReadsSandbox(RecordingSandbox):
    """A Recording Sandbox whose first file read fails."""

    def __init__(self, workspace: Path) -> None:
        super().__init__(workspace)
        self.failed = False

    async def read_file(self, path: str, max_bytes: int) -> bytes | None:
        if not self.failed:
            self.failed = True
            raise ConnectionError("sandbox is gone")
        return await super().read_file(path, max_bytes)


@pytest.mark.asyncio
async def test_a_doc_written_while_its_directory_is_read_is_looked_up_again(
    project: Path,
) -> None:
    """*Prepare*: A sandboxed session over a tree with no AGENTS.md below its
    root, whose sandbox holds file reads until released.
    *Do*: Read a file; while the hook waits for the directory's doc, write
    that doc with Vibe's own tool; then release the read and read again.
    *Assert*: The first read, which found no doc, appends none; the second
    looks the directory up again and appends it: the first lookup, back after
    the write, did not mark the directory as checked.
    """
    # Prepare
    (project / "pkg").mkdir()
    (project / "pkg" / "a.py").write_text("x\n", encoding="utf-8")
    sandbox = _HeldReadsSandbox(project)
    hook = agents_md_hook(HarnessFilesManager(sources=("user",)))
    config = LocalRuntimeAdapterConfig.at(
        cwd=project, roots=(project,), sandbox=sandbox
    )
    context = HookContext(config=config, messages=(), session_id="sandbox")
    doc = project / "pkg" / "AGENTS.md"

    # Do
    first = asyncio.ensure_future(hook(_read_input("pkg/a.py"), context))
    await sandbox.waiting.wait()
    doc.write_text("# Package rules", encoding="utf-8")
    await hook(
        _call_input(
            "file_system.write_file",
            {"path": "pkg/AGENTS.md", "content": "# Package rules"},
        ),
        context,
    )
    sandbox.release.set()
    first_appended = _appended(await first)
    second_appended = _appended(await hook(_read_input("pkg/a.py"), context))

    # Assert
    assert sandbox.reads == [str(doc), str(doc)]
    assert first_appended == []
    assert len(second_appended) == 1 and "# Package rules" in second_appended[0]


@pytest.mark.asyncio
async def test_a_directory_whose_doc_read_failed_is_looked_up_again(
    project: Path,
) -> None:
    """*Prepare*: A sandboxed session over a tree with an AGENTS.md below its
    root, whose sandbox fails the first file read.
    *Do*: Read a file in that directory twice.
    *Assert*: The second read looks the directory up again and appends its
    doc: the failed lookup did not mark it as checked.
    """
    # Prepare
    (project / "pkg").mkdir()
    (project / "pkg" / "a.py").write_text("x\n", encoding="utf-8")
    (project / "pkg" / "AGENTS.md").write_text("# Package rules", encoding="utf-8")
    sandbox = _FailingReadsSandbox(project)
    hook = agents_md_hook(HarnessFilesManager(sources=("user",)))
    config = LocalRuntimeAdapterConfig.at(
        cwd=project, roots=(project,), sandbox=sandbox
    )
    context = HookContext(config=config, messages=(), session_id="sandbox")

    # Do
    first = _appended(await hook(_read_input("pkg/a.py"), context))
    second = _appended(await hook(_read_input("pkg/a.py"), context))

    # Assert
    assert first == []
    assert len(second) == 1 and "# Package rules" in second[0]


def _read_input(path: str) -> RustPostToolCallHookInput:
    return _call_input("file_system.read_file", {"path": path})


def _call_input(
    name: RustRuntimeBuiltinToolName, arguments: dict[str, Any]
) -> RustPostToolCallHookInput:
    return RustPostToolCallHookInput(
        tool_call=RustHookToolCall(
            action_id="action-1",
            call_id="call-1",
            call=RustRuntimeBuiltinToolCall(name=name, arguments=arguments),
        ),
        tool_result=RustToolSuccessResult(
            content=[RustTextContentBlock(text="first note")]
        ),
    )


def _appended(result: RustPostToolCallHookResult) -> list[str]:
    return [
        block.text
        for block in result.output.tool_result.content[1:]
        if isinstance(block, RustTextContentBlock)
    ]
