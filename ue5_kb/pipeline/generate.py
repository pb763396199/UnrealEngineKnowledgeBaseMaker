"""
Pipeline 阶段 5: Generate (生成 Skill)

从模板生成 Claude Code Skill
"""

from pathlib import Path
from typing import Dict, Any
import shutil
from .base import PipelineStage


class GenerateStage(PipelineStage):
    """
    生成阶段

    从模板生成 Claude Code Skill
    """

    def __init__(self, base_path: Path, is_plugin: bool = False, plugin_name: str = None):
        """
        初始化生成阶段

        Args:
            base_path: 引擎/插件根目录
            is_plugin: 是否为插件模式
            plugin_name: 插件名称
        """
        super().__init__(base_path)
        self.is_plugin = is_plugin
        self.plugin_name = plugin_name

    @property
    def stage_name(self) -> str:
        return "generate"

    def get_output_path(self) -> Path:
        # Skill 输出到用户目录
        # 这里返回标记文件
        return self.stage_dir / "skill_generated.txt"

    def run(self, engine_version: str = None, skill_name: str = None, **kwargs) -> Dict[str, Any]:
        """
        生成 Claude Code Skill

        Args:
            engine_version: 引擎版本
            skill_name: Skill 名称

        Returns:
            生成结果
        """
        print(f"[Generate] 生成 Claude Code Skill...")

        # 获取知识库路径
        kb_path = self.base_path / "KnowledgeBase"
        if not kb_path.exists():
            raise RuntimeError("知识库不存在，请先运行 build 阶段")

        # 确定 Skill 名称
        if not skill_name:
            if self.is_plugin and self.plugin_name:
                # 插件模式: {plugin_name}-kb (不包含版本)
                skill_name = f"{self.plugin_name}-kb"
            else:
                # 引擎模式: ue5kb-{version}
                if not engine_version:
                    engine_version = self._detect_engine_version()
                skill_name = f"ue5kb-{engine_version}"

        # 确定 Skill 目录
        skill_path = self._get_skill_path(skill_name)

        # 生成 Skill（根据模式选择模板）
        # 插件模式使用插件版本，引擎模式使用引擎版本
        version = self._detect_plugin_version() if self.is_plugin else engine_version
        if not version:
            version = "1.0"
        self._generate_skill(kb_path, skill_path, version)

        # 创建标记文件
        self.stage_dir.mkdir(parents=True, exist_ok=True)
        marker_file = self.get_output_path()
        marker_file.write_text(f"Skill generated at: {skill_path}")

        result = {
            'skill_name': skill_name,
            'skill_path': str(skill_path),
            'kb_path': str(kb_path),
            'engine_version': engine_version
        }

        self.save_result(result, "generate_result.json")

        print(f"[Generate] 完成！")
        print(f"  Skill 名称: {skill_name}")
        print(f"  Skill 路径: {skill_path}")

        return result

    def _detect_engine_version(self) -> str:
        """检测引擎版本"""
        # 首先尝试引擎模式：从 Build.version 读取
        build_version_file = self.base_path / "Engine" / "Build" / "Build.version"

        if build_version_file.exists():
            import json
            with open(build_version_file, 'r', encoding='utf-8') as f:
                version_data = json.load(f)
                major = version_data.get('MajorVersion', 5)
                minor = version_data.get('MinorVersion', 0)
                patch = version_data.get('PatchVersion', 0)
                return f"{major}.{minor}.{patch}"

        # 从目录名推测
        dir_name = self.base_path.name
        import re
        match = re.search(r'(\d+)[._](\d+)(?:[._](\d+))?', dir_name)
        if match:
            major = match.group(1)
            minor = match.group(2)
            patch = match.group(3) or '0'
            return f"{major}.{minor}.{patch}"

        return "5.0.0"

    def _detect_plugin_version(self) -> str:
        """检测插件版本（仅插件模式使用）"""
        # 从 .uplugin 文件读取插件版本
        uplugin_files = list(self.base_path.glob("*.uplugin"))
        if uplugin_files:
            import json
            try:
                with open(uplugin_files[0], 'r', encoding='utf-8') as f:
                    plugin_data = json.load(f)
                    # 优先使用 VersionName
                    version = plugin_data.get('VersionName', '')
                    if version:
                        return version
                    # 其次使用 Version
                    version = plugin_data.get('Version', '')
                    if version:
                        return str(version)
            except Exception:
                pass

        # 从目录名推测
        dir_name = self.base_path.name
        import re
        match = re.search(r'[-_](\d+)[._](\d+)(?:[._](\d+))?', dir_name)
        if match:
            major = match.group(1)
            minor = match.group(2)
            patch = match.group(3) or '0'
            return f"{major}.{minor}.{patch}"

        return "1.0"

    def _get_skill_path(self, skill_name: str) -> Path:
        """获取 Skill 路径"""
        import os
        home = Path.home()
        claude_skills_dir = home / ".claude" / "skills"
        return claude_skills_dir / skill_name

    def _generate_skill(self, kb_path: Path, skill_path: Path, engine_version: str) -> None:
        """
        生成 Skill 文件

        Args:
            kb_path: 知识库路径
            skill_path: Skill 路径
            engine_version: 引擎版本
        """
        # 创建 Skill 目录
        skill_path.mkdir(parents=True, exist_ok=True)

        # 获取模板目录
        template_dir = Path(__file__).parent.parent.parent / "templates"

        # 根据模式选择模板
        if self.is_plugin:
            skill_md_template = template_dir / "skill.plugin.md.template"
            impl_py_template = template_dir / "impl.plugin.py.template"
            # 如果插件模板不存在，回退到引擎模板
            if not skill_md_template.exists():
                skill_md_template = template_dir / "skill.md.template"
            if not impl_py_template.exists():
                impl_py_template = template_dir / "impl.py.template"
        else:
            skill_md_template = template_dir / "skill.md.template"
            impl_py_template = template_dir / "impl.py.template"

        if not skill_md_template.exists() or not impl_py_template.exists():
            raise FileNotFoundError("模板文件不存在")

        # 从 manifest 加载版本信息
        from ..core.manifest import KBManifest
        from datetime import datetime

        manifest = KBManifest.load(kb_path)

        # 获取版本信息
        if manifest:
            kb_version = manifest.kb_version
            created_at = manifest.created_at
            last_updated = manifest.last_updated
        else:
            # 降级：使用默认值
            kb_version = "2.13.0"
            now = datetime.now().isoformat()
            created_at = now
            last_updated = now

        # 获取工具版本（从 importlib.metadata，避免 Config 权限问题）
        try:
            from importlib.metadata import version
            tool_version = version("ue5-kb")
        except Exception:
            tool_version = "2.13.0"

        # 插件版本（仅插件模式）
        plugin_version = self._detect_plugin_version() if self.is_plugin else None

        # 替换变量
        variables = {
            'ENGINE_VERSION': engine_version,
            'KB_VERSION': kb_version,
            'TOOL_VERSION': tool_version,
            'CREATED_AT': created_at,
            'LAST_UPDATED': last_updated,
            'KB_PATH': str(kb_path).replace('\\', '\\\\'),
            'SKILL_PATH': str(skill_path),
            'PLUGIN_NAME': self.plugin_name or 'Unknown',
            'PLUGIN_VERSION': plugin_version or '1.0',
        }

        # 生成 skill.md
        with open(skill_md_template, 'r', encoding='utf-8') as f:
            skill_md_content = f.read()

        for key, value in variables.items():
            skill_md_content = skill_md_content.replace(f'{{{key}}}', value)

        with open(skill_path / "skill.md", 'w', encoding='utf-8') as f:
            f.write(skill_md_content)

        # 生成 impl.py
        with open(impl_py_template, 'r', encoding='utf-8') as f:
            impl_py_content = f.read()

        for key, value in variables.items():
            impl_py_content = impl_py_content.replace(f'{{{key}}}', value)

        # 修复：将模板中的 {{ 和 }} 转换为单花括号（Python 字典语法）
        impl_py_content = impl_py_content.replace('{{', '{').replace('}}', '}')

        with open(skill_path / "impl.py", 'w', encoding='utf-8') as f:
            f.write(impl_py_content)

        print(f"  生成 skill.md 和 impl.py")
