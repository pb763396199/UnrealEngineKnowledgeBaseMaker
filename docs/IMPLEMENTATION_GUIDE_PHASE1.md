# 架构升级实施指南 - 第一阶段（Pipeline 重构）

> 快速开始指南：2-3天完成 Pipeline 架构重构

---

## 目标

将当前的单体构建流程重构为五阶段 Pipeline：

```
discover → extract → analyze → build → generate
```

---

## 文件结构变更

### 新增文件

```
ue5_kb/
├── pipeline/                      # 新增：Pipeline 模块
│   ├── __init__.py
│   ├── base.py                   # 基类：PipelineStage
│   ├── discover.py               # 阶段 1：发现模块
│   ├── extract.py                # 阶段 2：提取依赖
│   ├── analyze.py                # 阶段 3：分析代码
│   ├── build.py                  # 阶段 4：构建索引
│   ├── generate.py               # 阶段 5：生成 Skill
│   ├── coordinator.py            # Pipeline 协调器
│   └── state.py                  # 状态管理
└── cli.py                         # 修改：添加 pipeline 子命令
```

### 修改的文件

```
ue5_kb/cli.py                      # 添加 `ue5kb pipeline` 命令组
ue5_kb/builders/global_index_builder.py  # 重构为使用 Pipeline
```

---

## 实施步骤

### Step 1: 创建 Pipeline 基类（30分钟）

**文件：`ue5_kb/pipeline/base.py`**

```python
"""
Pipeline 基类

所有 Pipeline 阶段的基类
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional
import json
from datetime import datetime


class PipelineStage(ABC):
    """
    Pipeline 阶段基类

    每个阶段必须实现：
    - stage_name: 阶段名称
    - run(): 执行逻辑
    - is_completed(): 检查是否完成
    """

    def __init__(self, base_path: Path):
        """
        初始化阶段

        Args:
            base_path: 引擎/插件根目录
        """
        self.base_path = Path(base_path)
        self.data_dir = self.base_path / "data"
        self.stage_dir = self.data_dir / self.stage_name

    @property
    @abstractmethod
    def stage_name(self) -> str:
        """阶段名称（discover, extract, analyze, build, generate）"""
        pass

    @abstractmethod
    def run(self, **kwargs) -> Dict[str, Any]:
        """
        执行阶段

        Returns:
            执行结果（包含统计信息）
        """
        pass

    def is_completed(self) -> bool:
        """
        检查阶段是否已完成

        Returns:
            True 如果输出文件存在
        """
        return self.get_output_path().exists()

    @abstractmethod
    def get_output_path(self) -> Path:
        """
        获取输出文件路径

        Returns:
            输出文件的路径
        """
        pass

    def clean(self) -> None:
        """清除阶段输出（用于重新运行）"""
        import shutil
        if self.stage_dir.exists():
            shutil.rmtree(self.stage_dir)

    def save_result(self, result: Dict[str, Any], filename: str = "result.json") -> None:
        """
        保存结果到文件

        Args:
            result: 结果字典
            filename: 文件名
        """
        self.stage_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.stage_dir / filename

        # 添加元数据
        result['_metadata'] = {
            'stage': self.stage_name,
            'completed_at': datetime.now().isoformat(),
            'base_path': str(self.base_path)
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    def load_result(self, filename: str = "result.json") -> Optional[Dict[str, Any]]:
        """
        加载之前的结果

        Args:
            filename: 文件名

        Returns:
            结果字典，如果不存在则返回 None
        """
        result_path = self.stage_dir / filename
        if not result_path.exists():
            return None

        with open(result_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} stage='{self.stage_name}' completed={self.is_completed()}>"
```

### Step 2: 实现第一个阶段（Discover）（1小时）

**文件：`ue5_kb/pipeline/discover.py`**

