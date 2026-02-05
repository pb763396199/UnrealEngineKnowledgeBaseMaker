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
@click.version_option(version="2.10.0")
def cli():
    """UE5 Knowledge Base Builder - UE5 知识库生成工具

    \b
    支持双模式：
    - 引擎模式: 为整个 UE5 引擎生成知识库（1757+ 模块）
    - 插件模式: 为单个插件生成独立知识库

    \b
    v2.10.0 新特性：
    - 并行加速：多进程处理，4-8x 性能提升
    - 多进度条：实时显示各 worker 状态
    - 性能监控：各阶段耗时统计
    - Checkpoint：Analyze 阶段支持中断恢复

    \b
    可用命令：
      ue5kb init            初始化并生成知识库和 Skill
      ue5kb status          显示当前状态

    \b
    Pipeline 高级命令：
      ue5kb pipeline run              运行完整 Pipeline
      ue5kb pipeline status           查看 Pipeline 状态
      ue5kb pipeline clean            清除特定阶段的输出
      ue5kb pipeline partitioned      使用分区模式构建（大型引擎）
      ue5kb pipeline partition-status 查看分区构建状态

    \b
    常用示例：
      # 引擎模式 - 快速开始（自动检测并行度）
      ue5kb init --engine-path "D:\\Unreal Engine\\UE5.1"

      # 指定并行 worker 数量
      ue5kb init --engine-path "D:\\UE5" --workers 8
      ue5kb init --engine-path "D:\\UE5" -j 4

      # 插件模式
      ue5kb init --plugin-path "F:\\MyProject\\Plugins\\MyPlugin"

      # 高级选项
      ue5kb init --engine-path "D:\\UE5" --force
      ue5kb init --engine-path "D:\\UE5" --stage build
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
              help='Skill 保存路径 (默认: ~/.claude/skills/ue5kb-{版本})')
@click.option('--force', is_flag=True,
              help='强制重新运行所有阶段（忽略已完成的阶段）')
@click.option('--stage', type=click.Choice(['discover', 'extract', 'analyze', 'build', 'generate']),
              help='仅运行指定阶段（高级用法）')
@click.option('--workers', '-j', type=int, default=0,
              help='并行工作线程数（0=自动检测 CPU 核心数，默认: 0）')
@click.option('--verbose', '-v', is_flag=True,
              help='显示详细输出（用于调试）')
@click.pass_context
def init(ctx, engine_path, plugin_path, kb_path, skill_path, force, stage, workers, verbose):
    """初始化并生成知识库和 Skill

    \b
    v2.10.0 新特性：
    - 并行加速：多进程处理，4-8x 性能提升
    - 多进度条：实时显示各 worker 状态
    - 性能监控：各阶段耗时统计
    - Checkpoint：Analyze 阶段支持中断恢复

    \b
    支持两种模式：
    1. 引擎模式（--engine-path）
       为整个 UE5 引擎生成知识库（1757+ 模块）
       示例: ue5kb init --engine-path "D:\\Unreal Engine\\UE5.1"

    2. 插件模式（--plugin-path）
       为单个插件生成独立知识库
       示例: ue5kb init --plugin-path "F:\\MyProject\\Plugins\\MyPlugin"

    \b
    高级选项：
    - --force: 强制重新运行所有阶段
    - --stage: 仅运行指定阶段（discover/extract/analyze/build/generate）
    - --workers, -j: 并行工作线程数（0=自动检测 CPU 核心数，默认: 0）
    - --verbose, -v: 显示详细输出（用于调试）

    \b
    并行处理示例：
    # 自动检测并行度（推荐）
    ue5kb init --engine-path "D:\\UE5" -j 0

    # 指定 8 个 worker
    ue5kb init --engine-path "D:\\UE5" --workers 8

    # 串行模式（调试用）
    ue5kb init --engine-path "D:\\UE5" --workers 1

    \b
    输出内容：
    - 知识库：包含模块索引和代码图谱
    - Claude Skill：自动生成查询接口

    \b
    Pipeline 阶段：
    1. discover - 发现所有模块
    2. extract - 提取模块依赖
    3. analyze - 分析代码结构（最耗时，并行效果最明显）
    4. build - 构建索引
    5. generate - 生成 Skill
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
        init_plugin_mode(plugin_path, kb_path, skill_path, force, stage, workers, verbose)
    else:
        # 引擎模式
        init_engine_mode(engine_path, kb_path, skill_path, force, stage, workers, verbose)


