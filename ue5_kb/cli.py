"""
UE5 Knowledge Base Builder - CLI 接口

通用工具：为任何版本的 UE5 引擎生成知识库和 Claude Skill
"""
import click
from pathlib import Path
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
import re
import json
import sys

console = Console()


@click.group()
@click.version_option(version="2.0.0")
def cli():
    """UE5 Knowledge Base Builder - UE5 知识库生成工具

    为任何版本的 UE5 引擎生成知识库和 Claude Code Skill。
    """
    pass


@cli.command()
@click.option('--engine-path', type=click.Path(exists=True),
              help='UE5 引擎路径（与 --plugin-path 二选一）')
@click.option('--plugin-path', type=click.Path(exists=True),
              help='插件路径（与 --engine-path 二选一）')
@click.option('--kb-path', type=click.Path(),
              help='知识库保存路径 (默认: 引擎/插件根目录/KnowledgeBase)')
@click.option('--skill-path', type=click.Path(),
              help='Skill 保存路径 (默认: C:\\Users\\pb763\\.claude\\skills\\ue5kb-{版本}/)')
@click.pass_context
def init(ctx, engine_path, plugin_path, kb_path, skill_path):
    """初始化并生成知识库和 Skill

    支持两种模式：
    1. 引擎模式（--engine-path）：为整个 UE5 引擎生成知识库
    2. 插件模式（--plugin-path）：为单个插件生成知识库
    """

    # 0. 检查参数冲突
    if engine_path and plugin_path:
        console.print("[red]错误: --engine-path 和 --plugin-path 不能同时使用[/red]")
        return

    if not engine_path and not plugin_path:
        # 默认使用引擎模式
        console.print("\n[bold cyan]UE5 Knowledge Base Builder[/bold cyan]")
        console.print("为任何版本的 UE5 引擎生成知识库和 Claude Skill\n")
        engine_path = Prompt.ask(
            "UE5 引擎路径",
            default=r"D:\Unreal Engine\UnrealEngine51_500"
        )

    # 判断模式
    if plugin_path:
        # 插件模式
        init_plugin_mode(plugin_path, kb_path, skill_path)
    else:
        # 引擎模式
        init_engine_mode(engine_path, kb_path, skill_path)


def init_engine_mode(engine_path_str, kb_path, skill_path):
    """引擎模式：为整个 UE5 引擎生成知识库"""
    console.print("\n[bold cyan]模式: 引擎知识库生成[/bold cyan]\n")

    engine_path = Path(engine_path_str) if isinstance(engine_path_str, str) else engine_path_str
    if not engine_path.exists():
        console.print(f"[red]错误: 引擎路径不存在: {engine_path}[/red]")
        return

    # 2. 检测引擎版本
    engine_version = detect_engine_version(engine_path)
    console.print(f"[green]OK[/green] 检测到引擎版本: [bold cyan]{engine_version}[/bold cyan]")

    # 3. 计算默认路径
    if kb_path is None:
        kb_path = engine_path / "KnowledgeBase"
    else:
        kb_path = Path(kb_path)

    if skill_path is None:
        skill_path = Path("C:/Users/pb763/.claude/skills") / f"ue5kb-{engine_version}"
    else:
        skill_path = Path(skill_path)

    # 4. 显示配置摘要
    console.print("\n[bold]配置摘要:[/bold]\n")
    table = Table(show_header=False)
    table.add_column("项", style="cyan", width=20)
    table.add_column("值", style="yellow")
    table.add_row("引擎路径", str(engine_path))
    table.add_row("引擎版本", engine_version)
    table.add_row("知识库路径", str(kb_path))
    table.add_row("Skill 路径", str(skill_path))
    console.print(table)

    # 5. 生成知识库
    console.print("\n[bold cyan]步骤 1/2: 生成知识库...[/bold cyan]\n")
    success_kb = generate_knowledge_base(engine_path, kb_path, engine_version)

    if not success_kb:
        console.print("[red]X 知识库生成失败[/red]")
        return

    # 6. 生成 Skill
    console.print("\n[bold cyan]步骤 2/2: 生成 Claude Skill...[/bold cyan]\n")
    success_skill = generate_skill(kb_path, skill_path, engine_version)

    if not success_skill:
        console.print("[red]X Skill 生成失败[/red]")
        return

    # 7. 完成
    console.print(f"\n[green]OK 全部完成![/green]")
    console.print(f"\n[bold]生成的文件:[/bold]")
    console.print(f"  - 知识库: {kb_path}")
    console.print(f"  - Skill:  {skill_path}")
    console.print(f"\n[bold cyan]Next steps:[/bold cyan]")
    console.print(f"  使用 Claude Code 时，可以直接查询关于 UE{engine_version} 源码的问题")


