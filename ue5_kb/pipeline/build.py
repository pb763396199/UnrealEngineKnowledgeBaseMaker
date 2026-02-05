"""
Pipeline 阶段 4: Build (构建索引)

将 JSON 数据转换为优化的存储格式（SQLite + Pickle）
"""

from pathlib import Path
from typing import Dict, Any, List
import json
import os
import pickle
import networkx as nx
from .base import PipelineStage
from ..core.config import Config
from ..core.global_index import GlobalIndex
from ..core.optimized_index import OptimizedGlobalIndex


class BuildStage(PipelineStage):
    """
    构建阶段

    将前面阶段的 JSON 数据转换为最终的索引格式
    """

    @property
    def stage_name(self) -> str:
        return "build"

    def get_output_path(self) -> Path:
        # 输出到 KnowledgeBase 目录
        return self.base_path / "KnowledgeBase"

    def is_completed(self) -> bool:
        # 检查 KnowledgeBase 目录是否存在且有 global_index
        kb_path = self.get_output_path()
        global_index_db = kb_path / "global_index" / "index.db"
        return global_index_db.exists()

    def run(self, parallel: int = 1, **kwargs) -> Dict[str, Any]:
        """
        构建全局索引和模块图谱

        Args:
            parallel: 并行度（0=自动检测，1=串行，>1=并行）

        Returns:
            构建统计
        """
        # 确定并行度
        if parallel == 0:  # auto
            parallel = os.cpu_count() or 4

        # 如果并行度 > 1，使用并行模式
        if parallel > 1:
            from .build_parallel import ParallelBuildStage
            from rich.console import Console

            console = Console()
            console.print(f"[cyan]使用并行模式: {parallel} workers[/cyan]")

            parallel_stage = ParallelBuildStage(self.base_path, num_workers=parallel)
            return parallel_stage.run()

        # 否则使用原有的串行逻辑
        return self._run_serial()

    def _run_serial(self) -> Dict[str, Any]:
        """串行运行构建（原有逻辑）"""
        print(f"[Build] 构建知识库索引...")

        # 1. 创建配置
        kb_path = self.get_output_path()
        kb_path.mkdir(parents=True, exist_ok=True)

        config = self._create_config(kb_path)

        # 2. 构建全局索引
        global_index = self._build_global_index(config)

        # 3. 构建模块图谱
        modules_built = self._build_module_graphs(kb_path)

        # 4. 构建快速索引
        self._build_fast_indices(config)

        # 5. 保存统计信息
        stats = global_index.get_statistics()

        result = {
            'kb_path': str(kb_path),
            'global_index_created': True,
            'module_graphs_created': modules_built,
            'statistics': stats
        }

        # 保存构建摘要
        self.save_result(result, "build_summary.json")

        print(f"[Build] 完成！")
        print(f"  知识库路径: {kb_path}")
        print(f"  总模块数: {stats.get('total_modules', 0)}")
        print(f"  模块图谱: {modules_built} 个")

        return result

    def _create_config(self, kb_path: Path) -> Config:
        """
        创建配置对象

        Args:
            kb_path: 知识库路径

        Returns:
            Config 对象
        """
        config = Config(base_path=str(kb_path))
        config.save()
        return config

    def _build_global_index(self, config: Config) -> GlobalIndex:
        """
        构建全局索引

        Args:
            config: 配置对象

        Returns:
            GlobalIndex 对象
        """
        print(f"  构建全局索引...")

        global_index = GlobalIndex(config)

        # 加载 discover 和 extract 的结果
        discover_result = self.load_previous_stage_result('discover', 'modules.json')
        extract_dir = self.data_dir / 'extract'

        if not discover_result:
            raise RuntimeError("Discover 阶段结果不存在")

        modules = discover_result['modules']

        # 添加模块到索引
        for module in modules:
            module_name = module['name']

            # 加载依赖信息
            dep_file = extract_dir / module_name / "dependencies.json"
            if not dep_file.exists():
                # 没有依赖信息，使用空依赖
                dependencies = {}
            else:
                with open(dep_file, 'r', encoding='utf-8') as f:
                    dep_data = json.load(f)
                    dependencies = dep_data.get('dependencies', {})

            # 添加到索引
            global_index.add_module(
                module_name,
                {
                    'name': module_name,
                    'path': module['path'],
                    'category': module['category'],
                    'dependencies': dependencies.get('PublicDependencyModuleNames', []),
                    'public_dependencies': dependencies.get('PublicDependencyModuleNames', []),
                    'private_dependencies': dependencies.get('PrivateDependencyModuleNames', [])
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
        """
        将 GlobalIndex 数据同步到 SQLite

        Args:
            global_index: 全局索引
            config: 配置对象
        """
        import sqlite3
        import json

        print(f"  同步到 SQLite...")

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

        print(f"  已同步 {len(all_modules)} 个模块到 SQLite")

    def _build_fast_indices(self, config: Config) -> None:
        """
        构建快速索引（ClassIndex 和 FunctionIndex）

        Args:
            config: 配置对象
        """
        from ..core.class_index import ClassIndex
        from ..core.function_index import FunctionIndex

        print(f"  构建快速索引...")

        # 创建索引文件路径（确保使用 Path 对象）
        global_index_path = Path(config.global_index_path)
        class_index_db = global_index_path / "class_index.db"
        function_index_db = global_index_path / "function_index.db"

        class_idx = ClassIndex(str(class_index_db))
        func_idx = FunctionIndex(str(function_index_db))

        # 遍历所有模块图谱，收集类和函数信息
        graphs_dir = Path(config.module_graphs_path)

        if not graphs_dir.exists():
            print(f"    警告: 模块图谱目录不存在，跳过快速索引构建")
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

            except Exception as e:
                print(f"    警告: 处理 {module_name} 图谱失败: {e}")

        # 提交剩余数据
        if classes_batch:
            class_idx.add_classes_batch(classes_batch)
        if functions_batch:
            func_idx.add_functions_batch(functions_batch)

        class_idx.commit()
        func_idx.commit()

        # 输出统计
        class_stats = class_idx.get_statistics()
        func_stats = func_idx.get_statistics()

        print(f"    类索引: {class_stats['total_classes']} 个类")
        print(f"    函数索引: {func_stats['total_functions']} 个函数")

    def _build_optimized_index(self, global_index: GlobalIndex, config: Config) -> None:
        """
        构建优化索引（SQLite）

        Args:
            global_index: 全局索引
            config: 配置对象
        """
        print(f"  构建 SQLite 索引...")

        optimized = OptimizedGlobalIndex(config)

        # 将数据从 GlobalIndex 转移到 SQLite
        all_modules = global_index.get_all_modules()

        for module_name, module_info in all_modules.items():
            optimized.add_module(module_name, module_info)

        optimized.build_indices()

    def _build_module_graphs(self, kb_path: Path) -> int:
        """
        构建模块图谱

        Args:
            kb_path: 知识库路径

        Returns:
            构建的图谱数量
        """
        print(f"  构建模块图谱...")

        analyze_dir = self.data_dir / 'analyze'
        if not analyze_dir.exists():
            print(f"    警告: 分析阶段结果不存在，跳过模块图谱构建")
            return 0

        graphs_dir = kb_path / "module_graphs"
        graphs_dir.mkdir(parents=True, exist_ok=True)

        built_count = 0

        # 遍历分析结果
        for module_dir in analyze_dir.iterdir():
            if not module_dir.is_dir():
                continue

            code_graph_file = module_dir / "code_graph.json"
            if not code_graph_file.exists():
                continue

            module_name = module_dir.name

            try:
                # 加载代码图谱
                with open(code_graph_file, 'r', encoding='utf-8') as f:
                    code_graph = json.load(f)

                # 保存原始 JSON（便于查看和调试）
                json_file = graphs_dir / f"{module_name}.json"
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(code_graph, f, indent=2, ensure_ascii=False)

                # 转换为 NetworkX 图
                graph = self._create_networkx_graph(code_graph)

                # 保存为 pickle
                output_file = graphs_dir / f"{module_name}.pkl"
                with open(output_file, 'wb') as f:
                    pickle.dump({
                        'module': module_name,
                        'graph': graph,
                        'metadata': {
                            'class_count': len(code_graph.get('classes', [])),
                            'function_count': len(code_graph.get('functions', []))
                        }
                    }, f)

                built_count += 1

            except Exception as e:
                print(f"    警告: 构建 {module_name} 图谱失败: {e}")

        return built_count

    def _create_networkx_graph(self, code_graph: Dict[str, Any]) -> nx.DiGraph:
        """
        从代码图谱创建 NetworkX 图

        Args:
            code_graph: 代码图谱数据

        Returns:
            NetworkX 有向图
        """
        graph = nx.DiGraph()

        # 添加类节点
        for cls in code_graph.get('classes', []):
            class_name = cls['name']

            # 兼容不同的字段名
            file_path = cls.get('file') or cls.get('file_path', '')
            line_num = cls.get('line') or cls.get('line_number', 0)

            # 处理 parent_class (单个字符串) 和 parent_classes (列表)
            parent_class = cls.get('parent_class')
            parent_classes = cls.get('parent_classes', [])
            if parent_class and not parent_classes:
                parent_classes = [parent_class] if parent_class else []

            # 处理 properties - 新格式是 PropertyInfo 列表，旧格式是字符串列表
            properties = cls.get('properties', [])
            # 转换为统一的字典格式
            properties_dict = []
            for prop in properties:
                if isinstance(prop, dict):
                    # 新格式 PropertyInfo
                    properties_dict.append(prop)
                elif isinstance(prop, str):
                    # 旧格式字符串（向后兼容）
                    properties_dict.append({'name': prop, 'type': 'unknown', 'is_uproperty': False})

            graph.add_node(
                f"class_{class_name}",
                type='class',
                name=class_name,
                file=file_path,
                line=line_num,
                parent_classes=parent_classes,
                interfaces=cls.get('interfaces', []),  # 新增：接口列表
                methods=cls.get('methods', []),
                properties=properties_dict,  # 更新：PropertyInfo 列表
                namespace=cls.get('namespace', ''),  # 新增：命名空间
                is_uclass=cls.get('is_uclass', False),
                is_struct=cls.get('is_struct', False),
                is_interface=cls.get('is_interface', False)
            )

            # 添加继承边
            for parent in parent_classes:
                graph.add_edge(f"class_{class_name}", f"class_{parent}", type='inherits')

            # 添加接口实现边
            for interface in cls.get('interfaces', []):
                graph.add_edge(f"class_{class_name}", f"class_{interface}", type='implements')

        # 添加函数节点
        for func in code_graph.get('functions', []):
            func_name = func['name']

            # 兼容不同的字段名
            file_path = func.get('file') or func.get('file_path', '')
            line_num = func.get('line') or func.get('line_number', 0)

            # 构建函数签名
            signature = func.get('signature', '')
            if not signature:
                # 从 return_type 和 parameters 构建签名
                return_type = func.get('return_type', '')
                params = func.get('parameters', [])
                params_str = ', '.join([f"{p.get('type', 'unknown')} {p.get('name', 'param')}" for p in params])
                signature = f"{return_type} {func_name}({params_str})"

            graph.add_node(
                f"function_{func_name}",
                type='function',
                name=func_name,
                file=file_path,
                line=line_num,
                signature=signature,
                return_type=func.get('return_type', ''),
                parameters=func.get('parameters', []),
                class_name=func.get('class_name', ''),
                is_ufunction=func.get('is_ufunction', False),
                is_blueprint_callable=func.get('is_blueprint_callable', False)
            )

        return graph