def init_engine_mode(engine_path_str, kb_path, skill_path, force, stage, workers, verbose=False):
    """引擎模式：为整个 UE5 引擎生成知识库（使用 Pipeline 架构）"""
    console.print("\n[bold cyan]模式: 引擎知识库生成[/bold cyan]\n")

    engine_path = Path(engine_path_str) if isinstance(engine_path_str, str) else engine_path_str
    if not engine_path.exists():
        console.print(f"[red]错误: 引擎路径不存在: {engine_path}[/red]")
        return

    # 2. 检测引擎版本
    engine_version = detect_engine_version(engine_path)
    console.print(f"[green]OK[/green] 检测到引擎版本: [bold cyan]{engine_version}[/bold cyan]")

    # 3. 计算默认路径
    default_kb_path = engine_path / "KnowledgeBase"
    kb_path = Path(kb_path) if kb_path else default_kb_path

    # 4. 显示配置摘要
    console.print("\n[bold]配置摘要:[/bold]\n")
    table = Table(show_header=False)
    table.add_column("项", style="cyan", width=20)
    table.add_column("值", style="yellow")
    table.add_row("引擎路径", str(engine_path))
    table.add_row("引擎版本", engine_version)
    table.add_row("知识库路径", str(kb_path))

    # 显示高级选项
    if force:
        table.add_row("强制运行", "是")
    if stage:
        table.add_row("运行阶段", stage)

    console.print(table)

    # 5. 使用 PipelineCoordinator 运行
    console.print("\n[bold cyan]开始 Pipeline...[/bold cyan]\n")

    # 显示并行度配置
    if workers == 0:
        import os
        detected_workers = os.cpu_count() or 4
        console.print(f"[dim]自动检测并行度: {detected_workers} workers[/dim]\n")
    else:
        console.print(f"[dim]并行度: {workers} workers[/dim]\n")

    try:
        from ue5_kb.pipeline.coordinator import PipelineCoordinator

        coordinator = PipelineCoordinator(engine_path)

        if stage:
            # 仅运行指定阶段
            console.print(f"运行阶段: [cyan]{stage}[/cyan]\n")
            result = coordinator.run_stage(stage, force=force, parallel=workers, verbose=verbose)
            results = {stage: result}
        else:
            # 运行完整 Pipeline
            results = coordinator.run_all(force=force, parallel=workers, verbose=verbose)

        # 6. 显示结果
        display_pipeline_results(results)

        # 7. 处理自定义路径
        if kb_path != default_kb_path and default_kb_path.exists():
            # 如果指定了自定义路径，移动知识库
            console.print(f"\n[cyan]移动知识库到自定义路径...[/cyan]")
            import shutil
            if kb_path.exists():
                shutil.rmtree(kb_path)
            shutil.move(str(default_kb_path), str(kb_path))
            console.print(f"[green]OK[/green] 知识库已移动到: {kb_path}")

        # 8. 处理自定义 Skill 路径
        if skill_path:
            skill_path = Path(skill_path)
            default_skill_dir = Path.home() / ".claude" / "skills" / f"ue5kb-{engine_version}"
            if default_skill_dir.exists():
                import shutil
                if skill_path.exists():
                    shutil.rmtree(skill_path)
                shutil.move(str(default_skill_dir), str(skill_path))
                console.print(f"[green]OK[/green] Skill 已移动到: {skill_path}")

        # 9. 完成
        console.print(f"\n[green]OK 全部完成![/green]")
        console.print(f"\n[bold]生成的文件:[/bold]")
        console.print(f"  - 知识库: {kb_path}")

        generate_result = results.get('generate', {})
        if 'skill_path' in generate_result:
            skill_location = skill_path if skill_path else generate_result['skill_path']
            console.print(f"  - Skill:  {skill_location}")

        console.print(f"\n[bold cyan]Next steps:[/bold cyan]")
        console.print(f"  使用 Claude Code 时，可以直接查询关于 UE{engine_version} 源码的问题")
        console.print(f"  [dim]提示: 使用 'ue5kb pipeline status --engine-path \"{engine_path}\"' 查看状态[/dim]")

    except Exception as e:
        console.print(f"\n[red]X Pipeline 执行失败: {e}[/red]")
        import traceback
        traceback.print_exc()
        return