def init_plugin_mode(plugin_path_str, kb_path, skill_path):
    """插件模式：为单个插件生成知识库"""
    console.print("\n[bold cyan]模式: 插件知识库生成[/bold cyan]\n")

    plugin_path = Path(plugin_path_str) if isinstance(plugin_path_str, str) else plugin_path_str
    if not plugin_path.exists():
        console.print(f"[red]错误: 插件路径不存在: {plugin_path}[/red]")
        return

    # 检测插件信息
    plugin_name, plugin_version = detect_plugin_info(plugin_path)
    console.print(f"[green]OK[/green] 检测到插件: [bold cyan]{plugin_name}[/bold cyan]")
    if plugin_version != "unknown":
        console.print(f"[green]OK[/green] 插件版本: [bold cyan]{plugin_version}[/bold cyan]")

    # 计算默认路径
    if kb_path is None:
        kb_path = plugin_path / "KnowledgeBase"
    else:
        kb_path = Path(kb_path)

    if skill_path is None:
        skill_name = f"{plugin_name.lower()}-kb"
        if plugin_version != "unknown":
            skill_name += f"-{plugin_version}"
        skill_path = Path("C:/Users/pb763/.claude/skills") / skill_name
    else:
        skill_path = Path(skill_path)

    # 显示配置摘要
    console.print("\n[bold]配置摘要:[/bold]\n")
    table = Table(show_header=False)
    table.add_column("项", style="cyan", width=20)
    table.add_column("值", style="yellow")
    table.add_row("插件路径", str(plugin_path))
    table.add_row("插件名称", plugin_name)
    table.add_row("插件版本", plugin_version)
    table.add_row("知识库路径", str(kb_path))
    table.add_row("Skill 路径", str(skill_path))
    console.print(table)

    # 生成知识库
    console.print("\n[bold cyan]步骤 1/2: 生成插件知识库...[/bold cyan]\n")
    success_kb = generate_plugin_knowledge_base(plugin_path, kb_path, plugin_name, plugin_version)

    if not success_kb:
        console.print("[red]X 知识库生成失败[/red]")
        return

    # 生成 Skill
    console.print("\n[bold cyan]步骤 2/2: 生成 Claude Skill...[/bold cyan]\n")
    skill_identifier = f"{plugin_name} {plugin_version}" if plugin_version != "unknown" else plugin_name
    success_skill = generate_skill(kb_path, skill_path, skill_identifier, is_plugin=True)

    if not success_skill:
        console.print("[red]X Skill 生成失败[/red]")
        return

    # 完成
    console.print(f"\n[green]OK 全部完成![/green]")
    console.print(f"\n[bold]生成的文件:[/bold]")
    console.print(f"  - 知识库: {kb_path}")
    console.print(f"  - Skill:  {skill_path}")
    console.print(f"\n[bold cyan]Next steps:[/bold cyan]")
    console.print(f"  使用 Claude Code 时，可以直接查询关于 {plugin_name} 插件的问题")


@cli.command()
def status():
    """显示当前状态"""
    console.print("\n[bold cyan]UE5 Knowledge Base Builder 状态[/bold cyan]\n")

    # TODO: 显示已生成的知识库和 Skill
    console.print("功能开发中...")


