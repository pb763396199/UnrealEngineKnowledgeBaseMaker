"""
.uproject → KB Skill 自动映射

解析 .uproject 的 EngineAssociation，扫描已安装的 KB skills，返回匹配的 KB 路径。
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def parse_uproject(uproject_path: Path) -> Optional[str]:
    """
    解析 .uproject 文件中的 EngineAssociation。

    返回清理后的版本字符串（如 "5.5"、"5.5.4"），
    GUID 格式返回原始值，解析失败返回 None。
    """
    try:
        with open(uproject_path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    assoc = data.get("EngineAssociation", "")
    if not assoc:
        return None

    # 去掉花括号包裹: "{5.5}" → "5.5"
    cleaned = assoc.strip("{}")

    return cleaned if cleaned else None


def scan_kb_skills(skills_dir: Optional[Path] = None) -> Dict[str, Path]:
    """
    扫描共享 Skill store 下的 ue5kb-* 目录。

    返回 {engine_version: skill_dir_path} 映射。
    """
    if skills_dir is None:
        from .skill_store import get_default_skill_root
        skills_dir = get_default_skill_root()

    if not skills_dir.is_dir():
        return {}

    result = {}
    pattern = re.compile(r'^ue5kb-(.+)$')

    for item in skills_dir.iterdir():
        if not item.is_dir():
            continue
        m = pattern.match(item.name)
        if not m:
            continue
        # 需要有 skill.md 和 impl.py 才算有效
        if (item / "skill.md").exists() and (item / "impl.py").exists():
            result[m.group(1)] = item

    return result


def match_version(target: str, available: List[str]) -> Optional[str]:
    """
    版本匹配：精确 > 前缀匹配 > None。

    target: 从 .uproject 解析的版本（如 "5.5"）
    available: 已安装 KB 的版本列表（如 ["5.5.4", "5.1.1"]）
    """
    if not available:
        return None

    # 精确匹配
    if target in available:
        return target

    # 前缀匹配：target 是 available 的前缀（5.5 匹配 5.5.4）
    prefix_matches = [v for v in available if v.startswith(target + ".") or v.startswith(target + "-")]
    if len(prefix_matches) == 1:
        return prefix_matches[0]

    # 多个前缀匹配 → 选最高版本
    if prefix_matches:
        return sorted(prefix_matches, key=_version_key, reverse=True)[0]

    # 反向前缀：available 中某版本是 target 的前缀
    reverse_matches = [v for v in available if target.startswith(v + ".") or target.startswith(v + "-")]
    if reverse_matches:
        return sorted(reverse_matches, key=_version_key, reverse=True)[0]

    return None


def _version_key(version: str) -> Tuple:
    """将版本字符串转为可排序的元组"""
    parts = re.split(r'[.\-_]', version)
    result = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            result.append(p)
    return tuple(result)


def resolve_engine_kb(uproject_path: Path, skills_dir: Optional[Path] = None) -> Optional[dict]:
    """
    从 .uproject 文件解析引擎版本，找到对应的 KB skill。

    返回:
        {
            "engine_association": "5.5",
            "matched_version": "5.5.4",
            "skill_path": Path("~/.agents/skills/ue5kb-5.5.4"),
            "kb_path": Path("..."),  # 尝试从 registry 或 fallback 解析
        }
        失败返回 None。
    """
    uproject_path = Path(uproject_path)
    if not uproject_path.exists():
        return None

    assoc = parse_uproject(uproject_path)
    if not assoc:
        return None

    # GUID 格式无法匹配版本号
    if re.match(r'^[0-9a-fA-F]{8}-', assoc):
        return {"engine_association": assoc, "matched_version": None,
                "skill_path": None, "kb_path": None, "error": "GUID 格式无法自动映射"}

    skills = scan_kb_skills(skills_dir)
    if not skills:
        return {"engine_association": assoc, "matched_version": None,
                "skill_path": None, "kb_path": None, "error": "未找到已安装的 KB skills"}

    matched = match_version(assoc, list(skills.keys()))
    if not matched:
        return {"engine_association": assoc, "matched_version": None,
                "skill_path": None, "kb_path": None,
                "error": f"无匹配版本 (已安装: {', '.join(skills.keys())})"}

    skill_path = skills[matched]

    # 尝试解析 KB 路径
    kb_path = _resolve_kb_from_skill(skill_path)

    return {
        "engine_association": assoc,
        "matched_version": matched,
        "skill_path": str(skill_path),
        "kb_path": str(kb_path) if kb_path else None,
    }


def _resolve_kb_from_skill(skill_path: Path) -> Optional[Path]:
    """从 skill 目录解析 KB 路径（优先 registry，回退到 impl.py 中的硬编码路径）"""
    # 方法 1: BranchManager.resolve_kb_path()
    try:
        from .branch_manager import BranchManager
        mgr = BranchManager(skill_path)
        return Path(mgr.resolve_kb_path())
    except Exception:
        pass

    # 方法 2: 从 impl.py 中提取 _FALLBACK_KB_PATH
    impl_py = skill_path / "impl.py"
    if impl_py.exists():
        try:
            content = impl_py.read_text(encoding='utf-8')
            m = re.search(r'_FALLBACK_KB_PATH\s*=\s*(?:Path\()?[r]?["\'](.+?)["\']', content)
            if m:
                fallback = Path(m.group(1))
                if fallback.exists():
                    return fallback
        except Exception:
            pass

    return None
