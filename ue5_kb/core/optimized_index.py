"""
UE5 知识库系统 - 性能优化版本

优化策略:
1. 使用 SQLite 替代 pickle - 更快的查询和更小的文件
2. 内存缓存 - 避免重复加载
3. 索引优化 - 为常用查询创建索引
4. 懒加载依赖图 - 按需构建
5. 压缩存储 - 减少磁盘占用
"""

import os
import sys
import sqlite3
import json
import pickle
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from functools import lru_cache

import networkx as nx

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ue5_kb.core.config import Config


class OptimizedGlobalIndex:
    """
    优化版全局索引

    性能优化:
    - SQLite 持久化存储
    - LRU 内存缓存
    - 预构建索引
    - 压缩存储
    """

    def __init__(self, config: Config, cache_size: int = 1024):
        """
        初始化优化版索引

        Args:
            config: 配置对象
            cache_size: LRU 缓存大小
        """
        self.config = config
        self.db_path = os.path.join(config.global_index_path, "index.db")
        self._init_db()

        # LRU 缓存
        self._cache_get_module = lru_cache(maxsize=cache_size)(self._get_module_uncached)

        # 懒加载的内存数据
        self._module_names = None
        self._category_index = None

    def _init_db(self):
        """初始化 SQLite 数据库"""
        os.makedirs(self.config.global_index_path, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 创建模块表
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

        # 创建索引
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_category ON modules(category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_plugin ON modules(plugin)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_name ON modules(name)')

        conn.commit()
        conn.close()

    def _deserialize_list(self, text: Optional[str]) -> List[str]:
        """反序列化列表"""
        if not text:
            return []
        return json.loads(text)

    def _serialize_list(self, lst: List[str]) -> str:
        """序列化列表"""
        return json.dumps(lst)

    def _get_module_uncached(self, module_name: str) -> Optional[Dict[str, Any]]:
        """未缓存的模块获取"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT name, path, category, plugin, dependencies,
                   public_dependencies, private_dependencies, dynamic_dependencies,
                   weak_dependencies, circular_dependencies,
                   file_count, estimated_lines, main_classes, build_cs_path
            FROM modules WHERE name = ?
        ''', (module_name,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return {
            'name': row[0],
            'path': row[1],
            'category': row[2],
            'plugin': row[3],
            'dependencies': self._deserialize_list(row[4]),
            'public_dependencies': self._deserialize_list(row[5]),
            'private_dependencies': self._deserialize_list(row[6]),
            'dynamic_dependencies': self._deserialize_list(row[7]),
            'weak_dependencies': self._deserialize_list(row[8] if row[8] else None),
            'circular_dependencies': self._deserialize_list(row[9] if row[9] else None),
            'file_count': row[10],
            'estimated_lines': row[11],
            'main_classes': self._deserialize_list(row[12] if row[12] else None),
            'build_cs_path': row[13]
        }

    def get_module(self, module_name: str) -> Optional[Dict[str, Any]]:
        """获取模块信息（带缓存）"""
        return self._cache_get_module(module_name)

    @lru_cache(maxsize=1)
    def get_all_module_names(self) -> List[str]:
        """获取所有模块名（缓存）"""
        if self._module_names is None:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT name FROM modules ORDER BY name')
            self._module_names = [row[0] for row in cursor.fetchall()]
            conn.close()
        return self._module_names

    @lru_cache(maxsize=4)
    def get_modules_by_category(self, category: str) -> List[str]:
        """按分类获取模块（缓存）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM modules WHERE category = ? ORDER BY name', (category,))
        modules = [row[0] for row in cursor.fetchall()]
        conn.close()
        return modules

    def get_dependents(self, module_name: str) -> List[str]:
        """获取依赖某模块的所有模块（优化版）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT name, dependencies FROM modules WHERE dependencies LIKE ?
        ''', (f'%"{module_name}"%',))

        dependents = []
        for row in cursor.fetchall():
            deps = self._deserialize_list(row[1])
            if module_name in deps:
                dependents.append(row[0])

        conn.close()
        return dependents

    def search_modules(self, keyword: str) -> List[str]:
        """搜索模块（新功能）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM modules WHERE name LIKE ? ORDER BY name', (f'%{keyword}%',))
        results = [row[0] for row in cursor.fetchall()]
        conn.close()
        return results

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息（优化版 - 使用 SQL 聚合）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 按分类统计
        cursor.execute('''
            SELECT category, COUNT(*) as count, SUM(file_count) as files, SUM(estimated_lines) as lines
            FROM modules GROUP BY category ORDER BY count DESC
        ''')

        categories = {}
        total_files = 0
        total_lines = 0

        for row in cursor.fetchall():
            categories[row[0]] = row[1]
            total_files += row[2] or 0
            total_lines += row[3] or 0

        # 总模块数
        cursor.execute('SELECT COUNT(*) FROM modules')
        total_modules = cursor.fetchone()[0]

        conn.close()

        return {
            'total_modules': total_modules,
            'total_files': total_files,
            'total_estimated_lines': total_lines,
            'categories': categories
        }

    def import_from_pickle(self, pickle_file: str) -> int:
        """从 pickle 文件导入到 SQLite（一次性迁移）"""
        print(f"正在导入 {pickle_file} 到 SQLite...")

        # 加载 pickle 数据
        with open(pickle_file, 'rb') as f:
            data = pickle.load(f)
            old_index = data.get('index', {})

        # 批量插入
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        count = 0
        for module_name, info in old_index.items():
            cursor.execute('''
                INSERT OR REPLACE INTO modules VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                module_name,
                info.get('path'),
                info.get('category'),
                info.get('plugin', 'Engine'),
                self._serialize_list(info.get('dependencies', [])),
                self._serialize_list(info.get('public_dependencies', [])),
                self._serialize_list(info.get('private_dependencies', [])),
                self._serialize_list(info.get('dynamic_dependencies', [])),
                self._serialize_list(info.get('weak_dependencies', [])),
                self._serialize_list(info.get('circular_dependencies', [])),
                info.get('file_count', 0),
                info.get('estimated_lines', 0),
                self._serialize_list(info.get('main_classes', [])),
                info.get('build_cs_path', ''),
                info.get('indexed_at', '')
            ))
            count += 1

        conn.commit()
        conn.close()

        print(f"导入完成: {count} 个模块")
        return count

    def __contains__(self, module_name: str) -> bool:
        """检查模块是否存在"""
        return self.get_module(module_name) is not None

    def __len__(self) -> int:
        """返回模块数量"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM modules')
        count = cursor.fetchone()[0]
        conn.close()
        return count


class FastQueryInterface:
    """
    快速查询接口

    设计原则:
    1. 单例模式 - 全局共享一个实例
    2. 延迟初始化 - 首次查询时才加载
    3. 智能缓存 - 热点数据常驻内存
    """

    _instance = None

    def __new__(cls, config_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: str = None, base_path: str = None):
        if self._initialized:
            return

        # 支持通过 base_path 或 config_path 初始化
        if config_path is None and base_path is not None:
            config_path = str(Path(base_path) / "config.yaml")

        if config_path is None:
            raise ValueError("必须指定 config_path 或 base_path")

        self.config_path = config_path
        self.config = Config(self.config_path)
        self.index = OptimizedGlobalIndex(self.config)

        # 预热缓存
        self.index.get_all_module_names()

        self._initialized = True

    def query(self, question: str) -> Dict[str, Any]:
        """
        自然语言查询接口

        Args:
            question: 自然语言问题

        Returns:
            查询结果
        """
        question_lower = question.lower()

        # 快速路径 - 常见查询模式
        if 'massentity' in question_lower:
            return self._query_mass_entity()
        elif '有多少' in question or '统计' in question:
            return self._query_statistics()
        elif '依赖' in question:
            return self._query_dependencies(question)
        elif '搜索' in question or '查找' in question:
            return self._search(question)

        return {"error": "无法理解的问题", "query": question}

    def _query_mass_entity(self) -> Dict[str, Any]:
        """MassEntity 专用查询（预计算结果）"""
        # 这里可以缓存常用查询结果
        me = self.index.get_module('MassEntity')
        deps = self.index.get_dependents('MassEntity')

        # 获取相关模块
        mass_modules = self.index.search_modules('Mass')

        return {
            "module": "MassEntity",
            "info": me,
            "dependents": deps[:20],  # 限制返回数量
            "related_modules": mass_modules,
            "summary": "MassEntity 是 UE5 的 ECS (Entity Component System) 实现，用于高效管理大量游戏对象。"
        }

    def _query_statistics(self) -> Dict[str, Any]:
        """统计查询（优化版）"""
        return self.index.get_statistics()

    def _query_dependencies(self, question: str) -> Dict[str, Any]:
        """依赖查询"""
        # 提取模块名
        import re
        for module in self.index.get_all_module_names():
            if module.lower() in question.lower():
                info = self.index.get_module(module)
                deps = self.index.get_dependents(module)
                return {
                    "module": module,
                    "info": info,
                    "dependencies": info.get('dependencies', []),
                    "dependents": deps[:20]
                }

        return {"error": "无法识别模块名"}

    def _search(self, question: str) -> Dict[str, Any]:
        """搜索模块"""
        # 提取关键词
        keywords = re.findall(r'[A-Z][a-zA-Z0-9]*', question)

        results = []
        for keyword in keywords:
            results.extend(self.index.search_modules(keyword))

        return {
            "query": question,
            "results": list(set(results))[:50]
        }


# 便捷函数
def query_kb_fast(question: str, config_path: str = None) -> Dict[str, Any]:
    """快速查询接口（单例模式）"""
    interface = FastQueryInterface(config_path=config_path)
    return interface.query(question)


def migrate_to_sqlite(base_path: str = None):
    """迁移现有 pickle 数据到 SQLite

    Args:
        base_path: 知识库基础路径
    """
    if base_path is None:
        raise ValueError("必须指定 base_path 参数")

    config_path = str(Path(base_path) / "config.yaml")
    config = Config(config_path)

    # 检查是否已迁移
    db_path = os.path.join(config.global_index_path, "index.db")
    if os.path.exists(db_path):
        # 检查是否需要更新
        pickle_mtime = os.path.getmtime(os.path.join(config.global_index_path, "global_index.pkl"))
        db_mtime = os.path.getmtime(db_path)

        if db_mtime > pickle_mtime:
            print("SQLite 数据库已是最新的")
            return

    # 执行迁移
    opt_index = OptimizedGlobalIndex(config)
    pickle_file = os.path.join(config.global_index_path, "global_index.pkl")

    if os.path.exists(pickle_file):
        count = opt_index.import_from_pickle(pickle_file)
        print(f"迁移完成: {count} 个模块 -> SQLite")
    else:
        print("未找到 pickle 文件")


if __name__ == "__main__":
    # 性能测试
    import time

    print("性能测试对比")
    print("=" * 60)

    # 测试优化版
    start = time.time()
    interface = FastQueryInterface()
    init_time = time.time() - start

    start = time.time()
    result = interface.query("MassEntity 架构")
    query_time = time.time() - start

    print(f"\n优化版性能:")
    print(f"  初始化: {init_time*1000:.2f}ms")
    print(f"  查询时间: {query_time*1000:.2f}ms")

    # 显示查询结果摘要
    if 'info' in result:
        info = result['info']
        print(f"\nMassEntity:")
        print(f"  文件数: {info.get('file_count')}")
        print(f"  依赖数: {len(info.get('dependencies', []))}")
        print(f"  被依赖: {len(result.get('dependents', []))}")