def detect_engine_version(engine_path: Path) -> str:
    """从引擎路径检测版本号"""
    # 方法1: 读取 Engine/Build/Build.version 文件 (最准确)
    build_version_file = engine_path / "Engine" / "Build" / "Build.version"
    if build_version_file.exists():
        try:
            import json
            content = build_version_file.read_text()
            version_data = json.loads(content)

            major = version_data.get("MajorVersion")
            minor = version_data.get("MinorVersion")
            patch = version_data.get("PatchVersion")

            if major and minor:
                if patch:
                    return f"{major}.{minor}.{patch}"
                else:
                    return f"{major}.{minor}.0"
        except Exception as e:
            console.print(f"[dim]读取 Build.version 失败: {e}[/dim]")

    # 方法2: 从文件夹名称解析 (如 UnrealEngine51_500 -> 5.1.500)
    path_name = engine_path.name
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', path_name)
    if match:
        major, minor, patch = match.groups()
        return f"{major}.{minor}.{patch}"

    # 默认返回 unknown
    return "unknown"


def detect_plugin_info(plugin_path: Path) -> tuple[str, str]:
    """从插件路径检测插件名称和版本

    Returns:
        (plugin_name, plugin_version)
    """
    # 方法1: 读取 .uplugin 文件
    uplugin_files = list(plugin_path.glob('*.uplugin'))
    if uplugin_files:
        uplugin_file = uplugin_files[0]
        plugin_name = uplugin_file.stem

        try:
            content = uplugin_file.read_text(encoding='utf-8')
            plugin_data = json.loads(content)

            # 读取版本信息
            version = plugin_data.get("VersionName") or plugin_data.get("Version")
            if version:
                return plugin_name, str(version)

            return plugin_name, "unknown"
        except Exception as e:
            console.print(f"[dim]读取 .uplugin 文件失败: {e}[/dim]")
            return plugin_name, "unknown"

    # 方法2: 使用文件夹名称
    plugin_name = plugin_path.name

    # 尝试从文件夹名称中提取版本 (例如: MyPlugin_1.2.3 -> MyPlugin, 1.2.3)
    match = re.search(r'(.+?)[-_](\d+\.\d+(?:\.\d+)?)', plugin_name)
    if match:
        name, version = match.groups()
        return name, version

    return plugin_name, "unknown"


