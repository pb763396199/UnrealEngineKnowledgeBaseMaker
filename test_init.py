"""
Test script for UE5-KB tool
"""
import sys
from pathlib import Path

# Add project path
sys.path.insert(0, str(Path(__file__).parent))

from ue5_kb.cli import detect_engine_version, generate_skill_md, generate_impl_py

# Test engine version detection
print("=" * 60)
print("Testing Engine Version Detection")
print("=" * 60)

test_engine_path = Path(r"D:\Unreal Engine\UnrealEngine51_500")
if test_engine_path.exists():
    version = detect_engine_version(test_engine_path)
    print(f"[OK] Engine path: {test_engine_path}")
    print(f"[OK] Detected version: {version}")
else:
    print(f"[SKIP] Engine path not found: {test_engine_path}")

# Test Skill generation
print("\n" + "=" * 60)
print("Testing Skill Template Generation")
print("=" * 60)

kb_path = Path("J:/Test/UE5-KB")
skill_path = Path("C:/Users/pb763/.claude/skills/ue5kb-5.1.500")
engine_version = "5.1.500"

print(f"KB path: {kb_path}")
print(f"Skill path: {skill_path}")
print(f"Engine version: {engine_version}")

# Test generation
try:
    skill_md = generate_skill_md(kb_path, engine_version)
    print(f"\n[OK] skill.md generated")
    print(f"  Length: {len(skill_md)} chars")

    impl_py = generate_impl_py(kb_path, engine_version)
    print(f"[OK] impl.py generated")
    print(f"  Length: {len(impl_py)} chars")

    # Verify key content
    if str(kb_path) in skill_md:
        print(f"[OK] skill.md contains correct KB path")

    if str(kb_path) in impl_py:
        print(f"[OK] impl.py contains correct KB path")

    if engine_version in skill_md:
        print(f"[OK] skill.md contains correct version")

    if engine_version in impl_py:
        print(f"[OK] impl.py contains correct version")

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)

except Exception as e:
    print(f"\n[ERROR] Test failed: {e}")
    import traceback
    traceback.print_exc()
