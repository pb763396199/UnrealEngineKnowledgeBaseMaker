"""
ue5kb-dev-guide Skill Implementation

UE5 Knowledge Base Maker 项目专属开发指导实现。
"""

from pathlib import Path
from typing import Any

# 项目根路径（动态获取）
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
KB_PATH = PROJECT_ROOT

# 导入项目模块
try:
    from ue5_kb.core.config import get_config
    from ue5_kb.core.global_index import GlobalIndex
    from ue5_kb.core.module_graph import ModuleGraph
    from ue5_kb.parsers.buildcs_parser import BuildCSParser
    from ue5_kb.builders.global_index_builder import GlobalIndexBuilder
    from ue5_kb.builders.plugin_index_builder import PluginIndexBuilder
except ImportError:
    # 开发环境下可能未安装，使用备用方案
    pass


def get_project_info() -> dict[str, Any]:
    """获取项目基本信息

    Returns:
        包含项目名称、版本、路径等信息的字典
    """
    return {
        "name": "UE5 Knowledge Base Maker",
        "version": "2.5.0",
        "type": "Python CLI Tool",
        "tech_stack": ["Python 3.9+", "Click", "Rich", "NetworkX", "SQLite"],
        "root_path": str(PROJECT_ROOT),
        "docs": {
            "readme": str(PROJECT_ROOT / "README.md"),
            "status": str(PROJECT_ROOT / "STATUS.md"),
            "changelog": str(PROJECT_ROOT / "CHANGELOG.md"),
            "claude_md": str(PROJECT_ROOT / "CLAUDE.md"),
        },
        "openspec_path": str(PROJECT_ROOT / "openspec"),
    }


def get_architecture_overview() -> dict[str, Any]:
    """获取系统架构概览

    Returns:
        包含架构层次、模块关系、数据流的字典
    """
    return {
        "version": "2.5.0",
        "architecture_type": "Pipeline-based (5-stage)",
        "layers": {
            "cli": "cli.py - 命令行接口和模式路由",
            "pipeline": "pipeline/ - 5阶段处理流程",
            "parsers": "parsers/ - 代码解析器",
            "core": "core/ - 核心模块和接口",
            "query": "query/ - 查询优化模块",
            "analyzers": "analyzers/ - Phase 2 分析框架",
        },
        "pipeline_stages": {
            "discover": "发现所有 .Build.cs 文件",
            "extract": "解析模块元数据",
            "analyze": "分析代码关系",
            "build": "构建索引",
            "generate": "生成 Skills",
        },
        "modes": {
            "engine": {
                "entry": "PipelineCoordinator (engine mode)",
                "output": "{引擎}/KnowledgeBase/",
            },
            "plugin": {
                "entry": "PipelineCoordinator (plugin mode)",
                "output": "{插件}/KnowledgeBase/",
            },
        },
        "data_flow": [
            "Discover (.Build.cs 发现)",
            "Extract (元数据解析)",
            "Analyze (关系分析)",
            "Build (索引构建)",
            "Generate (Skill 生成)",
        ],
    }


def get_pipeline_info() -> dict[str, Any]:
    """获取 Pipeline 系统信息

    Returns:
        包含 Pipeline 架构、阶段、状态管理的字典
    """
    return {
        "architecture": "5-Stage Pipeline System",
        "stages": {
            "discover": {
                "file": "pipeline/discover.py",
                "class": "DiscoverStage",
                "purpose": "发现所有 .Build.cs 文件",
                "input": "引擎/插件根目录",
                "output": "module_list (名称、路径、分类)",
            },
            "extract": {
                "file": "pipeline/extract.py",
                "class": "ExtractStage",
                "purpose": "解析模块元数据",
                "input": "module_list",
                "output": "module_metadata (依赖、类、函数)",
            },
            "analyze": {
                "file": "pipeline/analyze.py",
                "class": "AnalyzeStage",
                "purpose": "分析代码关系",
                "input": "module_metadata",
                "output": "enhanced_metadata (调用图、示例)",
            },
            "build": {
                "file": "pipeline/build.py",
                "class": "BuildStage",
                "purpose": "构建索引",
                "input": "enhanced_metadata",
                "output": "SQLite + Pickle 文件",
            },
            "generate": {
                "file": "pipeline/generate.py",
                "class": "GenerateStage",
                "purpose": "生成 Skills",
                "input": "索引文件",
                "output": "Claude Code Skills",
            },
        },
        "coordinator": {
            "file": "pipeline/coordinator.py",
            "class": "PipelineCoordinator",
            "methods": {
                "run_all()": "运行完整 Pipeline",
                "run_stage()": "运行单个阶段",
                "get_state()": "获取 Pipeline 状态",
            },
        },
        "state_management": {
            "file": "pipeline/state.py",
            "class": "PipelineState",
            "state_file": "pipeline_state.json",
            "features": [
                "状态持久化",
                "增量执行支持",
                "错误恢复",
            ],
        },
    }