```python
"""
Pipeline 阶段 1: Discover (发现模块)

扫描引擎目录，发现所有 .Build.cs 文件
"""

from pathlib import Path
from typing import Dict, Any, List
from .base import PipelineStage


class DiscoverStage(PipelineStage):
    """
    发现阶段

    扫描 Engine 目录，查找所有 .Build.cs 文件
    """

    @property
    def stage_name(self) -> str:
        return "discover"

    def get_output_path(self) -> Path:
        return self.stage_dir / "modules.json"

    def run(self, **kwargs) -> Dict[str, Any]:
        """
        发现所有模块

        Returns:
            包含模块列表的结果
        """
        print(f"[Discover] 扫描模块...")

        engine_dir = self.base_path / "Engine"
        if not engine_dir.exists():
            raise FileNotFoundError(f"引擎目录不存在: {engine_dir}")

        # 查找所有 .Build.cs 文件
        modules = self._discover_modules(engine_dir)

        result = {
            'modules': modules,
            'total_count': len(modules)
        }

        # 保存结果
        self.save_result(result, "modules.json")

        print(f"[Discover] 完成！发现 {len(modules)} 个模块")

        return result

    def _discover_modules(self, engine_dir: Path) -> List[Dict[str, str]]:
        """
        递归查找所有 .Build.cs 文件

        Args:
            engine_dir: 引擎目录

        Returns:
            模块列表
        """
        modules = []

        for build_cs in engine_dir.rglob('**/*.Build.cs'):
            # 提取模块名
            module_name = build_cs.stem.replace('.Build', '')

            # 推断分类
            category = self._infer_category(build_cs)

            modules.append({
                'name': module_name,
                'path': str(build_cs.relative_to(self.base_path)),
                'category': category,
                'absolute_path': str(build_cs)
            })

        return sorted(modules, key=lambda m: m['name'])

    def _infer_category(self, build_cs_path: Path) -> str:
        """
        从路径推断模块分类

        Args:
            build_cs_path: .Build.cs 文件路径

        Returns:
            分类标签
        """
        path_str = str(build_cs_path)

        if '/Source/Runtime/' in path_str or '\\Source\\Runtime\\' in path_str:
            return 'Runtime'
        elif '/Source/Editor/' in path_str or '\\Source\\Editor\\' in path_str:
            return 'Editor'
        elif '/Source/Developer/' in path_str or '\\Source\\Developer\\' in path_str:
            return 'Developer'
        elif '/Source/Programs/' in path_str or '\\Source\\Programs\\' in path_str:
            return 'Programs'
        elif '/Plugins/' in path_str or '\\Plugins\\' in path_str:
            # 提取插件类型和名称
            return self._extract_plugin_category(path_str)
        elif '/Platforms/' in path_str or '\\Platforms\\' in path_str:
            # 提取平台名称
            return self._extract_platform_category(path_str)
        else:
            return 'Unknown'

    def _extract_plugin_category(self, path_str: str) -> str:
        """提取插件分类（Plugins.Type.Name）"""
        import re
        # 匹配 Plugins/{Type}/{Name}
        pattern = r'[/\\]Plugins[/\\]([^/\\]+)[/\\]([^/\\]+)'
        match = re.search(pattern, path_str)
        if match:
            plugin_type = match.group(1)
            plugin_name = match.group(2)
            return f'Plugins.{plugin_type}.{plugin_name}'
        return 'Plugins.Unknown'

    def _extract_platform_category(self, path_str: str) -> str:
        """提取平台分类（Platforms.PlatformName）"""
        import re
        pattern = r'[/\\]Platforms[/\\]([^/\\]+)'
        match = re.search(pattern, path_str)
        if match:
            platform = match.group(1)
            return f'Platforms.{platform}'
        return 'Platforms.Unknown'
```

### Step 3: 实现 Extract 阶段（1小时）

**文件：`ue5_kb/pipeline/extract.py`**

