"""
Pipeline 阶段 4: Build 并行实现（混合模式）

使用线程池并行构建 NetworkX 图，串行处理 SQLite 写入
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import json
import os
import pickle
import networkx as nx

from ..core.config import Config
from ..core.global_index import GlobalIndex
from ..core.optimized_index import OptimizedGlobalIndex
from ..utils.progress_tracker import ProgressTracker
from rich.console import Console


def _fix_multi_json_file(file_path: Path) -> None:
    """
    检测并修复包含多个 JSON 对象的文件

    如果文件包含多个 JSON 对象串联（如 {}{}），只保留第一个
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 检查是否包含多个顶层 JSON 对象
        # 使用正则表达式找到第一个完整的 JSON 对象
        # 通过匹配大括号来找到第一个对象
        brace_count = 0
        in_string = False
        escape = False
        first_obj_end = -1

        for i, char in enumerate(content):
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if char == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    first_obj_end = i + 1
                    break

        # 如果找到了多余的数据，截断文件
        if first_obj_end > 0 and first_obj_end < len(content.strip()):
            print(f"警告: 文件 {file_path} 包含多个 JSON 对象，已修复")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content[:first_obj_end])
    except Exception:
        # 如果修复失败，忽略错误，让后续代码处理
        pass


class ParallelBuildStage:
    """
    并行构建阶段（混合模式）

    - NetworkX 图构建: 使用线程池并行
    - SQLite 写入: 保持串行
    - Pickle 序列化: 可并行
    """

    def __init__(self, base_path: Path, num_workers: Optional[int] = None):
        """
        初始化并行构建阶段

        Args:
            base_path: 引擎/插件根目录
            num_workers: 并行 worker 数量（None = 自动检测）
        """
        self.base_path = Path(base_path)
        self.data_dir = self.base_path / "KnowledgeBase" / "data"
        self.kb_path = self.base_path / "KnowledgeBase"

        if num_workers is None:
            num_workers = min(os.cpu_count() or 4, 4)  # 限制最大 4 个 worker

        self.num_workers = num_workers

    def run(self, **kwargs) -> Dict[str, Any]:
        """运行构建阶段"""
        console = Console()

        # 1. 创建配置
        self.kb_path.mkdir(parents=True, exist_ok=True)
        config = self._create_config()

        # 2. 并行构建模块图谱
        graphs_dir = self.kb_path / "module_graphs"
        graphs_dir.mkdir(parents=True, exist_ok=True)

        analyze_dir = self.data_dir / "analyze"
        if not analyze_dir.exists():
            raise RuntimeError("Analyze 阶段未完成")

        # 收集所有需要处理的模块
        module_tasks = []
        for module_dir in analyze_dir.iterdir():
            if not module_dir.is_dir():
                continue
            code_graph_file = module_dir / "code_graph.json"
            if code_graph_file.exists():
                module_tasks.append((module_dir.name, code_graph_file, graphs_dir))

        # 并行构建图
        tracker = ProgressTracker(
            stage_name="build",
            total_items=len(module_tasks),
            num_workers=self.num_workers,
            console=console,
        )

        tracker.start()

        built_count = 0
        failed_modules = []

        # 跟踪每个 worker 的完成数量
        worker_completed = {i: 0 for i in range(self.num_workers)}
        worker_total = {i: len(module_tasks) // self.num_workers for i in range(self.num_workers)}
        # 补充余数到第一个 worker
        remainder = len(module_tasks) % self.num_workers
        for i in range(remainder):
            worker_total[i] += 1

        # 首次更新所有 worker 状态
        for i in range(self.num_workers):
            tracker.update_worker(i, "Initializing...", 0, worker_total[i])

        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            # 存储 (module_name, worker_id)
            future_to_info = {}
            for idx, task in enumerate(module_tasks):
                worker_id = idx % self.num_workers
                future_to_info[executor.submit(self._build_module_graph, task)] = (task[0], worker_id)

            for future in as_completed(future_to_info):
                module_name, worker_id = future_to_info[future]

                try:
                    result = future.result()
                    if result["status"] == "success":
                        built_count += 1
                        worker_completed[worker_id] += 1
                        tracker.increment_total()

                        # 更新 worker 进度条
                        tracker.update_worker(
                            worker_id,
                            module_name,
                            worker_completed[worker_id],
                            worker_total[worker_id]
                        )
                    else:
                        worker_completed[worker_id] += 1
                        failed_modules.append(
                            {"name": module_name, "error": result["error"]}
                        )
                        tracker.add_error(
                            module_name, result["error"], "BuildError"
                        )
                        tracker.increment_total()

                        # 更新 worker 进度条
                        tracker.update_worker(
                            worker_id,
                            f"Error: {module_name}",
                            worker_completed[worker_id],
                            worker_total[worker_id]
                        )

                except Exception as e:
                    worker_completed[worker_id] += 1
                    failed_modules.append(
                        {"name": module_name, "error": str(e)}
                    )
                    tracker.add_error(
                        module_name, str(e), type(e).__name__
                    )
                    tracker.increment_total()

                    # 更新 worker 进度条
                    tracker.update_worker(
                        worker_id,
                        f"Error: {module_name}",
                        worker_completed[worker_id],
                        worker_total[worker_id]
                    )

        stats = tracker.stop()

        # 3. 串行构建全局索引和 SQLite
        console.print(f"\n[cyan]构建全局索引...[/cyan]")
        global_index = self._build_global_index(config)

        # 4. 串行构建快速索引
        console.print(f"[cyan]构建快速索引...[/cyan]")
        self._build_fast_indices(config)

        result = {
            "kb_path": str(self.kb_path),
            "module_graphs_created": built_count,
            "failed_modules": failed_modules,
            "elapsed_time": stats["elapsed"],
        }

        console.print(f"\n[green]Build 阶段完成！[/green]")
        console.print(f"  模块图谱: {built_count} 个")
        console.print(f"  耗时: {stats['elapsed']:.2f}s")

        return result

    def _build_module_graph(self, task: Tuple) -> Dict[str, Any]:
        """
        构建单个模块的 NetworkX 图

        这个操作是线程安全的，因为每个模块独立处理
        """
        module_name, code_graph_file, graphs_dir = task

        try:
            # 尝试修复可能有多个 JSON 对象的文件
            _fix_multi_json_file(code_graph_file)

            with open(code_graph_file, "r", encoding="utf-8") as f:
                code_graph = json.load(f)

            # 保存原始 JSON（便于查看和调试）
            json_file = graphs_dir / f"{module_name}.json"
            with open(json_file, "w", encoding="utf-8") as f:
                json.dump(code_graph, f, indent=2, ensure_ascii=False)

            # 创建 NetworkX 图
            graph = self._create_networkx_graph(code_graph)

            # 保存为 pickle
            output_file = graphs_dir / f"{module_name}.pkl"
            with open(output_file, "wb") as f:
                pickle.dump(
                    {
                        "module": module_name,
                        "graph": graph,
                        "metadata": {
                            "class_count": len(code_graph.get("classes", [])),
                            "function_count": len(code_graph.get("functions", [])),
                        },
                    },
                    f,
                )

            return {"status": "success", "module": module_name}

        except Exception as e:
            return {
                "status": "error",
                "module": module_name,
                "error": str(e),
            }

    def _create_networkx_graph(self, code_graph: Dict[str, Any]) -> nx.DiGraph:
        """从代码图谱创建 NetworkX 图"""
        graph = nx.DiGraph()

        for cls in code_graph.get("classes", []):
            class_name = cls["name"]
            file_path = cls.get("file") or cls.get("file_path", "")
            line_num = cls.get("line") or cls.get("line_number", 0)

            parent_classes = cls.get("parent_classes", [])
            properties = cls.get("properties", [])

            # 转换属性为字典格式
            properties_dict = []
            for prop in properties:
                if isinstance(prop, dict):
                    properties_dict.append(prop)
                elif isinstance(prop, str):
                    properties_dict.append(
                        {"name": prop, "type": "unknown", "is_uproperty": False}
                    )

            graph.add_node(
                f"class_{class_name}",
                type="class",
                name=class_name,
                file=file_path,
                line=line_num,
                parent_classes=parent_classes,
                interfaces=cls.get("interfaces", []),
                methods=cls.get("methods", []),
                properties=properties_dict,
                namespace=cls.get("namespace", ""),
                is_uclass=cls.get("is_uclass", False),
                is_struct=cls.get("is_struct", False),
                is_interface=cls.get("is_interface", False),
            )

            for parent in parent_classes:
                graph.add_edge(f"class_{class_name}", f"class_{parent}", type="inherits")

            for interface in cls.get("interfaces", []):
                graph.add_edge(
                    f"class_{class_name}", f"class_{interface}", type="implements"
                )

        for func in code_graph.get("functions", []):
            func_name = func["name"]
            file_path = func.get("file") or func.get("file_path", "")
            line_num = func.get("line") or func.get("line_number", 0)

            signature = func.get("signature", "")
            if not signature:
                return_type = func.get("return_type", "")
                params = func.get("parameters", [])
                params_str = ", ".join(
                    [f"{p.get('type', 'unknown')} {p.get('name', 'param')}" for p in params]
                )
                signature = f"{return_type} {func_name}({params_str})"

            graph.add_node(
                f"function_{func_name}",
                type="function",
                name=func_name,
                file=file_path,
                line=line_num,
                signature=signature,
                return_type=func.get("return_type", ""),
                parameters=func.get("parameters", []),
                class_name=func.get("class_name", ""),
                is_ufunction=func.get("is_ufunction", False),
                is_blueprint_callable=func.get("is_blueprint_callable", False),
            )

        return graph

    def _create_config(self) -> Config:
        """创建配置"""
        config = Config(base_path=str(self.kb_path))
        config.save()
        return config

    def _build_global_index(self, config: Config) -> GlobalIndex:
        """构建全局索引（串行）"""
        # 使用现有的 GlobalIndex 构建逻辑
        global_index = GlobalIndex(config)

        # 加载 discover 和 extract 的结果
        discover_result_file = self.data_dir / 'discover' / 'modules.json'
        if not discover_result_file.exists():
            return global_index

        # 尝试修复可能有多个 JSON 对象的文件
        _fix_multi_json_file(discover_result_file)

        try:
            with open(discover_result_file, 'r', encoding='utf-8') as f:
                discover_result = json.load(f)
        except json.JSONDecodeError as e:
            # 如果 JSON 解析失败，尝试读取并显示错误
            with open(discover_result_file, 'r', encoding='utf-8') as f:
                content = f.read()
                print(f"JSON 解析错误: {e}")
                print(f"文件: {discover_result_file}")
                print(f"文件大小: {len(content)} 字节")
                if e.pos:
                    start = max(0, e.pos - 100)
                    end = min(len(content), e.pos + 100)
                    print(f"错误位置上下文:\n{content[start:end]}")
            raise

        modules = discover_result.get('modules', [])
        extract_dir = self.data_dir / 'extract'

        # 添加模块到索引
        for module in modules:
            module_name = module['name']

            # 加载依赖信息
            dep_file = extract_dir / module_name / "dependencies.json"
            if not dep_file.exists():
                # 没有依赖信息，使用空依赖
                dependencies = {}
            else:
                # 尝试修复可能有多个 JSON 对象的文件
                _fix_multi_json_file(dep_file)

                try:
                    with open(dep_file, 'r', encoding='utf-8') as f:
                        dep_data = json.load(f)
                        dependencies = dep_data.get('dependencies', {})
                except json.JSONDecodeError as e:
                    print(f"JSON 解析错误: {e}")
                    print(f"文件: {dep_file}")
                    raise

            # 添加到索引
            # BuildCsParser 返回 'public'/'private'/'dynamic'
            # 兼容旧格式 'PublicDependencyModuleNames' 等
            public_deps = (dependencies.get('public', [])
                           or dependencies.get('PublicDependencyModuleNames', []))
            private_deps = (dependencies.get('private', [])
                            or dependencies.get('PrivateDependencyModuleNames', []))
            dynamic_deps = (dependencies.get('dynamic', [])
                            or dependencies.get('DynamicallyLoadedModuleNames', []))

            global_index.add_module(
                module_name,
                {
                    'name': module_name,
                    'path': module['path'],
                    'category': module['category'],
                    'dependencies': public_deps,
                    'public_dependencies': public_deps,
                    'private_dependencies': private_deps,
                    'dynamic_dependencies': dynamic_deps,
                }
            )

        # 构建依赖图
        global_index.build_dependency_graph()

        # 保存索引
        global_index.save()

        # 同步到 SQLite（供 OptimizedGlobalIndex 查询使用）
        self._sync_to_sqlite(global_index, config)

        return global_index

    def _sync_to_sqlite(self, global_index: GlobalIndex, config: Config) -> None:
        """将 GlobalIndex 数据同步到 SQLite"""
        import sqlite3

        # 获取数据库路径
        db_path = os.path.join(config.global_index_path, "index.db")

        # 连接数据库
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 创建表（如果不存在）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS modules (
                name TEXT PRIMARY KEY,
                path TEXT,
                category TEXT,
                plugin TEXT DEFAULT 'Engine',
                dependencies TEXT,
                public_dependencies TEXT,
                private_dependencies TEXT,
                dynamic_dependencies TEXT,
                weak_dependencies TEXT,
                circular_dependencies TEXT,
                file_count INTEGER,
                estimated_lines INTEGER,
                main_classes TEXT,
                build_cs_path TEXT,
                indexed_at TEXT
            )
        ''')

        # 清空旧数据
        cursor.execute('DELETE FROM modules')

        # 插入所有模块数据
        all_modules = global_index.get_all_modules()
        for module_name, module_info in all_modules.items():
            dependencies = module_info.get('dependencies', [])

            cursor.execute('''
                INSERT OR REPLACE INTO modules (
                    name, path, category, plugin, dependencies,
                    public_dependencies, private_dependencies, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                module_name,
                module_info.get('path', ''),
                module_info.get('category', ''),
                'Engine',
                json.dumps(dependencies),
                json.dumps(module_info.get('public_dependencies', [])),
                json.dumps(module_info.get('private_dependencies', [])),
                module_info.get('indexed_at', '')
            ))

        conn.commit()
        conn.close()

    def _build_fast_indices(self, config: Config) -> None:
        """构建快速索引（串行）"""
        from ..core.class_index import ClassIndex
        from ..core.function_index import FunctionIndex

        # 创建索引文件路径
        global_index_path = Path(config.global_index_path)
        class_index_db = global_index_path / "class_index.db"
        function_index_db = global_index_path / "function_index.db"

        class_idx = ClassIndex(str(class_index_db))
        func_idx = FunctionIndex(str(function_index_db))

        # 遍历所有模块图谱，收集类和函数信息
        graphs_dir = Path(config.module_graphs_path)

        if not graphs_dir.exists():
            return

        classes_batch = []
        functions_batch = []

        for graph_file in graphs_dir.glob("*.pkl"):
            module_name = graph_file.stem

            try:
                with open(graph_file, 'rb') as f:
                    data = pickle.load(f)
                    graph = data.get('graph')

                if not graph:
                    continue

                # 收集类信息
                for node, node_data in graph.nodes(data=True):
                    if node_data.get('type') == 'class':
                        class_info = {
                            'name': node_data.get('name', ''),
                            'module': module_name,
                            'namespace': node_data.get('namespace', ''),
                            'parent_classes': node_data.get('parent_classes', []),
                            'interfaces': node_data.get('interfaces', []),
                            'file_path': node_data.get('file', ''),
                            'line_number': node_data.get('line', 0),
                            'is_uclass': node_data.get('is_uclass', False),
                            'is_struct': node_data.get('is_struct', False),
                            'is_interface': node_data.get('is_interface', False),
                            'is_blueprintable': node_data.get('is_blueprintable', False),
                            'method_count': len(node_data.get('methods', [])),
                            'property_count': len(node_data.get('properties', []))
                        }
                        classes_batch.append(class_info)

                    elif node_data.get('type') == 'function':
                        func_info = {
                            'name': node_data.get('name', ''),
                            'module': module_name,
                            'class_name': node_data.get('class_name', ''),
                            'return_type': node_data.get('return_type', ''),
                            'parameters': node_data.get('parameters', []),
                            'signature': node_data.get('signature', ''),
                            'file_path': node_data.get('file', ''),
                            'line_number': node_data.get('line', 0),
                            'is_virtual': node_data.get('is_virtual', False),
                            'is_const': node_data.get('is_const', False),
                            'is_static': node_data.get('is_static', False),
                            'is_blueprint_callable': node_data.get('is_blueprint_callable', False),
                            'ufunction_specifiers': node_data.get('ufunction_specifiers', {})
                        }
                        functions_batch.append(func_info)

                # 批量提交（每 1000 条）
                if len(classes_batch) >= 1000:
                    class_idx.add_classes_batch(classes_batch)
                    classes_batch.clear()

                if len(functions_batch) >= 1000:
                    func_idx.add_functions_batch(functions_batch)
                    functions_batch.clear()

            except Exception:
                pass  # 跳过错误文件

        # 提交剩余数据
        if classes_batch:
            class_idx.add_classes_batch(classes_batch)
        if functions_batch:
            func_idx.add_functions_batch(functions_batch)

        class_idx.commit()
        func_idx.commit()