def get_analyzer_info() -> dict[str, Any]:
    """获取 Analyzers 框架信息（Phase 2）

    Returns:
        包含 Analyzers 组件、功能、使用方法的字典
    """
    return {
        "phase": "Phase 2 Framework",
        "analyzers": {
            "call_analyzer": {
                "file": "analyzers/call_analyzer.py",
                "class": "CallAnalyzer",
                "purpose": "函数调用关系分析",
                "features": [
                    "构建调用关系图",
                    "追踪 caller-callee 关系",
                    "支持影响分析",
                ],
            },
            "example_extractor": {
                "file": "analyzers/example_extractor.py",
                "class": "ExampleExtractor",
                "purpose": "使用示例提取",
                "features": [
                    "从代码中提取实际使用示例",
                    "提供实用的代码样本",
                    "支持学习和文档生成",
                ],
            },
        },
        "integration": {
            "stage": "AnalyzeStage",
            "invocation": "由 PipelineCoordinator.analyze 调用",
            "output": "enhanced_metadata (包含调用图和示例)",
        },
        "usage_example": """from ue5_kb.pipeline.coordinator import PipelineCoordinator

coordinator = PipelineCoordinator(engine_path)
results = coordinator.run_all()

# 获取调用分析结果
call_graph = results['analyze'].get('call_graph')
examples = results['analyze'].get('examples')""",
    }