def init_plugin_mode(plugin_path_str, kb_path, skill_path, force, stage, workers, verbose=False):
    """插件模式：为单个插件生成知识库（使用 Pipeline 架构）"""
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
    default_kb_path = plugin_path / "KnowledgeBase"
    kb_path = Path(kb_path) if kb_path else default_kb_path

    # 显示配置摘要
    console.print("\n[bold]配置摘要:[/bold]\n")
    table = Table(show_header=False)
    table.add_column("项", style="cyan", width=20)
    table.add_column("值", style="yellow")
    table.add_row("插件路径", str(plugin_path))
    table.add_row("插件名称", plugin_name)
    table.add_row("插件版本", plugin_version)
    table.add_row("知识库路径", str(kb_path))

    if force:
        table.add_row("强制运行", "是")
    if stage:
        table.add_row("运行阶段", stage)

    console.print(table)

    # 运行 Pipeline
    console.print("\n[bold cyan]开始 Pipeline...[/bold cyan]\n")

    # 显示并行度配置
    if workers == 0:
        import os
        detected_workers = os.cpu_count() or 4
        console.print(f"[dim]自动检测并行度: {detected_workers} workers[/dim]\n")
    else:
        console.print(f"[dim]并行度: {workers} workers[/dim]\n")

    try:
        from ue5_kb.pipeline.coordinator import PipelineCoordinator

        coordinator = PipelineCoordinator(plugin_path, is_plugin=True, plugin_name=plugin_name)

        if stage:
            console.print(f"运行阶段: [cyan]{stage}[/cyan]\n")
            result = coordinator.run_stage(stage, force=force, parallel=workers, verbose=verbose)
            results = {stage: result}
        else:
            results = coordinator.run_all(force=force, parallel=workers, verbose=verbose)

        # 显示结果
        display_pipeline_results(results)

        # 处理自定义路径
        if kb_path != default_kb_path and default_kb_path.exists():
            console.print(f"\n[cyan]移动知识库到自定义路径...[/cyan]")
            import shutil
            if kb_path.exists():
                shutil.rmtree(kb_path)
            shutil.move(str(default_kb_path), str(kb_path))
            console.print(f"[green]OK[/green] 知识库已移动到: {kb_path}")

        # 完成
        console.print(f"\n[green]OK 全部完成![/green]")
        console.print(f"\n[bold]生成的文件:[/bold]")
        console.print(f"  - 知识库: {kb_path}")

        console.print(f"\n[bold cyan]Next steps:[/bold cyan]")
        console.print(f"  使用 Claude Code 时，可以直接查询关于 {plugin_name} 插件的问题")

    except Exception as e:
        console.print(f"\n[red]X Pipeline 执行失败: {e}[/red]")
        import traceback
        traceback.print_exc()
        return


