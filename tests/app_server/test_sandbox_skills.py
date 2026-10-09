"""Skills of sessions whose tools run behind a Sandbox Adapter.

The adapter here runs every command in a real subprocess, with the sandbox's
temporary directory pointed at a directory of the test's own, so what a run
copies into the sandbox is on disk to inspect.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys

import pytest

pytest.importorskip("mistralai_vibe_local_harness.vibe")

from tests.stubs.local_sandbox import RecordingSandbox, build_trusted_project
from vibe.app_server._sandbox_skills import SKILLS_DIRNAME, SandboxSkills
from vibe.core.skills.models import SkillInfo

pytestmark = [
    # Whole sessions with subprocess tools: slower than a unit test under load.
    pytest.mark.timeout(60),
    pytest.mark.skipif(
        sys.platform == "win32", reason="the sandbox runs POSIX command lines"
    ),
]

# Only the commands that write a copy carry these: the helper's install
# operation, and the file a large request is streamed into.
_INSTALL_MARKER = " skills-install "
_UPLOAD_MARKERS = (_INSTALL_MARKER, "mistralai-vibe-request-")


@pytest.fixture
def sandbox_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The sandbox's temporary directory, where skills are copied."""
    path = tmp_path / "sandbox-tmp"
    path.mkdir()
    monkeypatch.setenv("TMPDIR", str(path))
    return path


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return build_trusted_project(tmp_path / "project", monkeypatch)


def _uploads(sandbox: RecordingSandbox) -> list[str]:
    return [
        command
        for command in sandbox.commands
        if any(marker in command for marker in _UPLOAD_MARKERS)
    ]


def _copies(sandbox_tmp: Path) -> dict[str, dict[str, bytes]]:
    """Each copy in the sandbox, by digest: its files by relative path."""
    root = sandbox_tmp / SKILLS_DIRNAME
    if not root.is_dir():
        return {}
    return {
        copy.name: {
            path.relative_to(copy).as_posix(): path.read_bytes()
            for path in sorted(copy.rglob("*"))
            if path.is_file()
        }
        for copy in root.iterdir()
    }


def _write_skill(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: The {name} skill.\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return directory


@pytest.mark.asyncio
async def test_a_sandbox_without_skills_of_its_own_needs_no_upload(
    project: Path, sandbox_tmp: Path
) -> None:
    """*Prepare*: No skill to copy, and a project without skills.
    *Do*: Prepare a session.
    *Assert*: One scan, no upload, and no project skill.
    """
    # Prepare
    sandbox = RecordingSandbox(project)

    # Do
    skills = await SandboxSkills(sandbox).prepare_session([], roots=[project])

    # Assert
    assert skills.project_skills == {}
    assert skills.issues == ()
    assert len(sandbox.commands) == 1
    assert _uploads(sandbox) == []


def _host_skill(directory: Path, name: str, *, files: dict[str, bytes]) -> SkillInfo:
    _write_skill(directory, name, f"The {name} body.")
    for relative, content in files.items():
        (directory / relative).parent.mkdir(parents=True, exist_ok=True)
        (directory / relative).write_bytes(content)
    return SkillInfo(
        name=name,
        description=f"The {name} skill.",
        prompt=f"The {name} body.",
        skill_path=directory / "SKILL.md",
    )


@pytest.mark.asyncio
async def test_a_broken_copy_is_replaced_and_an_intact_one_reused(
    tmp_path: Path, project: Path, sandbox_tmp: Path
) -> None:
    """*Prepare*: A skill copied by one process, whose copy is then altered.
    *Do*: Prepare it from a new process, then from a third.
    *Assert*: The second uploads it again and restores the copy; the third
    reuses it.
    """
    # Prepare
    skill = _host_skill(tmp_path / "host" / "notes", "notes", files={"a.txt": b"a"})
    await SandboxSkills(RecordingSandbox(project)).prepare_session([skill], roots=[])
    (digest,) = _copies(sandbox_tmp)
    copy = sandbox_tmp / SKILLS_DIRNAME / digest
    (copy / "a.txt").write_bytes(b"tampered")
    restoring, reusing = RecordingSandbox(project), RecordingSandbox(project)

    # Do
    await SandboxSkills(restoring).prepare_session([skill], roots=[])
    reused = SandboxSkills(reusing)
    await reused.prepare_session([skill], roots=[])

    # Assert
    assert len(_uploads(restoring)) == 1
    assert (copy / "a.txt").read_bytes() == b"a"
    assert _uploads(reusing) == []
    location = reused.locate(skill)
    assert location is not None
    assert location.path == f"{copy}/SKILL.md"
    assert location.files == ("a.txt",)


@pytest.mark.asyncio
async def test_a_skill_too_large_for_one_argument_is_staged_and_copied(
    tmp_path: Path, project: Path, sandbox_tmp: Path
) -> None:
    """*Prepare*: A skill whose upload exceeds one command line argument.
    *Do*: Prepare it.
    *Assert*: It is uploaded in several commands, and copied intact.
    """
    # Prepare
    asset = os.urandom(200 * 1024)
    skill = _host_skill(tmp_path / "host" / "big", "big", files={"data.bin": asset})
    sandbox = RecordingSandbox(project)

    # Do
    skills = SandboxSkills(sandbox)
    await skills.prepare_session([skill], roots=[])

    # Assert
    assert len(_uploads(sandbox)) > 2
    assert skills.locate(skill) is not None
    ((_, copy),) = _copies(sandbox_tmp).items()
    assert copy["data.bin"] == asset
    assert not [path for path in sandbox_tmp.iterdir() if path.is_file()]


@pytest.mark.asyncio
async def test_a_skill_over_the_size_limits_is_left_out(
    tmp_path: Path, project: Path, sandbox_tmp: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """*Prepare*: A skill with a file over the per-file limit, and a small one.
    *Do*: Prepare both.
    *Assert*: Only the small one is copied; the other is left out, with a
    config issue that names it.
    """
    # Prepare
    large = _host_skill(
        tmp_path / "host" / "large", "large", files={"a.bin": b"x" * (257 * 1024)}
    )
    small = _host_skill(tmp_path / "host" / "small", "small", files={})
    skills = SandboxSkills(RecordingSandbox(project))

    # Do
    with caplog.at_level(logging.WARNING):
        session = await skills.prepare_session([large, small], roots=[])

    # Assert
    assert skills.locate(large) is None
    assert skills.locate(small) is not None
    assert len(_copies(sandbox_tmp)) == 1
    (issue,) = session.issues
    assert issue.file == str(large.skill_path)
    assert "a.bin exceeds the size limit" in issue.message
    assert any(str(large.skill_path) in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_a_skills_directory_others_can_write_is_not_used(
    tmp_path: Path, project: Path, sandbox_tmp: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """*Prepare*: A skills directory in the sandbox that every user can write.
    *Do*: Prepare a skill.
    *Assert*: Nothing is copied there, and the skill is left out, with a
    config issue that says why.
    """
    # Prepare
    root = sandbox_tmp / SKILLS_DIRNAME
    root.mkdir()
    root.chmod(0o777)
    skill = _host_skill(tmp_path / "host" / "notes", "notes", files={})
    skills = SandboxSkills(RecordingSandbox(project))

    # Do
    with caplog.at_level(logging.WARNING):
        session = await skills.prepare_session([skill], roots=[])

    # Assert
    assert skills.locate(skill) is None
    assert list(root.iterdir()) == []
    (issue,) = session.issues
    assert issue.file == str(skill.skill_path)
    assert "other users can reach" in issue.message
    assert any("other users can reach" in r.getMessage() for r in caplog.records)