```python
"""
Pipeline 阶段 2: Extract (提取依赖)

解析 .Build.cs 文件，提取模块依赖关系
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from .base import PipelineStage
from ..parsers.buildcs_parser import BuildCsParser


class ExtractStage(PipelineStage):
    """
    提取阶段

    解析每个模块的 .Build.cs 文件，提取依赖关系
    """

    @property
    def stage_name(self) -> str:
        return "extract"

    def get_output_path(self) -> Path:
        # Extract 阶段的输出是目录（包含多个文件）
        return self.stage_dir

    def is_completed(self) -> bool:
        # 检查 extract/ 目录是否存在且非空
        if not self.stage_dir.exists():
            return False

        # 检查是否有至少一个模块目录
        module_dirs = list(self.stage_dir.iterdir())
        return len(module_dirs) > 0

    def run(self, **kwargs) -> Dict[str, Any]:
        """
        提取所有模块的依赖关系

        Returns:
            包含提取统计的结果
        """
        # 加载 discover 阶段的结果
        discover_result = self._load_discover_result()
        if not discover_result:
            raise RuntimeError("Discover 阶段未完成，请先运行 discover")

        modules = discover_result['modules']

        print(f"[Extract] 提取 {len(modules)} 个模块的依赖...")

        parser = BuildCsParser()
        success_count = 0
        failed_modules = []

        for module in modules:
            try:
                # 解析 .Build.cs 文件
                dependencies = parser.parse_file(module['absolute_path'])

                # 保存到单独的文件
                self._save_module_dependencies(module['name'], dependencies)

                success_count += 1

            except Exception as e:
                print(f"  警告: 解析 {module['name']} 失败: {e}")
                failed_modules.append({
                    'name': module['name'],
                    'error': str(e)
                })

        result = {
            'total_modules': len(modules),
            'success_count': success_count,
            'failed_count': len(failed_modules),
            'failed_modules': failed_modules
        }

        # 保存摘要
        self.save_result(result, "summary.json")

        print(f"[Extract] 完成！成功: {success_count}, 失败: {len(failed_modules)}")

        return result

    def _load_discover_result(self) -> Optional[Dict[str, Any]]:
        """加载 discover 阶段的结果"""
        discover_dir = self.data_dir / "discover"
        modules_file = discover_dir / "modules.json"

        if not modules_file.exists():
            return None

        import json
        with open(modules_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _save_module_dependencies(self, module_name: str, dependencies: Dict[str, Any]) -> None:
        """
        保存单个模块的依赖信息

        Args:
            module_name: 模块名
            dependencies: 依赖字典
        """
        module_dir = self.stage_dir / module_name
        module_dir.mkdir(parents=True, exist_ok=True)

        output_file = module_dir / "dependencies.json"

        import json
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(dependencies, f, indent=2, ensure_ascii=False)
```

### Step 4: 实现 Pipeline 协调器（1小时）

**文件：`ue5_kb/pipeline/coordinator.py`**

```python
"""
Pipeline 协调器

管理 Pipeline 的执行流程
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from .discover import DiscoverStage
from .extract import ExtractStage
# from .analyze import AnalyzeStage  # TODO: 后续实现
# from .build import BuildStage      # TODO: 后续实现
# from .generate import GenerateStage # TODO: 后续实现
from .state import PipelineState


class PipelineCoordinator:
    """
    Pipeline 协调器

    管理 Pipeline 各阶段的执行
    """

    STAGES = ['discover', 'extract', 'analyze', 'build', 'generate']

    def __init__(self, base_path: Path):
        """
        初始化协调器

        Args:
            base_path: 引擎/插件根目录
        """
        self.base_path = Path(base_path)
        self.state = PipelineState(base_path)

        # 初始化各阶段
        self.stages = {
            'discover': DiscoverStage(base_path),
            'extract': ExtractStage(base_path),
            # 'analyze': AnalyzeStage(base_path),  # TODO
            # 'build': BuildStage(base_path),      # TODO
            # 'generate': GenerateStage(base_path) # TODO
        }

    def run_all(self, force: bool = False) -> Dict[str, Any]:
        """
        运行完整 Pipeline

        Args:
            force: 是否强制重新运行已完成的阶段

        Returns:
            包含所有阶段结果的字典
        """
        results = {}

        for stage_name in self.STAGES:
            if stage_name not in self.stages:
                print(f"[Pipeline] 跳过未实现的阶段: {stage_name}")
                continue

            result = self.run_stage(stage_name, force=force)
            results[stage_name] = result

        return results

    def run_stage(self, stage_name: str, force: bool = False) -> Dict[str, Any]:
        """
        运行特定阶段

        Args:
            stage_name: 阶段名称
            force: 是否强制重新运行

        Returns:
            阶段结果
        """
        if stage_name not in self.stages:
            raise ValueError(f"未知的阶段: {stage_name}")

        stage = self.stages[stage_name]

        # 检查是否已完成
        if stage.is_completed() and not force:
            print(f"[Pipeline] 阶段 '{stage_name}' 已完成，跳过")
            return {'skipped': True, 'reason': 'already completed'}

        # 运行阶段
        print(f"[Pipeline] 运行阶段: {stage_name}")

        try:
            result = stage.run()

            # 更新状态
            self.state.mark_completed(stage_name, result)

            return result

        except Exception as e:
            print(f"[Pipeline] 阶段 '{stage_name}' 失败: {e}")
            self.state.mark_failed(stage_name, str(e))
            raise

    def get_status(self) -> Dict[str, Any]:
        """
        获取 Pipeline 状态

        Returns:
            包含各阶段状态的字典
        """
        status = {
            'base_path': str(self.base_path),
            'stages': {}
        }

        for stage_name in self.STAGES:
            if stage_name not in self.stages:
                status['stages'][stage_name] = {'implemented': False}
                continue

            stage = self.stages[stage_name]
            stage_state = self.state.get_stage_state(stage_name)

            status['stages'][stage_name] = {
                'implemented': True,
                'completed': stage.is_completed(),
                'state': stage_state
            }

        return status

    def clean_stage(self, stage_name: str) -> None:
        """
        清除特定阶段的输出

        Args:
            stage_name: 阶段名称
        """
        if stage_name not in self.stages:
            raise ValueError(f"未知的阶段: {stage_name}")

        stage = self.stages[stage_name]
        stage.clean()

        # 清除状态
        self.state.clear_stage(stage_name)

        print(f"[Pipeline] 已清除阶段: {stage_name}")
```

