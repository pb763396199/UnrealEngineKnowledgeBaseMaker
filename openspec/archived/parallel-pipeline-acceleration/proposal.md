# Change: Parallel Pipeline Acceleration with Multi-Progress Display

## ID
parallel-pipeline-acceleration

## Status
IMPLEMENTED

## Created
2026-02-05

## Why

当前 UE5 Knowledge Base Maker 创建知识库的速度太慢，处理完整的 UE5 引擎（1757+ 模块）需要 10-15 分钟。主要瓶颈在于：

### 瓶颈 1: Analyze 阶段（最耗时）
- **问题**: 串行处理 1757+ 个模块，每个模块需解析数百个 C++ 源文件
- **耗时**: 约 600 秒（10 分钟）
- **原因**: C++ 正则解析是 CPU 密集型操作，单进程无法充分利用多核 CPU

### 瓶颈 2: Extract 阶段
- **问题**: 串行解析 .Build.cs 文件
- **耗时**: 约 30 秒
- **原因**: 虽然单个文件解析快，但数量巨大

### 瓶颈 3: 用户体验问题
- **问题 1**: 没有实时进度条，只有数字显示
- **问题 2**: 无法看到并行处理的状态
- **问题 3**: 所有日志都输出，正常输出淹没错误信息
- **问题 4**: 没有各阶段和总耗时的统计

## What Changes

### 1. 新增 Utils 模块

创建 `ue5_kb/utils/` 目录，添加以下工具类：

#### 1.1 ProgressTracker (`ue5_kb/utils/progress_tracker.py`)

多进度条跟踪器，使用 `rich.progress` 实现：

```python
class ProgressTracker:
    """多进度条跟踪器

    特性：
    - 支持多个 worker 的独立进度条
    - 总进度汇总
    - 错误收集和展示
    - 速度统计和 ETA 计算
    """

    def __init__(self, stage_name: str, total_items: int, num_workers: int, console: Console)
    def start(self) -> None
    def update_worker(self, worker_id: int, current_task: str, completed: int, total: int) -> None
    def increment_total(self, count: int = 1) -> None
    def add_error(self, module: str, error: str, error_type: str) -> None
    def stop(self) -> Dict[str, Any]
```

**UI 设计**:
```
┌─ Pipeline: Analyze Stage ──────────────────────────────────────────────┐
│                                                                         │
│  [████████████████████████░░░░░░░░░░░░░░░░░░░░░░░] 453/1757 modules  │
│  Total Progress                                                    26% │
│                                                                         │
│  [██████████████████████████████████░░░░░] Core/Engine.cpp            │
│  Worker 1                                                   128/150   │
│                                                                         │
│  [██████████████████████████████████░░░░░] RenderCore/Light.cpp       │
│  Worker 2                                            89/150           │
│                                                                         │
│  Speed: 127 modules/sec | ETA: 10.2s | Elapsed: 45.3s                  │
│  Errors: 2                                                              │
│    - MyPlugin1.Module: UnicodeDecodeError                              │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 1.2 StageTimer (`ue5_kb/utils/stage_timer.py`)

阶段计时器，跟踪各阶段耗时：

```python
class StageTimer:
    """Pipeline 阶段计时器"""

    def start_pipeline(self) -> None
    def end_pipeline(self) -> None
    def start_stage(self, stage_name: str, total_items: int = 0) -> None
    def end_stage(self, stage_name: str, items_processed: int = 0, errors: int = 0) -> None
    def get_summary(self) -> Dict[str, Any]
    def format_summary(self) -> str
```

#### 1.3 CheckpointManager (`ue5_kb/utils/checkpoint_manager.py`)

Checkpoint 管理器，支持中断恢复：

```python
class CheckpointManager:
    """Checkpoint 管理器"""

    def load(self) -> Dict[str, Any]
    def save_completed(self, task_id: str, result: Dict[str, Any]) -> None
    def save_failed(self, task_id: str, error: str, error_type: str) -> None
    def get_completed_tasks(self) -> set
    def clear(self) -> None
```

### 2. AnalyzeStage 并行化

#### 2.1 新增文件: `ue5_kb/pipeline/analyze_parallel.py`

```python
def _analyze_module_worker(args: Tuple) -> Dict[str, Any]:
    """
    Worker 函数：分析单个模块（在独立进程中执行）

    Returns:
        包含分析结果的字典
    """

class ParallelAnalyzeStage:
    """并行分析阶段"""

    def __init__(self, base_path: Path, num_workers: Optional[int] = None)
    def run(self, modules: List[Dict[str, Any]], force: bool = False, verbose: bool = False) -> Dict[str, Any]
```

#### 2.2 修改文件: `ue5_kb/pipeline/analyze.py`

在 `AnalyzeStage.run()` 方法中添加并行分支：

```python
def run(self, parallel: int = 1, verbose: bool = False, **kwargs) -> Dict[str, Any]:
    # 确定并行度
    if parallel == 0:  # auto
        parallel = os.cpu_count() or 4

    # 如果并行度 > 1，使用并行模式
    if parallel > 1:
        from .analyze_parallel import ParallelAnalyzeStage
        parallel_stage = ParallelAnalyzeStage(self.base_path, num_workers=parallel)
        return parallel_stage.run(modules, force=False, verbose=verbose)

    # 否则使用原有的串行逻辑
    return self._run_serial(modules, verbose)
