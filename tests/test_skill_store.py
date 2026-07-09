"""测试 ue5_kb/skill_store.py 的跨 provider 适配器安装逻辑，
尤其是"目标已失效的悬空 junction/symlink"场景。"""
import os
from pathlib import Path

import pytest

from ue5_kb.skill_store import create_directory_link


def _make_junction(link_path: Path, target_path: Path) -> None:
    import subprocess

    link_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(os.name != "nt", reason="junction 是 Windows 特有机制")
def test_create_directory_link_creates_fresh_link(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "marker.txt").write_text("hi", encoding="utf-8")
    destination = tmp_path / "provider" / "skill-name"

    result = create_directory_link(source, destination)

    assert result["status"] == "ok"
    assert destination.exists()
    assert (destination / "marker.txt").read_text(encoding="utf-8") == "hi"


@pytest.mark.skipif(os.name != "nt", reason="junction 是 Windows 特有机制")
def test_create_directory_link_replaces_dangling_junction_with_force(tmp_path):
    """回归测试：旧 junction 指向的目标目录已被删除/迁移（比如换了台机器、换了用户名）时，
    `Path.exists()` 会跟随 reparse point 解析目标，目标不存在则返回 False，导致
    `create_directory_link` 误判"目的地不存在"从而跳过备份步骤；随后 os.symlink/mklink
    都会因为磁盘上仍然有这个悬空条目而报 "already exists" 失败，旧的错误链接被原样保留。
    """
    stale_target = tmp_path / "stale_user_profile" / "old_skill_location"
    stale_target.mkdir(parents=True)
    destination = tmp_path / "provider" / "skill-name"
    _make_junction(destination, stale_target)

    # 模拟"换机器/换用户名"：悬空 junction 的目标彻底消失
    stale_target.rmdir()
    assert not destination.exists()  # 复现关键前提：exists() 因目标消失而返回 False
    assert os.path.lexists(destination)  # 但 reparse point 条目本身仍然物理存在

    new_source = tmp_path / "new_correct_location"
    new_source.mkdir()
    (new_source / "marker.txt").write_text("correct data", encoding="utf-8")

    result = create_directory_link(new_source, destination, force=True)

    assert result["status"] == "ok", result
    assert destination.exists()
    assert (destination / "marker.txt").read_text(encoding="utf-8") == "correct data"


@pytest.mark.skipif(os.name != "nt", reason="junction 是 Windows 特有机制")
def test_create_directory_link_without_force_skips_existing_destination(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    other_source = tmp_path / "other_source"
    other_source.mkdir()
    destination = tmp_path / "provider" / "skill-name"
    _make_junction(destination, source)

    result = create_directory_link(other_source, destination, force=False)

    assert result["status"] == "skipped"
    assert result["reason"] == "destination_exists"


@pytest.mark.skipif(os.name != "nt", reason="junction 是 Windows 特有机制")
def test_create_directory_link_recognizes_already_correct_link(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "provider" / "skill-name"
    _make_junction(destination, source)

    result = create_directory_link(source, destination, force=False)

    assert result["status"] == "ok"
    assert result["action"] == "exists"
