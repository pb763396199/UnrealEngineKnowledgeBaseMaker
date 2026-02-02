"""
测试完整的 init 流程
"""
import os
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from ue5_kb.cli import detect_engine_version, generate_skill_md, generate_impl_py


def test_full_init():
    """测试完整的初始化流程"""

    print("=" * 60)
    print("Testing Full Init Flow")
    print("=" * 60)

    # 1. 测试引擎路径
    engine_path = Path(r"D:\Unreal Engine\UnrealEngine51_500")

    if not engine_path.exists():
        print(f"[SKIP] Engine path not found: {engine_path}")
        return False

    print(f"\n[OK] Engine path exists: {engine_path}")

    # 2. 检测引擎版本
    engine_version = detect_engine_version(engine_path)
    print(f"[OK] Detected version: {engine_version}")

    if engine_version == "unknown":
        print("[FAIL] Version detection failed")
        return False

    # 3. 计算路径
    kb_path = engine_path / "KnowledgeBase"
    skill_path = Path("C:/Users/pb763/.claude/skills") / f"ue5kb-{engine_version}"

    print(f"\n[OK] KB path: {kb_path}")
    print(f"[OK] Skill path: {skill_path}")

    # 4. 测试模板生成
    skill_md = generate_skill_md(kb_path, engine_version)
    impl_py = generate_impl_py(kb_path, engine_version)

    print(f"\n[OK] skill.md generated ({len(skill_md)} chars)")
    print(f"[OK] impl.py generated ({len(impl_py)} chars)")

    # 5. 验证内容
    if str(kb_path) not in skill_md:
        print("[FAIL] KB path not in skill.md")
        return False

    if str(kb_path) not in impl_py:
        print("[FAIL] KB path not in impl.py")
        return False

    if engine_version not in skill_md:
        print("[FAIL] Version not in skill.md")
        return False

    if engine_version not in impl_py:
        print("[FAIL] Version not in impl.py")
        return False

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)

    # 6. 显示配置摘要
    print("\n[bold]Configuration Summary:[/bold]")
    print(f"  Engine: {engine_path}")
    print(f"  Version: {engine_version}")
    print(f"  KB Path: {kb_path}")
    print(f"  Skill Path: {skill_path}")

    return True


if __name__ == "__main__":
    success = test_full_init()
    sys.exit(0 if success else 1)