def generate_knowledge_base(engine_path: Path, kb_path: Path, engine_version: str) -> bool:
    """生成引擎知识库"""
    console.print(f"  引擎: {engine_path}")
    console.print(f"  版本: {engine_version}")
    console.print(f"  保存到: {kb_path}")

    # 创建知识库目录
    kb_path.mkdir(parents=True, exist_ok=True)

    try:
        # 导入构建器
        from ue5_kb.core.config import Config
        from ue5_kb.builders.global_index_builder import GlobalIndexBuilder

        # 创建配置
        config = Config(base_path=str(kb_path))

        # 设置引擎路径
        config.set('project.engine_path', str(engine_path))
        config.set('project.engine_version', engine_version)

        # 保存配置
        config.save()

        console.print("\n[bold cyan]开始构建全局索引...[/bold cyan]")

        # 创建构建器并构建
        builder = GlobalIndexBuilder(config)
        global_index = builder.build_all(resume=True)

        # 输出统计
        stats = global_index.get_statistics()
        console.print(f"\n[green]OK[/green] 全局索引构建完成")
        console.print(f"  总模块数: {stats['total_modules']}")
        console.print(f"  总文件数: {stats['total_files']:,}")
        console.print(f"  预估代码行数: {stats['total_estimated_lines']:,}")

        return True

    except Exception as e:
        console.print(f"\n[red]X 知识库构建失败: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def generate_plugin_knowledge_base(plugin_path: Path, kb_path: Path, plugin_name: str, plugin_version: str) -> bool:
    """生成插件知识库"""
    console.print(f"  插件: {plugin_path}")
    console.print(f"  名称: {plugin_name}")
    console.print(f"  版本: {plugin_version}")
    console.print(f"  保存到: {kb_path}")

    # 创建知识库目录
    kb_path.mkdir(parents=True, exist_ok=True)

    try:
        # 导入构建器
        from ue5_kb.core.config import Config
        from ue5_kb.builders.plugin_index_builder import PluginIndexBuilder

        # 手动创建插件专用配置
        config_file = kb_path / "config.yaml"
        plugin_config = {
            'project': {
                'name': f'{plugin_name} Plugin Knowledge Base',
                'version': '2.0.0',
                'plugin_path': str(plugin_path),
                'plugin_name': plugin_name,
                'plugin_version': plugin_version,
            },
            'storage': {
                'base_path': str(kb_path),
                'global_index': str(kb_path / 'global_index'),
                'module_graphs': str(kb_path / 'module_graphs'),
                'cache': str(kb_path / 'cache'),
                'logs': str(kb_path / 'logs'),
                'checkpoints': str(kb_path / 'checkpoints'),
            },
            'build': {
                'parallel_workers': 4,
                'batch_size': 100,
                'checkpoint_interval': 10,
                'resume_from_checkpoint': True,
            },
            'verification': {
                'coverage_threshold': 95.0,
            }
        }

        # 保存配置文件
        import yaml
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(plugin_config, f, allow_unicode=True, default_flow_style=False)

        # 加载配置
        config = Config(config_path=str(config_file))

        console.print("\n[bold cyan]开始构建插件索引...[/bold cyan]")

        # 创建构建器并构建
        builder = PluginIndexBuilder(config)
        global_index = builder.build_all(resume=True)

        # 输出统计
        stats = global_index.get_statistics()
        console.print(f"\n[green]OK[/green] 插件索引构建完成")
        console.print(f"  总模块数: {stats['total_modules']}")
        console.print(f"  总文件数: {stats['total_files']:,}")
        console.print(f"  预估代码行数: {stats['total_estimated_lines']:,}")

        return True

    except Exception as e:
        console.print(f"\n[red]X 知识库构建失败: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def generate_skill(kb_path: Path, skill_path: Path, identifier: str, is_plugin: bool = False) -> bool:
    """生成 Claude Skill

    Args:
        kb_path: 知识库路径
        skill_path: Skill 保存路径
        identifier: 引擎版本或插件名称
        is_plugin: 是否为插件模式
    """
    skill_name = skill_path.name
    console.print(f"  Skill 名称: {skill_name}")
    console.print(f"  保存到: {skill_path}")

    # 创建 Skill 目录
    skill_path.mkdir(parents=True, exist_ok=True)

    # 生成 skill.md
    skill_md = generate_skill_md(kb_path, identifier, is_plugin)
    (skill_path / "skill.md").write_text(skill_md, encoding='utf-8')

    # 生成 impl.py
    impl_py = generate_impl_py(kb_path, identifier, is_plugin)
    (skill_path / "impl.py").write_text(impl_py, encoding='utf-8')

    console.print(f"[green]OK[/green] Skill 文件已生成")
    return True


def generate_skill_md(kb_path: Path, identifier: str, is_plugin: bool = False) -> str:
    """生成 skill.md 内容（从模板）

    Args:
        kb_path: 知识库路径
        identifier: 引擎版本或插件名称
        is_plugin: 是否为插件模式
    """
    if is_plugin:
        # 使用插件模板
        template_path = Path(__file__).parent.parent / "templates" / "plugin_skill.md.template"
    else:
        # 使用引擎模板
        template_path = Path(__file__).parent.parent / "templates" / "skill.md.template"

    # 如果模板存在，使用模板
    if template_path.exists():
        template_content = template_path.read_text(encoding='utf-8')
        return template_content.format(
            ENGINE_VERSION=identifier,
            KB_PATH=str(kb_path),
            PLUGIN_NAME=identifier
        )

    # 否则使用内嵌模板（向后兼容）
    if is_plugin:
        return f'''---
name: {identifier.lower().replace(' ', '-')}-kb
description: 查询 {identifier} 插件知识库（模块级 + 代码级查询）
---

# {identifier} 插件知识库查询技能

## 技能说明

此技能用于查询 {identifier} 插件源码知识库，支持**模块级查询**和**代码级查询**。

## 知识库路径

知识库存储在: `{kb_path}`

## 使用方法

直接询问关于 {identifier} 插件的问题，例如：
- "列出所有模块"
- "XXX 类继承自什么？"
- "搜索包含 YYY 的类"

## 自动加载

知识库会自动从 `{kb_path}` 加载。
'''
    else:
        return f'''---
name: ue5kb-{identifier}
description: 查询 UE{identifier} 引擎知识库（模块级 + 代码级查询）
---

# UE{identifier} 知识库查询技能

## 技能说明

此技能用于查询虚幻引擎 {identifier} 源码知识库，支持**模块级查询**和**代码级查询**。

## 知识库路径

知识库存储在: `{kb_path}`

## 使用方法

直接询问关于 UE{identifier} 源码的问题，例如：
- "Core 模块有哪些依赖？"
- "AActor 类继承自什么？"
- "列出所有 Runtime 模块"

## 自动加载

知识库会自动从 `{kb_path}` 加载。
'''


def generate_impl_py(kb_path: Path, identifier: str, is_plugin: bool = False) -> str:
    """生成 impl.py 内容（从模板）

    Args:
        kb_path: 知识库路径
        identifier: 引擎版本或插件名称
        is_plugin: 是否为插件模式
    """
    # 始终使用统一的模板（插件和引擎共用）
    template_path = Path(__file__).parent.parent / "templates" / "impl.py.template"

    # 如果模板存在，使用模板
    if template_path.exists():
        template_content = template_path.read_text(encoding='utf-8')
        return template_content.format(
            ENGINE_VERSION=identifier,
            KB_PATH=str(kb_path)
        )

    # 否则使用内嵌模板（向后兼容）
    context_type = "插件" if is_plugin else "引擎"
    return f'''"""
{identifier} {context_type}知识库查询实现
"""

import os
import sys
from pathlib import Path

# 知识库路径 (绝对路径)
KB_PATH = Path(r"{kb_path}")

# 添加知识库路径到 Python 路径
root_path = KB_PATH.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

# 导入知识库模块
try:
    from ue5_kb.core.config import Config
    from ue5_kb.core.global_index import GlobalIndex
    from ue5_kb.core.optimized_index import FastQueryInterface
except ImportError as e:
    raise ImportError(
        f"无法导入知识库模块: {{e}}\\n"
        f"请确保知识库已正确生成在: {{KB_PATH}}"
    )

def query_module_dependencies(module_name):
    """查询模块依赖"""
    config = Config(str(KB_PATH / "config.yaml"))
    index = GlobalIndex(config)

    module_info = index.get_module(module_name)
    if not module_info:
        return {{"error": f"未找到模块: {{module_name}}"}}

    deps = module_info.get('dependencies', [])
    return {{
        "module": module_name,
        "dependencies": deps,
        "info": module_info
    }}

def search_modules(keyword):
    """搜索模块"""
    config = Config(str(KB_PATH / "config.yaml"))
    index = GlobalIndex(config)

    all_modules = index.get_all_modules()
    results = []

    keyword_lower = keyword.lower()
    for module_name, info in all_modules.items():
        if keyword_lower in module_name.lower():
            results.append({{
                "name": module_name,
                "category": info.get('category'),
                "path": info.get('path')
            }})

    return {{
        "keyword": keyword,
        "found_count": len(results),
        "results": results[:50]
    }}

def get_statistics():
    """获取统计信息"""
    config = Config(str(KB_PATH / "config.yaml"))
    index = GlobalIndex(config)

    return index.get_statistics()
'''


def main():
    """CLI 入口点"""
    cli()


if __name__ == '__main__':
    main()
