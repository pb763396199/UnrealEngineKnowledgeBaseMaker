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
              help='UE5 引擎路径')
@click.option('--kb-path', type=click.Path(),
              help='知识库保存路径 (默认: 引擎根目录/KnowledgeBase)')
@click.option('--skill-path', type=click.Path(),
              help='Skill 保存路径 (默认: C:\\Users\\pb763\\.claude\\skills\\ue5kb-{版本}/)')
@click.pass_context
def init(ctx, engine_path, kb_path, skill_path):
    """初始化并生成知识库和 Skill"""

    # 1. 获取引擎路径
    if not engine_path:
        console.print("\n[bold cyan]UE5 Knowledge Base Builder[/bold cyan]")
        console.print("为任何版本的 UE5 引擎生成知识库和 Claude Skill\n")
        engine_path = Prompt.ask(
            "UE5 引擎路径",
            default=r"D:\Unreal Engine\UnrealEngine51_500"
        )

    engine_path = Path(engine_path)
    if not engine_path.exists():
        console.print(f"[red]错误: 引擎路径不存在: {engine_path}[/red]")
        return

    # 2. 检测引擎版本
    engine_version = detect_engine_version(engine_path)
    console.print(f"[green]✓[/green] 检测到引擎版本: [bold cyan]{engine_version}[/bold cyan]")

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
        console.print("[red]✗ 知识库生成失败[/red]")
        return

    # 6. 生成 Skill
    console.print("\n[bold cyan]步骤 2/2: 生成 Claude Skill...[/bold cyan]\n")
    success_skill = generate_skill(kb_path, skill_path, engine_version)

    if not success_skill:
        console.print("[red]✗ Skill 生成失败[/red]")
        return

    # 7. 完成
    console.print(f"\n[green]✓ 全部完成![/green]")
    console.print(f"\n[bold]生成的文件:[/bold]")
    console.print(f"  • 知识库: {kb_path}")
    console.print(f"  • Skill:  {skill_path}")
    console.print(f"\n[bold cyan]下一步:[/bold]")
    console.print(f"  使用 Claude Code 时，可以直接查询关于 UE{engine_version} 源码的问题")


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


def generate_knowledge_base(engine_path: Path, kb_path: Path, engine_version: str) -> bool:
    """生成知识库"""
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
        console.print(f"\n[green]✓[/green] 全局索引构建完成")
        console.print(f"  总模块数: {stats['total_modules']}")
        console.print(f"  总文件数: {stats['total_files']:,}")
        console.print(f"  预估代码行数: {stats['total_estimated_lines']:,}")

        return True

    except Exception as e:
        console.print(f"\n[red]✗ 知识库构建失败: {e}[/red]")
        import traceback
        traceback.print_exc()
        return False


def generate_skill(kb_path: Path, skill_path: Path, engine_version: str) -> bool:
    """生成 Claude Skill"""
    console.print(f"  Skill 名称: ue5kb-{engine_version}")
    console.print(f"  保存到: {skill_path}")

    # 创建 Skill 目录
    skill_path.mkdir(parents=True, exist_ok=True)

    # 生成 skill.md
    skill_md = generate_skill_md(kb_path, engine_version)
    (skill_path / "skill.md").write_text(skill_md, encoding='utf-8')

    # 生成 impl.py
    impl_py = generate_impl_py(kb_path, engine_version)
    (skill_path / "impl.py").write_text(impl_py, encoding='utf-8')

    console.print(f"[green]✓[/green] Skill 文件已生成")
    return True


def generate_skill_md(kb_path: Path, engine_version: str) -> str:
    """生成 skill.md 内容"""
    return f'''---
name: ue5kb-{engine_version}
description: 查询 UE{engine_version} 引擎知识库
---

# UE{engine_version} 知识库查询技能

## 技能说明

此技能用于查询虚幻引擎 {engine_version} 源码知识库。

## 知识库路径

知识库存储在: `{kb_path}`

## 使用方法

直接询问关于 UE{engine_version} 源码的问题，例如：
- "Core 模块有哪些依赖？"
- "AActor 类继承自什么？"
- "列出所有 Runtime 模块"

## 自动加载

知识库会自动从 `{kb_path}` 加载。
'''


def generate_impl_py(kb_path: Path, engine_version: str) -> str:
    """生成 impl.py 内容"""
    # 计算相对路径（从 Skill 目录到知识库）
    try:
        rel_kb_path = Path(os.path.relpath(kb_path, Path("C:/Users/pb763/.claude/skills")))
    except:
        rel_kb_path = kb_path

    return f'''"""
UE{engine_version} 知识库查询实现
"""

import os
import sys
from pathlib import Path

# 知识库路径 (绝对路径)
KB_PATH = Path(r"{kb_path}")

# 添加知识库路径到 Python 路径
if str(KB_PATH.parent) not in sys.path:
    sys.path.insert(0, str(KB_PATH.parent))

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

def query_knowledge_base(question):
    """查询知识库

    Args:
        question: 自然语言问题

    Returns:
        查询结果
    """
    # 创建配置
    config = Config(str(KB_PATH / "config.yaml"))

    # 使用快速查询接口
    query_interface = FastQueryInterface()

    # 解析问题并查询
    result = query_interface.query(question)

    return result


# 示例查询函数
def query_module_dependencies(module_name):
    """查询模块依赖"""
    config = Config(str(KB_PATH / "config.yaml"))
    index = GlobalIndex(config)

    module_info = index.get_module(module_name)
    if not module_info:
        return f"未找到模块: {{module_name}}"

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

    results = index.search_modules(keyword)
    return results


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