def get_module_documentation(module_name: str) -> dict[str, Any]:
    """获取指定模块的文档

    Args:
        module_name: 模块名称（如 'core/config', 'builders/global_index_builder'）

    Returns:
        包含模块职责、关键类/函数、使用示例的字典
    """
    modules = {
        "cli": {
            "file": "ue5_kb/cli.py",
            "purpose": "CLI 命令定义和处理",
            "key_functions": {
                "init()": "初始化命令，路由到引擎/插件模式",
                "init_engine_mode()": "引擎模式处理逻辑",
                "init_plugin_mode()": "插件模式处理逻辑",
                "detect_engine_version()": "从 Build.version 检测引擎版本",
                "detect_plugin_info()": "从 .uplugin 检测插件信息",
                "generate_skill()": "从模板生成 Claude Skill",
            },
            "usage": 'python -m ue5_kb.cli init --engine-path "D:\\UE5.1"',
        },
        "core/config": {
            "file": "ue5_kb/core/config.py",
            "purpose": "配置管理（路径、版本）",
            "key_class": "Config",
            "key_attributes": {
                "base_path": "知识库根路径",
                "engine_version": "引擎版本",
                "index_db_path": "SQLite 数据库路径",
                "module_graphs_dir": "模块图谱目录",
            },
            "usage": "from ue5_kb.core.config import get_config\nconfig = get_config(engine_path)",
        },
        "core/global_index": {
            "file": "ue5_kb/core/global_index.py",
            "purpose": "全局索引接口",
            "key_class": "GlobalIndex",
            "key_methods": {
                "get_module_info()": "获取模块信息",
                "get_module_dependencies()": "获取模块依赖",
                "search_modules()": "搜索模块",
                "get_statistics()": "获取统计信息",
            },
            "usage": "from ue5_kb.core.global_index import GlobalIndex\nindex = GlobalIndex(kb_path)",
        },
        "core/module_graph": {
            "file": "ue5_kb/core/module_graph.py",
            "purpose": "模块图谱接口",
            "key_class": "ModuleGraph",
            "key_methods": {
                "get_class_info()": "获取类信息",
                "get_class_hierarchy()": "获取类继承层次",
                "get_module_classes()": "获取模块中的所有类",
                "search_classes()": "搜索类",
            },
            "usage": "from ue5_kb.core.module_graph import ModuleGraph\ngraph = ModuleGraph(kb_path)",
        },
        "builders/global_index_builder": {
            "file": "ue5_kb/builders/global_index_builder.py",
            "purpose": "引擎索引构建",
            "key_class": "GlobalIndexBuilder",
            "key_methods": {
                "build()": "构建索引",
                "_scan_build_files()": "扫描 .Build.cs 文件",
                "_determine_category()": "确定模块分类",
            },
            "usage": "from ue5_kb.builders.global_index_builder import GlobalIndexBuilder\nbuilder = GlobalIndexBuilder(engine_path)\nbuilder.build()",
        },
        "builders/plugin_index_builder": {
            "file": "ue5_kb/builders/plugin_index_builder.py",
            "purpose": "插件索引构建",
            "key_class": "PluginIndexBuilder",
            "key_methods": {
                "build()": "构建索引",
                "_scan_build_files()": "扫描插件的 .Build.cs 文件",
            },
            "usage": "from ue5_kb.builders.plugin_index_builder import PluginIndexBuilder\nbuilder = PluginIndexBuilder(plugin_path)\nbuilder.build()",
        },
        "parsers/buildcs_parser": {
            "file": "ue5_kb/parsers/buildcs_parser.py",
            "purpose": "Build.cs 文件解析",
            "key_class": "BuildCSParser",
            "key_methods": {
                "parse_file()": "解析单个文件",
                "_extract_dependencies()": "提取依赖关系",
                "_extract_module_info()": "提取模块信息",
            },
            "usage": "from ue5_kb.parsers.buildcs_parser import BuildCSParser\nparser = BuildCSParser()\nresult = parser.parse_file(build_file)",
        },
        "parsers/cpp_parser": {
            "file": "ue5_kb/parsers/cpp_parser.py",
            "purpose": "C++ 代码解析",
            "key_class": "CPPParser",
            "key_methods": {
                "parse_module()": "解析模块",
                "_extract_classes()": "提取类定义",
                "_extract_functions()": "提取函数定义",
                "_extract_inheritance()": "提取继承关系",
            },
            "usage": "from ue5_kb.parsers.cpp_parser import CPPParser\nparser = CPPParser()\nresult = parser.parse_module(module_path)",
        },
        "query/layered_query": {
            "file": "ue5_kb/query/layered_query.py",
            "purpose": "分层查询接口（Context Optimization）",
            "key_class": "LayeredQueryInterface",
            "key_methods": {
                "query_class()": "查询类信息（支持 summary/details/source）",
                "query_function()": "查询函数信息",
            },
            "usage": "from ue5_kb.query.layered_query import LayeredQueryInterface\nquery = LayeredQueryInterface(kb_path)\nresult = query.query_class('AActor', 'summary')",
        },
        "query/result_cache": {
            "file": "ue5_kb/query/result_cache.py",
            "purpose": "结果缓存和屏蔽（Observation Masking）",
            "key_class": "ResultCache",
            "key_methods": {
                "mask_large_result()": "屏蔽大型结果",
                "retrieve()": "按需获取完整结果",
            },
            "usage": "from ue5_kb.query.result_cache import ResultCache\ncache = ResultCache()\nmasked = cache.mask_large_result(results, threshold=5)",
        },
        "query/token_budget": {
            "file": "ue5_kb/query/token_budget.py",
            "purpose": "Token 预算管理",
            "key_class": "TokenBudget",
            "key_methods": {
                "allocate()": "分配预算",
                "get_statistics()": "获取预算统计",
            },
            "usage": "from ue5_kb.query.token_budget import get_token_budget, ContextCategory\nbudget = get_token_budget()\nif budget.allocate(ContextCategory.QUERY_RESULTS, tokens):\n    return result",
        },
    }

    return modules.get(module_name, {
        "error": f"未知模块: {module_name}",
        "available_modules": list(modules.keys()),
    })