```

### 3. ExtractStage 并行化

#### 3.1 新增文件: `ue5_kb/pipeline/extract_parallel.py`

类似 AnalyzeStage 的设计，使用 `ProcessPoolExecutor` 并行解析 .Build.cs 文件。

#### 3.2 修改文件: `ue5_kb/pipeline/extract.py`

添加并行分支。

### 4. BuildStage 混合并行化

#### 4.1 新增文件: `ue5_kb/pipeline/build_parallel.py`

使用混合策略：
- **NetworkX 图构建**: 使用 `ThreadPoolExecutor` 并行
- **SQLite 写入**: 保持串行
- **Pickle 序列化**: 可并行

#### 4.2 修改文件: `ue5_kb/pipeline/build.py`

添加混合并行分支。

### 5. PipelineCoordinator 集成

#### 5.1 修改文件: `ue5_kb/pipeline/coordinator.py`

集成 `StageTimer`，修改 `run_all()` 方法：

```python
def run_all(self, force: bool = False, workers: int = 0, **kwargs) -> Dict[str, Any]:
    """运行完整 Pipeline（带性能监控）"""
    self.timer.start_pipeline()
    results = {}

    # 自动检测并行度
    if workers == 0:
        workers = os.cpu_count() or 4

    for stage_name in self.STAGES:
        try:
            # ... 执行阶段 ...

            # 显示阶段耗时
            elapsed = self.timer.get_stage_metrics(stage_name).elapsed
            console.print(f"[cyan]✓ {stage_name} 完成 ({elapsed:.2f}s)[/cyan]")

        except Exception as e:
            # ... 错误处理 ...

    self.timer.end_pipeline()

    # 显示总耗时
    self._display_performance_summary()

    return results
```

### 6. CLI 参数更新

#### 6.1 修改文件: `ue5_kb/cli.py`

将 `--parallel` 参数改为 `--workers`，更符合约定：

```python
# 修改前 (第 72-73 行)
@click.option('--parallel', type=int, default=1,
              help='并行度（用于 analyze 阶段，默认: 1）')

# 修改后
@click.option('--workers', '-j', type=int, default=0,
              help='并行工作线程数（0=自动检测 CPU 核心数，默认: 0）')
```

更新所有使用该参数的地方。

### 7. 配置文件更新

#### 7.1 修改文件: `ue5_kb/core/config.py`

添加 `parallel` 配置节：

```python
default_config = {
    # ... 现有配置 ...
    'parallel': {
        'enabled': True,
        'workers': 0,  # 0 = 自动检测
        'max_workers': 16,  # 最大 worker 数限制
        'min_workers': 1,   # 最小 worker 数
    },
    # ... 其他配置 ...
}
```

## Impact

### Affected specs
- `specs/core/pipeline/parallel-processing-spec.md` - 新增：并行处理规范

### Affected code

**新增文件**:
- `ue5_kb/utils/__init__.py`
- `ue5_kb/utils/progress_tracker.py`
- `ue5_kb/utils/stage_timer.py`
- `ue5_kb/utils/checkpoint_manager.py`
- `ue5_kb/pipeline/analyze_parallel.py`
- `ue5_kb/pipeline/extract_parallel.py`
- `ue5_kb/pipeline/build_parallel.py`

**修改文件**:
- `ue5_kb/pipeline/analyze.py` - 添加并行模式分支
- `ue5_kb/pipeline/extract.py` - 添加并行模式分支
- `ue5_kb/pipeline/build.py` - 添加混合并行模式分支
- `ue5_kb/pipeline/coordinator.py` - 集成 StageTimer
- `ue5_kb/core/config.py` - 添加 parallel 配置
- `ue5_kb/cli.py` - 更新参数

### Backward compatibility
- CLI 参数 `--parallel` 改为 `--workers`（破坏性变更）
- 输出格式变更：添加进度条和耗时统计

**迁移指南**:
```bash
# 旧版本
ue5kb init --engine-path "D:\UE5" --parallel 4

# 新版本
ue5kb init --engine-path "D:\UE5" --workers 4
ue5kb init --engine-path "D:\UE5" -j 0  # 自动检测
```

### Performance impact

**预期性能提升** (8 核 CPU):

| 阶段 | 串行耗时 | 并行耗时 | 加速比 |
|------|----------|----------|--------|
| Discover | ~5s | ~5s | 1x |
| Extract | ~30s | ~8s | 3.8x |
| **Analyze** | ~600s | ~80s | **7.5x** |
| Build | ~120s | ~35s | 3.4x |
| Generate | ~5s | ~5s | 1x |
| **总计** | **~760s** | **~133s** | **5.7x** |

### 引擎模式和插件模式兼容性

两种模式都支持并行加速，代码逻辑完全相同。

## Testing Plan

### 单元测试
- 测试 `ProgressTracker` 多进度条更新
- 测试 `StageTimer` 耗时统计
- 测试 `CheckpointManager` 保存/加载

### 集成测试

#### 小规模测试（10-20 模块）
```bash
ue5kb init --engine-path "D:\UE5" --workers 4 --stage analyze
```
验证：
- 进度条正常显示
- 并行 worker 正常工作
- 错误被正确捕获

#### 中等规模测试（100-200 模块）
```bash
ue5kb init --engine-path "D:\UE5" --workers 0
```
验证：
- 自动检测并行度
- 性能提升符合预期

#### 完整测试（1757+ 模块）
```bash
ue5kb init --engine-path "D:\UE5" --force
```
验证：
- 端到端流程正常
- 总耗时统计正确
- checkpoint 恢复功能

### 性能基准测试

对比串行和并行的总耗时，验证加速比达到预期。

## References

- 计划文件: `C:\Users\pb763\.claude\plans\vast-gliding-feather.md`
- CLAUDE.md: 项目开发指导
- Rich Progress 文档: https://rich.readthedocs.io/en/stable/progress.html