### Step 5: 实现状态管理（30分钟）

**文件：`ue5_kb/pipeline/state.py`**

```python
"""
Pipeline 状态管理

管理 .pipeline_state 文件
"""

from pathlib import Path
from typing import Dict, Any, Optional
import json
from datetime import datetime


class PipelineState:
    """
    Pipeline 状态管理器

    管理 .pipeline_state 文件
    """

    def __init__(self, base_path: Path):
        """
        初始化状态管理器

        Args:
            base_path: 引擎/插件根目录
        """
        self.base_path = Path(base_path)
        self.state_file = self.base_path / ".pipeline_state"
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """加载状态文件"""
        if not self.state_file.exists():
            return self._create_initial_state()

        with open(self.state_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _create_initial_state(self) -> Dict[str, Any]:
        """创建初始状态"""
        return {
            'version': '2.0',
            'created_at': datetime.now().isoformat(),
            'stages': {}
        }

    def _save_state(self) -> None:
        """保存状态文件"""
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def mark_completed(self, stage_name: str, result: Dict[str, Any]) -> None:
        """
        标记阶段完成

        Args:
            stage_name: 阶段名称
            result: 阶段结果
        """
        self.state['stages'][stage_name] = {
            'completed': True,
            'completed_at': datetime.now().isoformat(),
            'result_summary': self._extract_summary(result)
        }
        self._save_state()

    def mark_failed(self, stage_name: str, error: str) -> None:
        """
        标记阶段失败

        Args:
            stage_name: 阶段名称
            error: 错误信息
        """
        self.state['stages'][stage_name] = {
            'completed': False,
            'failed_at': datetime.now().isoformat(),
            'error': error
        }
        self._save_state()

    def get_stage_state(self, stage_name: str) -> Optional[Dict[str, Any]]:
        """
        获取阶段状态

        Args:
            stage_name: 阶段名称

        Returns:
            阶段状态，如果不存在则返回 None
        """
        return self.state['stages'].get(stage_name)

    def clear_stage(self, stage_name: str) -> None:
        """
        清除阶段状态

        Args:
            stage_name: 阶段名称
        """
        if stage_name in self.state['stages']:
            del self.state['stages'][stage_name]
            self._save_state()

    def _extract_summary(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """提取结果摘要（避免存储过大的数据）"""
        summary = {}

        # 提取关键指标
        for key in ['total_count', 'success_count', 'failed_count', 'modules_processed']:
            if key in result:
                summary[key] = result[key]

        return summary
```

### Step 6: 更新 CLI（1小时）

**文件：`ue5_kb/cli.py`（添加 pipeline 命令组）**