def get_development_workflow() -> dict[str, Any]:
    """获取开发工作流指导

    Returns:
        包含开发流程、代码模式、测试策略的字典
    """
    return {
        "workflow": [
            "1. 需求分析",
            "2. 阅读 CLAUDE.md 了解基本流程",
            "3. 使用 Explore agent 探索相关代码",
            "4. 检查 openspec/ 是否需要创建 proposal",
            "5. 设计实现方案",
            "6. 编写代码（在 tests/ 中编写测试）",
            "7. 运行测试循环直到通过",
            "8. 更新 CHANGELOG.md",
            "9. 询问用户是否需要更新版本号/README.md",
            "10. 更新 CLI 帮助文档（如果重大功能）",
            "11. 提交代码",
        ],
        "test_cycle": {
            "description": "每次代码变更后必须执行以下循环，直到测试通过",
            "steps": [
                "代码变更",
                "运行测试 (pytest tests/)",
                "测试通过? 否 → 修复问题，返回运行测试",
                "测试通过? 是 → 使用 /ue5kb-dev-guide Skill 验证",
                "Skill 验证通过? 否 → 根据反馈修复，返回运行测试",
                "Skill 验证通过? 是 → 重新安装包 (pip install -e .)",
                "完成",
            ],
            "commands": [
                "pytest tests/ -v",
                "/ue5kb-dev-guide validate",
                "pip install -e . --force-reinstall --no-deps",
            ],
        },
        "code_patterns": {
            "Builder": """from ue5_kb.core.config import get_config
from ue5_kb.parsers.buildcs_parser import BuildCSParser

class CustomBuilder:
    def __init__(self, base_path: Path):
        self.config = get_config(base_path)
        self.parser = BuildCSParser()

    def build(self) -> None:
        files = self._scan_files()
        data = [self.parser.parse_file(f) for f in files]
        self._store(data)
""",
            "Parser": """class CustomParser:
    def parse_file(self, file_path: Path) -> dict:
        content = file_path.read_text(encoding='utf-8')
        return self._extract_info(content)
""",
        },
        "testing": {
            "unit_test": """import pytest
from pathlib import Path
from ue5_kb.parsers.buildcs_parser import BuildCSParser

def test_buildcs_parser():
    parser = BuildCSParser()
    test_file = Path("tests/fixtures/Core.Build.cs")
    result = parser.parse_file(test_file)
    assert result["name"] == "Core"
""",
            "integration_test": """def test_full_build_integration():
    from ue5_kb.builders.global_index_builder import GlobalIndexBuilder
    test_engine = Path("tests/fixtures/test_engine")
    builder = GlobalIndexBuilder(test_engine)
    builder.build()
    assert builder.config.index_db_path.exists()
""",
        },
    }


def get_best_practices() -> dict[str, Any]:
    """获取最佳实践指导

    Returns:
        包含代码风格、错误处理、性能优化的字典
    """
    return {
        "code_style": {
            "type_annotations": """def parse_file(file_path: Path) -> dict | None:
    \"\"\"解析 .Build.cs 文件

    Args:
        file_path: 文件路径

    Returns:
        包含模块信息的字典，解析失败返回 None
    \"\"\"
    pass
""",
            "naming_convention": {
                "class": "PascalCase (e.g., GlobalIndexBuilder)",
                "function": "snake_case (e.g., scan_files)",
                "constant": "UPPER_CASE (e.g., MODULE_NAME)",
            },
            "docstring": """\"\"\"单行摘要

更详细的描述（可选）

Args:
    arg1: 参数1说明

Returns:
    返回值说明

Raises:
    ValueError: 错误说明
\"\"\"
""",
        },
        "error_handling": {
            "safe_parse": """def safe_parse(file_path: Path) -> dict | None:
    try:
        return parser.parse_file(file_path)
    except FileNotFoundError:
        logger.warning(f"文件不存在: {file_path}")
        return None
    except Exception as e:
        logger.error(f"解析失败: {file_path}, 错误: {e}")
        return None
""",
            "retry": """def parse_with_retry(file_path: Path, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        try:
            return parser.parse_file(file_path)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"重试 {attempt + 1}/{max_retries}")
            time.sleep(1)
""",
        },
        "performance": {
            "lru_cache": """from functools import lru_cache

@lru_cache(maxsize=128)
def get_module_info(module_name: str) -> dict:
    return _query_from_db(module_name)
""",
            "batch_operations": """def batch_insert(items: list) -> None:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.executemany("INSERT ... VALUES (?, ?)", items)
        conn.commit()
""",
            "generators": """def parse_large_file(file_path: Path):
    with open(file_path) as f:
        for line in f:
            yield process_line(line)
""",
        },
    }


