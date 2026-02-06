"""
UE5 知识库系统 - 函数快速索引

提供基于 SQLite 的函数快速查找能力，优化 query_function_info 性能
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Any, Optional


class FunctionIndex:
    """
    函数快速索引

    功能:
    - 基于 SQLite 的函数名称索引
    - 支持 < 10ms 的快速查询
    - 存储完整的函数签名和参数信息
    """

    def __init__(self, db_path: str):
        """
        初始化函数索引

        Args:
            db_path: SQLite 数据库路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row  # 支持字典式访问
        self._create_schema()

    def _create_schema(self) -> None:
        """创建数据库表结构"""
        cursor = self.conn.cursor()

        # 创建函数索引表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS function_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                module TEXT NOT NULL,
                class_name TEXT,
                return_type TEXT,
                parameters TEXT,                -- JSON 序列化
                signature TEXT,                 -- 完整签名（便于显示）
                file_path TEXT,                 -- 声明位置（头文件）
                line_number INTEGER,            -- 声明行号
                impl_file_path TEXT,            -- 实现位置（cpp文件）
                impl_line_number INTEGER,       -- 实现行号
                is_virtual BOOLEAN DEFAULT 0,
                is_const BOOLEAN DEFAULT 0,
                is_static BOOLEAN DEFAULT 0,
                is_override BOOLEAN DEFAULT 0,
                is_blueprint_callable BOOLEAN DEFAULT 0,
                ufunction_specifiers TEXT,      -- JSON 序列化
                UNIQUE(name, module, class_name, file_path, line_number)
            )
        """)

        # 数据库迁移：为旧版本添加新字段
        try:
            # 检查表结构
            cursor.execute("PRAGMA table_info(function_index)")
            columns = {row[1] for row in cursor.fetchall()}

            # 添加新字段（如果不存在）
            if 'impl_file_path' not in columns:
                cursor.execute("ALTER TABLE function_index ADD COLUMN impl_file_path TEXT")
                print("  [迁移] 添加 impl_file_path 字段")

            if 'impl_line_number' not in columns:
                cursor.execute("ALTER TABLE function_index ADD COLUMN impl_line_number INTEGER DEFAULT 0")
                print("  [迁移] 添加 impl_line_number 字段")

        except Exception as e:
            print(f"  警告: 数据库迁移失败: {e}")

        # 创建索引以优化查询
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_func_name ON function_index(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_func_module ON function_index(module)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_func_class ON function_index(class_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_func_bp ON function_index(is_blueprint_callable)")

        self.conn.commit()

    def add_function(self, func_info: Dict[str, Any]) -> None:
        """
        添加函数到索引

        Args:
            func_info: 函数信息字典
        """
        cursor = self.conn.cursor()

        # 序列化参数列表和 UFUNCTION 参数
        parameters_json = json.dumps(func_info.get('parameters', []))
        ufunction_spec_json = json.dumps(func_info.get('ufunction_specifiers', {}))

        cursor.execute("""
            INSERT OR REPLACE INTO function_index (
                name, module, class_name, return_type, parameters, signature,
                file_path, line_number, impl_file_path, impl_line_number,
                is_virtual, is_const, is_static, is_override,
                is_blueprint_callable, ufunction_specifiers
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            func_info['name'],
            func_info['module'],
            func_info.get('class_name'),
            func_info.get('return_type', ''),
            parameters_json,
            func_info.get('signature', ''),
            func_info.get('file_path', ''),
            func_info.get('line_number', 0),
            func_info.get('impl_file_path', ''),
            func_info.get('impl_line_number', 0),
            func_info.get('is_virtual', False),
            func_info.get('is_const', False),
            func_info.get('is_static', False),
            func_info.get('is_override', False),
            func_info.get('is_blueprint_callable', False),
            ufunction_spec_json
        ))

    def add_functions_batch(self, func_infos: List[Dict[str, Any]]) -> None:
        """
        批量添加函数（性能优化）

        Args:
            func_infos: 函数信息列表
        """
        cursor = self.conn.cursor()

        data = []
        for func_info in func_infos:
            parameters_json = json.dumps(func_info.get('parameters', []))
            ufunction_spec_json = json.dumps(func_info.get('ufunction_specifiers', {}))

            data.append((
                func_info['name'],
                func_info['module'],
                func_info.get('class_name'),
                func_info.get('return_type', ''),
                parameters_json,
                func_info.get('signature', ''),
                func_info.get('file_path', ''),
                func_info.get('line_number', 0),
                func_info.get('impl_file_path', ''),
                func_info.get('impl_line_number', 0),
                func_info.get('is_virtual', False),
                func_info.get('is_const', False),
                func_info.get('is_static', False),
                func_info.get('is_override', False),
                func_info.get('is_blueprint_callable', False),
                ufunction_spec_json
            ))

        cursor.executemany("""
            INSERT OR REPLACE INTO function_index (
                name, module, class_name, return_type, parameters, signature,
                file_path, line_number, impl_file_path, impl_line_number,
                is_virtual, is_const, is_static, is_override,
                is_blueprint_callable, ufunction_specifiers
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data)

        self.conn.commit()

    def query_by_name(self, name: str, module_hint: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        按名称查询函数（< 10ms）

        Args:
            name: 函数名称
            module_hint: 模块提示（可选，用于加速查询）

        Returns:
            函数信息列表
        """
        cursor = self.conn.cursor()

        if module_hint:
            # 使用模块提示加速查询
            cursor.execute("""
                SELECT * FROM function_index
                WHERE name = ? AND module LIKE ?
                ORDER BY is_blueprint_callable DESC, module ASC
            """, (name, f'%{module_hint}%'))
        else:
            # 全局查询
            cursor.execute("""
                SELECT * FROM function_index
                WHERE name = ?
                ORDER BY is_blueprint_callable DESC, module ASC
            """, (name,))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def query_by_module(self, module: str) -> List[Dict[str, Any]]:
        """
        查询模块中的所有函数

        Args:
            module: 模块名称

        Returns:
            函数信息列表
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM function_index WHERE module = ?
        """, (module,))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def search_by_keyword(self, keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        按关键字模糊搜索函数

        Args:
            keyword: 搜索关键字
            limit: 限制返回数量

        Returns:
            函数信息列表
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM function_index
            WHERE name LIKE ?
            ORDER BY is_blueprint_callable DESC, name ASC
            LIMIT ?
        """, (f'%{keyword}%', limit))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def query_blueprint_callable(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        查询所有 Blueprint 可调用的函数

        Args:
            limit: 限制返回数量

        Returns:
            函数信息列表
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM function_index
            WHERE is_blueprint_callable = 1
            LIMIT ?
        """, (limit,))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            'id': row['id'],
            'name': row['name'],
            'module': row['module'],
            'class_name': row['class_name'],
            'return_type': row['return_type'],
            'parameters': json.loads(row['parameters']) if row['parameters'] else [],
            'signature': row['signature'],
            'file_path': row['file_path'],
            'line_number': row['line_number'],
            'impl_file_path': row['impl_file_path'],
            'impl_line_number': row['impl_line_number'],
            'is_virtual': bool(row['is_virtual']),
            'is_const': bool(row['is_const']),
            'is_static': bool(row['is_static']),
            'is_override': bool(row['is_override']),
            'is_blueprint_callable': bool(row['is_blueprint_callable']),
            'ufunction_specifiers': json.loads(row['ufunction_specifiers']) if row['ufunction_specifiers'] else {}
        }

    def get_statistics(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        cursor = self.conn.cursor()

        # 总函数数
        cursor.execute("SELECT COUNT(*) FROM function_index")
        total = cursor.fetchone()[0]

        # Blueprint 可调用函数数
        cursor.execute("SELECT COUNT(*) FROM function_index WHERE is_blueprint_callable = 1")
        bp_count = cursor.fetchone()[0]

        # 按模块统计
        cursor.execute("""
            SELECT module, COUNT(*) as count
            FROM function_index
            GROUP BY module
            ORDER BY count DESC
            LIMIT 10
        """)
        top_modules = [{'module': row[0], 'count': row[1]} for row in cursor.fetchall()]

        return {
            'total_functions': total,
            'blueprint_callable': bp_count,
            'top_modules': top_modules
        }

    def commit(self) -> None:
        """提交事务"""
        self.conn.commit()

    def close(self) -> None:
        """关闭数据库连接"""
        self.conn.close()

    def __del__(self):
        """析构时关闭连接"""
        if hasattr(self, 'conn'):
            self.conn.close()
