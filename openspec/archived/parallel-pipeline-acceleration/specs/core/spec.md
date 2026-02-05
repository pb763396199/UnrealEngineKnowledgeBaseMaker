# 并行处理规范

## 概述

本规范定义 UE5 Knowledge Base Maker 的并行处理策略，包括进程池、线程池的使用，以及进度显示和错误处理。

## 并行策略

### 阶段并行策略

| 阶段 | 并行类型 | Worker 类型 | 理由 |
|------|----------|-------------|------|
| Discover | 串行 | N/A | I/O 密集但依赖递归扫描 |
| Extract | 进程池 | `ProcessPoolExecutor` | CPU 密集（正则解析），模块独立 |
| Analyze | 进程池 | `ProcessPoolExecutor` | CPU 极其密集，模块独立 |
| Build | 混合 | 线程池(图) + 串行(DB) | 图构建可并行，SQLite 必须串行 |
| Generate | 串行 | N/A | I/O 密集但文件少 |

### Worker 数量

```python
def get_worker_count(requested: int) -> int:
    """
    确定实际 worker 数量

    规则：
    1. requested = 0: 自动检测，使用 os.cpu_count()
    2. requested < 0: 视为 0（自动检测）
    3. requested > 0: 使用请求的值，但不超过 max_workers
    """
    if requested <= 0:
        return os.cpu_count() or 4
    return min(requested, max_workers)
```

## 进度显示

### 进度条层级

1. **总进度条**: 显示整体完成度
2. **Worker 进度条**: 每个并行 worker 一个进度条
3. **当前任务**: 动态显示当前处理的模块/文件名

### 进度更新频率

- 总进度: 每个 item 完成时更新
- Worker 进度: 每 10 个文件或完成时更新
- ETA: 每秒重新计算

### 错误显示

只显示错误日志，正常输出不显示：
- 错误汇总在进度条下方
- 每个错误显示：模块名、错误类型、错误信息

## 错误处理

### 错误隔离

单个模块失败不影响其他模块：
```python
try:
    result = worker.process(module)
    if result['status'] == 'success':
        tracker.increment_total()
    else:
        tracker.add_error(module, result['error'], result['error_type'])
        tracker.increment_total()
except Exception as e:
    tracker.add_error(module, str(e), type(e).__name__)
    tracker.increment_total()
```

### Checkpoint 机制

支持中断恢复：
- 每完成一个模块保存 checkpoint
- 重启时跳过已完成的模块
- checkpoint 文件: `{stage_dir}/.checkpoint`

## 性能监控

### 计时指标

```python
{
    'stages': {
        'discover': {
            'elapsed': 4.23,        # 秒
            'items_processed': 1757,
            'items_total': 1757,
            'speed': 415.37,        # items/sec
            'errors': 0
        },
        # ...
    },
    'total_elapsed': 194.90,
    'pipeline_elapsed': 194.90
}
```

### 输出格式

```
============================================================
Pipeline Performance Summary
============================================================

DISCOVER:
  Elapsed:     4.23s
  Processed:   1757/1757
  Speed:       415.37 items/sec

ANALYZE:
  Elapsed:     145.32s
  Processed:   1755/1757
  Speed:       12.08 items/sec
  Errors:      2

============================================================
Total Pipeline Time: 194.90s (3.25 min)
============================================================
```

## 线程安全

### 共享状态

- `ProgressTracker`: 使用 `threading.Lock` 保护
- `CheckpointManager`: 文件锁或原子操作
- `StageTimer`: 只读访问，无需锁

### 不可变数据

Worker 函数只接收不可变参数，返回可序列化结果。

## 兼容性

### Python 版本

- 最低要求: Python 3.9
- 推荐版本: Python 3.10+

### 平台

- Windows: 完全支持
- Linux: 完全支持
- macOS: 完全支持（spawn 模式）