def display_pipeline_results(results: dict) -> None:
    """显示 Pipeline 执行结果"""
    console.print(f"\n[bold cyan]=== Pipeline 结果 ===[/bold cyan]\n")

    table = Table()
    table.add_column("阶段")
    table.add_column("状态")
    table.add_column("详情")

    for stage_name, result in results.items():
        if result.get('skipped'):
            status = "[yellow]跳过[/yellow]"
            details = result.get('reason', '')
        elif result.get('error'):
            status = "[red]失败[/red]"
            details = result.get('error', '')[:50]
        else:
            status = "[green]成功[/green]"
            # 提取关键统计
            if 'total_count' in result:
                details = f"{result['total_count']} 个模块"
            elif 'success_count' in result:
                details = f"{result['success_count']} 个成功"
            elif 'analyzed_count' in result:
                details = f"{result['analyzed_count']} 个模块"
            elif 'skill_name' in result:
                details = f"Skill: {result['skill_name']}"
            elif 'kb_path' in result:
                details = f"知识库已创建"
            else:
                details = "OK"

        table.add_row(stage_name, status, details)

    console.print(table)




@cli.command()
def status():
    """显示当前状态和已生成的知识库

    \b
    显示系统中已生成的所有知识库和 Skill。

    \b
    示例：
      ue5kb status
    """
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


# ============================================================================
# Pipeline 命令组
# ============================================================================

@cli.group()
def pipeline():
    """Pipeline 管理命令（五阶段架构）

    \b
    五阶段 Pipeline：
    1. discover - 发现所有模块
    2. extract - 提取模块依赖
    3. analyze - 分析代码结构
    4. build - 构建索引
    5. generate - 生成 Skill

    \b
    v2.10.0 并行加速：
    - 使用 --workers 或 -j 指定并行线程数
    - 0 = 自动检测 CPU 核心数（推荐）
    - 预期 4-8x 性能提升

    \b
    可用命令：
      ue5kb pipeline run              运行完整 Pipeline
      ue5kb pipeline status           查看各阶段完成状态
      ue5kb pipeline clean            清除特定阶段的输出
      ue5kb pipeline partitioned      分区模式（大型引擎）
      ue5kb pipeline partition-status 查看分区状态

    \b
    常用示例：
      # 运行完整 Pipeline（自动检测并行度）
      ue5kb pipeline run --engine-path "D:\\UE5"

      # 强制重新运行所有阶段
      ue5kb pipeline run --engine-path "D:\\UE5" --force

      # 指定并行 worker 数量
      ue5kb pipeline run --engine-path "D:\\UE5" --workers 8
      ue5kb pipeline run --engine-path "D:\\UE5" -j 4

      # 查看状态
      ue5kb pipeline status --engine-path "D:\\UE5"

      # 清除特定阶段
      ue5kb pipeline clean --engine-path "D:\\UE5" discover
      ue5kb pipeline clean --engine-path "D:\\UE5" --all

      # 分区模式（仅处理特定分区）
      ue5kb pipeline partitioned --engine-path "D:\\UE5" --partition runtime --partition editor
    """
    pass


@pipeline.command('run')
@click.option('--engine-path', type=click.Path(exists=True), required=True,
              help='UE5 引擎路径')