```python
@cli.group()
def pipeline():
    """Pipeline 管理命令"""
    pass


@pipeline.command('run')
@click.option('--engine-path', type=click.Path(exists=True), required=True,
              help='UE5 引擎路径')
@click.option('--force', is_flag=True, help='强制重新运行所有阶段')
def pipeline_run(engine_path, force):
    """运行完整 Pipeline"""
    from ue5_kb.pipeline.coordinator import PipelineCoordinator

    console.print(f"\n[bold cyan]运行 Pipeline[/bold cyan]")
    console.print(f"引擎路径: {engine_path}\n")

    coordinator = PipelineCoordinator(Path(engine_path))

    try:
        results = coordinator.run_all(force=force)

        console.print("\n[bold green]Pipeline 完成![/bold green]")
        console.print(f"结果: {results}")

    except Exception as e:
        console.print(f"\n[bold red]Pipeline 失败: {e}[/bold red]")
        raise


@pipeline.command('status')
@click.option('--engine-path', type=click.Path(exists=True), required=True,
              help='UE5 引擎路径')
def pipeline_status(engine_path):
    """查看 Pipeline 状态"""
    from ue5_kb.pipeline.coordinator import PipelineCoordinator

    coordinator = PipelineCoordinator(Path(engine_path))
    status = coordinator.get_status()

    console.print("\n[bold cyan]Pipeline 状态[/bold cyan]\n")

    # 创建表格
    from rich.table import Table
    table = Table()
    table.add_column("阶段")
    table.add_column("已实现")
    table.add_column("已完成")
    table.add_column("完成时间")

    for stage_name, stage_info in status['stages'].items():
        implemented = "✓" if stage_info.get('implemented') else "✗"
        completed = "✓" if stage_info.get('completed') else "✗"

        state = stage_info.get('state', {})
        completed_at = state.get('completed_at', 'N/A') if state else 'N/A'

        table.add_row(stage_name, implemented, completed, completed_at)

    console.print(table)


@pipeline.command('clean')
@click.option('--engine-path', type=click.Path(exists=True), required=True,
              help='UE5 引擎路径')
@click.argument('stage_name')
def pipeline_clean(engine_path, stage_name):
    """清除特定阶段的输出"""
    from ue5_kb.pipeline.coordinator import PipelineCoordinator

    coordinator = PipelineCoordinator(Path(engine_path))

    try:
        coordinator.clean_stage(stage_name)
        console.print(f"[green]已清除阶段: {stage_name}[/green]")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
```

---

## 测试

### 测试 Discover 阶段

```bash
# 创建测试目录
mkdir -p /j/test_pipeline

# 运行 discover
ue5kb pipeline run --engine-path "D:\Unreal Engine\UnrealEngine51_500"

# 检查输出
cat "D:\Unreal Engine\UnrealEngine51_500\data\discover\modules.json"

# 查看状态
ue5kb pipeline status --engine-path "D:\Unreal Engine\UnrealEngine51_500"
```

### 测试 Extract 阶段

```bash
# Extract 会自动在 Discover 完成后运行
# 或者单独运行
ue5kb pipeline run --engine-path "D:\Unreal Engine\UnrealEngine51_500"

# 检查输出
ls "D:\Unreal Engine\UnrealEngine51_500\data\extract\"

# 查看某个模块的依赖
cat "D:\Unreal Engine\UnrealEngine51_500\data\extract\Core\dependencies.json"
```

### 测试幂等性

```bash
# 第一次运行
ue5kb pipeline run --engine-path "D:\Unreal Engine\UnrealEngine51_500"

# 第二次运行（应该跳过已完成的阶段）
ue5kb pipeline run --engine-path "D:\Unreal Engine\UnrealEngine51_500"

# 输出应该显示：
# [Pipeline] 阶段 'discover' 已完成，跳过
# [Pipeline] 阶段 'extract' 已完成，跳过
```

### 测试清除和重跑

```bash
# 清除 extract 阶段
ue5kb pipeline clean --engine-path "D:\Unreal Engine\UnrealEngine51_500" extract

# 重新运行 extract
ue5kb pipeline run --engine-path "D:\Unreal Engine\UnrealEngine51_500"
```

---

## 下一步

完成第一阶段后：

1. **实现 Analyze 阶段**（类似 Extract，但解析 C++ 文件）
2. **实现 Build 阶段**（转换 JSON → SQLite + Pickle）
3. **实现 Generate 阶段**（从模板生成 Skill）
4. **集成到现有的 `ue5kb init` 命令**（作为默认流程）

---

## 常见问题

### Q: 为什么要分这么多阶段？

A: 分阶段的好处：
- 调试时只需重跑失败的阶段
- 可以并行化（Extract 和 Analyze 可以并行）
- 中间结果可读（JSON 格式）
- 支持增量更新

### Q: 性能会变差吗？

A: 不会。虽然多了文件 I/O，但：
- JSON 序列化很快
- 减少了重复工作（增量更新）
- 可以跳过已完成的阶段

### Q: 如何与现有代码兼容？

A: 保留旧的 `ue5kb init` 命令，添加新的 `ue5kb pipeline` 命令。用户可以选择使用哪个。

---

## 总结

第一阶段实施完成后，你将拥有：

✅ 五阶段 Pipeline 架构（前两个阶段已实现）
✅ 幂等性设计（可重复运行）
✅ 状态管理（`.pipeline_state` 文件）
✅ 独立运行每个阶段的能力
✅ 清晰的中间输出（JSON 文件）

**下一步**: 实现剩余的三个阶段（Analyze, Build, Generate）