def get_troubleshooting_guide() -> dict[str, Any]:
    """获取故障排除指南

    Returns:
        包含常见错误、诊断方法、解决方案的字典
    """
    return {
        "common_errors": {
            "ModuleNotFoundError": {
                "symptom": "ModuleNotFoundError: No module named 'ue5_kb'",
                "cause": "包未安装",
                "solution": "pip install -e .",
            },
            "sqlite_locked": {
                "symptom": "sqlite3.OperationalError: database is locked",
                "cause": "多个进程同时访问数据库",
                "solution": "使用独占连接或增加超时时间",
                "code": """from contextlib import contextmanager

@contextmanager
def db_connection(db_path: Path):
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        yield conn
    finally:
        conn.close()
""",
            },
            "pickle_incompatible": {
                "symptom": "ModuleNotFoundError: Can't get module 'ue5_kb.core.xxx'",
                "cause": "Pickle 文件包含完整模块路径，重构后失效",
                "solution": "使用 JSON 作为备选",
            },
            "windows_path": {
                "symptom": "FileNotFoundError: [Errno 2] No such file or directory",
                "cause": "路径分隔符或转义问题",
                "solution": "使用 pathlib.Path 或原始字符串",
                "correct": [
                    'path = Path(r"D:\\path\\to\\file")',
                    'path = Path("D:/path/to/file")',
                ],
                "incorrect": [
                    'path = "D:\\path\\to\\file"  # \\t 被解析为制表符',
                ],
            },
        },
        "performance_issues": {
            "slow_query": {
                "diagnosis": """import time

start = time.time()
result = query_function()
elapsed = time.time() - start
print(f"查询耗时: {elapsed:.3f}秒")
""",
                "solutions": [
                    "启用 SQLite 索引",
                    "使用 LRU 缓存",
                    "批量操作",
                ],
            },
            "high_memory": {
                "diagnosis": """import psutil
import os

process = psutil.Process(os.getpid())
print(f"内存占用: {process.memory_info().rss / 1024 / 1024:.1f} MB")
""",
                "solutions": [
                    "使用生成器而非列表",
                    "及时释放大对象",
                    "分批处理大文件",
                ],
            },
        },
        "commands": {
            "dev": "pip install -e . --force-reinstall --no-deps",
            "test": "pytest tests/ -v",
            "help": "python -m ue5_kb.cli --help",
            "openspec_list": "openspec list",
            "openspec_validate": "openspec validate <change-id> --strict",
        },
    }


def validate_setup() -> dict[str, Any]:
    """验证项目设置

    Returns:
        包含验证结果的字典
    """
    results = {
        "valid": True,
        "issues": [],
        "warnings": [],
    }

    # 检查关键文件
    required_files = [
        "CLAUDE.md",
        "README.md",
        "STATUS.md",
        "CHANGELOG.md",
        "pyproject.toml",
        "ue5_kb/__init__.py",
        "ue5_kb/cli.py",
        ".claude/skills/ue5kb-dev-guide/skill.md",
        ".claude/skills/ue5kb-dev-guide/impl.py",
    ]

    for file_path in required_files:
        path = PROJECT_ROOT / file_path
        if not path.exists():
            results["valid"] = False
            results["issues"].append(f"缺少文件: {file_path}")

    # 检查目录结构
    required_dirs = [
        "ue5_kb/core",
        "ue5_kb/builders",
        "ue5_kb/parsers",
        "ue5_kb/query",
        "tests",
        "openspec",
    ]

    for dir_path in required_dirs:
        path = PROJECT_ROOT / dir_path
        if not path.exists():
            results["warnings"].append(f"缺少目录: {dir_path}")

    return results


# Skill 主入口点
def skill_main(action: str = "info", **kwargs) -> dict[str, Any]:
    """Skill 主入口点

    Args:
        action: 要执行的操作
        **kwargs: 额外参数

    Returns:
        操作结果
    """
    actions = {
        "info": get_project_info,
        "architecture": get_architecture_overview,
        "pipeline": get_pipeline_info,
        "analyzers": get_analyzer_info,
        "module": lambda: get_module_documentation(kwargs.get("module", "")),
        "workflow": get_development_workflow,
        "practices": get_best_practices,
        "troubleshoot": get_troubleshooting_guide,
        "validate": validate_setup,
    }

    handler = actions.get(action)
    if handler:
        return handler()
    else:
        return {
            "error": f"未知操作: {action}",
            "available_actions": list(actions.keys()),
        }


if __name__ == "__main__":
    import json
    result = skill_main("info")
    print(json.dumps(result, indent=2, ensure_ascii=False))