@click.option('--force', is_flag=True, help='强制重新运行所有阶段')
@click.option('--workers', '-j', type=int, default=0, help='并行工作线程数（0=自动检测，默认: 0）')
def pipeline_run(engine_path, force, workers):
    """运行完整 Pipeline

    \b
    按顺序执行所有阶段：discover → extract → analyze → build → generate
    已完成的阶段会自动跳过，使用 --force 强制重新运行。

    \b
    示例：
      ue5kb pipeline run --engine-path "D:\\UE5"
      ue5kb pipeline run --engine-path "D:\\UE5" --force
      ue5kb pipeline run --engine-path "D:\\UE5" --workers 4
      ue5kb pipeline run --engine-path "D:\\UE5" -j 0
    """
    from ue5_kb.pipeline.coordinator import PipelineCoordinator

    console.print(f"\n[bold cyan]=== Pipeline 运行 ===[/bold cyan]")
    console.print(f"引擎路径: {engine_path}")
    console.print(f"强制运行: {force}")
    console.print(f"并行度: {workers if workers > 0 else '自动检测'}\n")

    coordinator = PipelineCoordinator(Path(engine_path))

    try:
        results = coordinator.run_all(force=force, parallel=workers)

        # 显示结果摘要
        console.print(f"\n[bold green]=== Pipeline 完成 ===[/bold green]\n")

        table = Table()
        table.add_column("阶段")
        table.add_column("状态")
        table.add_column("详情")

        for stage_name, result in results.items():
            if result.get('skipped'):
                status = "[yellow]跳过[/yellow]"
                details = result.get('reason', '')
            elif result.get('error'):
                status = "[red]失败[/red]"
                details = result.get('error', '')[:50]
            else:
                status = "[green]成功[/green]"
                # 提取关键统计
                if 'total_count' in result:
                    details = f"{result['total_count']} 个模块"
                elif 'success_count' in result:
                    details = f"{result['success_count']} 个成功"
                elif 'analyzed_count' in result:
                    details = f"{result['analyzed_count']} 个模块"
                elif 'skill_name' in result:
                    details = f"Skill: {result['skill_name']}"
                else:
                    details = "OK"

            table.add_row(stage_name, status, details)

        console.print(table)

    except Exception as e:
        console.print(f"\n[bold red]Pipeline 失败: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@pipeline.command('status')
@click.option('--engine-path', type=click.Path(exists=True), required=True,
              help='UE5 引擎路径')
def pipeline_status(engine_path):
    """查看 Pipeline 状态

    \b
    显示各阶段的完成状态、完成时间和摘要信息。

    \b
    示例：
      ue5kb pipeline status --engine-path "D:\\UE5"
    """
    from ue5_kb.pipeline.coordinator import PipelineCoordinator

    coordinator = PipelineCoordinator(Path(engine_path))
    status = coordinator.get_status()

    console.print(f"\n[bold cyan]=== Pipeline 状态 ===[/bold cyan]")
    console.print(f"引擎路径: {status['base_path']}\n")

    # 创建表格
    table = Table()
    table.add_column("阶段")
    table.add_column("已完成")
    table.add_column("完成时间")
    table.add_column("摘要")

    for stage_name, stage_info in status['stages'].items():
        completed = "✓" if stage_info.get('completed') else "✗"

        state = stage_info.get('state', {})
        completed_at = state.get('completed_at', 'N/A') if state else 'N/A'
        if completed_at != 'N/A':
            # 格式化时间戳
            completed_at = completed_at.split('T')[0]  # 只显示日期

        # 提取摘要
        summary = state.get('result_summary', {}) if state else {}
        if summary:
            summary_str = ', '.join([f"{k}: {v}" for k, v in list(summary.items())[:2]])
            summary_str = summary_str[:40] + ('...' if len(summary_str) > 40 else '')
        else:
            summary_str = ''

        table.add_row(stage_name, completed, completed_at, summary_str)

    console.print(table)
    console.print()


@pipeline.command('clean')
@click.option('--engine-path', type=click.Path(exists=True), required=True,
              help='UE5 引擎路径')
@click.argument('stage_name', required=False)
@click.option('--all', is_flag=True, help='清除所有阶段')
def pipeline_clean(engine_path, stage_name, all):
    """清除特定阶段的输出

    \b
    清除指定阶段的输出文件，以便重新运行该阶段。
    可用阶段: discover, extract, analyze, build, generate

    \b
    示例：
      ue5kb pipeline clean --engine-path "D:\\UE5" discover
      ue5kb pipeline clean --engine-path "D:\\UE5" --all
    """
    from ue5_kb.pipeline.coordinator import PipelineCoordinator

    coordinator = PipelineCoordinator(Path(engine_path))

    if all:
        console.print(f"[yellow]清除所有阶段...[/yellow]")
        coordinator.clean_all()
        console.print(f"[green]已清除所有阶段[/green]")
    elif stage_name:
        try:
            coordinator.clean_stage(stage_name)
            console.print(f"[green]已清除阶段: {stage_name}[/green]")
        except ValueError as e:
            console.print(f"[red]错误: {e}[/red]")
            sys.exit(1)
    else:
        console.print(f"[red]错误: 请指定阶段名称或使用 --all[/red]")
        console.print(f"可用阶段: discover, extract, analyze, build, generate")
        sys.exit(1)


# ============================================================================
# 分区构建命令（Multi-Agent Partitioning）
# ============================================================================

@pipeline.command('partitioned')
@click.option('--engine-path', type=click.Path(exists=True), required=True,
              help='UE5 引擎路径')
@click.option('--partition', type=str, multiple=True,
              help='要处理的分区（可多次指定）。可选：runtime, editor, plugins, developer, platforms, programs')
@click.option('--parallel', is_flag=True, help='并行处理（暂未实现）')
def pipeline_partitioned(engine_path, partition, parallel):
    """使用分区模式构建（适用于大型引擎）

    \b
    分区模式将引擎分为6个独立的 partition：
    - runtime: Runtime 核心模块（~700个）
    - editor: Editor 编辑器模块（~600个）
    - plugins: Plugins 插件模块（~900个）
    - developer: Developer 开发工具模块
    - platforms: Platforms 平台模块
    - programs: Programs 独立程序模块

    \b
    示例：
      ue5kb pipeline partitioned --engine-path "D:\\UE5"  # 处理所有分区
      ue5kb pipeline partitioned --engine-path "D:\\UE5" --partition runtime --partition editor  # 仅处理指定分区
    """
    from ue5_kb.builders.partitioned_builder import PartitionedBuilder

    console.print(f"\n[bold cyan]=== 分区构建模式 ===[/bold cyan]")
    console.print(f"引擎路径: {engine_path}\n")

    builder = PartitionedBuilder(Path(engine_path))

    # 确定要处理的分区
    partitions_to_process = list(partition) if partition else None

    if partitions_to_process:
        console.print(f"处理分区: {', '.join(partitions_to_process)}")
    else:
        console.print(f"处理所有分区")

    try:
        result = builder.build_partitioned(
            partitions=partitions_to_process,
            parallel=parallel
        )

        # 显示结果
        console.print(f"\n[bold green]=== 分区构建完成 ===[/bold green]\n")

        table = Table()
        table.add_column("分区")
        table.add_column("状态")
        table.add_column("模块数")

        for partition_name, partition_result in result['partitions'].items():
            if 'error' in partition_result:
                status = "[red]失败[/red]"
                module_count = "N/A"
            else:
                status = "[green]成功[/green]"
                module_count = str(partition_result.get('module_count', 0))

            table.add_row(partition_name, status, module_count)

        console.print(table)

        # 显示合并统计
        merged = result.get('merged', {})
        console.print(f"\n总计:")
        console.print(f"  总模块数: {merged.get('total_modules', 0)}")
        console.print(f"  成功分区: {result.get('successful_partitions', 0)}/{result.get('total_partitions', 0)}")

    except Exception as e:
        console.print(f"\n[bold red]分区构建失败: {e}[/bold red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)


@pipeline.command('partition-status')
@click.option('--engine-path', type=click.Path(exists=True), required=True,
              help='UE5 引擎路径')
def pipeline_partition_status(engine_path):
    """查看分区构建状态

    \b
    显示各分区的完成状态和说明。

    \b
    示例：
      ue5kb pipeline partition-status --engine-path "D:\\UE5"
    """
    from ue5_kb.builders.partitioned_builder import PartitionedBuilder, PartitionConfig

    builder = PartitionedBuilder(Path(engine_path))
    status = builder.get_partition_status()

    console.print(f"\n[bold cyan]=== 分区状态 ===[/bold cyan]\n")

    table = Table()
    table.add_column("分区")
    table.add_column("已完成")
    table.add_column("说明")

    for partition_name, config in PartitionConfig.PARTITIONS.items():
        partition_status = status.get(partition_name, {})
        completed = "✓" if partition_status.get('completed') else "✗"
        description = config['description']

        table.add_row(partition_name, completed, description)

    console.print(table)
    console.print()


def main():
    """CLI 入口点"""
    cli()


if __name__ == '__main__':
    main()
