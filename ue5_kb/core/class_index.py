"""
UE5 知识库系统 - 类快速索引

提供基于 SQLite 的类快速查找和模糊搜索能力
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Any, Optional


class ClassIndex:
    """
    类快速索引

    功能:
    - 基于 SQLite 的类名称索引
    - 支持 < 10ms 的快速查询
    - 支持模糊搜索 (LIKE 查询)
    - 存储完整的类继承和属性信息
    """

    def __init__(self, db_path: str):
        """
        初始化类索引

        Args:
            db_path: SQLite 数据库路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        """创建数据库表结构"""
        cursor = self.conn.cursor()

        # 创建类索引表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS class_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                module TEXT NOT NULL,
                namespace TEXT,
                parent_classes TEXT,              -- JSON 序列化
                interfaces TEXT,                  -- JSON 序列化
                file_path TEXT,
                line_number INTEGER,
                is_uclass BOOLEAN DEFAULT 0,
                is_struct BOOLEAN DEFAULT 0,
                is_interface BOOLEAN DEFAULT 0,
                is_blueprintable BOOLEAN DEFAULT 0,
                method_count INTEGER DEFAULT 0,
                property_count INTEGER DEFAULT 0,
                UNIQUE(name, module, file_path, line_number)
            )
        """)

        # 创建索引以优化查询
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_class_name ON class_index(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_class_module ON class_index(module)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_class_namespace ON class_index(namespace)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_class_uclass ON class_index(is_uclass)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_class_blueprintable ON class_index(is_blueprintable)")

        self.conn.commit()

    def add_class(self, class_info: Dict[str, Any]) -> None:
        """
        添加类到索引

        Args:
            class_info: 类信息字典
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO class_index (
                name, module, namespace, parent_classes, interfaces,
                file_path, line_number,
                is_uclass, is_struct, is_interface, is_blueprintable,
                method_count, property_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            class_info['name'],
            class_info['module'],
            class_info.get('namespace', ''),
            json.dumps(class_info.get('parent_classes', [])),
            json.dumps(class_info.get('interfaces', [])),
            class_info.get('file_path', ''),
            class_info.get('line_number', 0),
            class_info.get('is_uclass', False),
            class_info.get('is_struct', False),
            class_info.get('is_interface', False),
            class_info.get('is_blueprintable', False),
            class_info.get('method_count', 0),
            class_info.get('property_count', 0)
        ))

    def add_classes_batch(self, class_infos: List[Dict[str, Any]]) -> None:
        """
        批量添加类（性能优化）

        Args:
            class_infos: 类信息列表
        """
        cursor = self.conn.cursor()

        data = []
        for cls_info in class_infos:
            data.append((
                cls_info['name'],
                cls_info['module'],
                cls_info.get('namespace', ''),
                json.dumps(cls_info.get('parent_classes', [])),
                json.dumps(cls_info.get('interfaces', [])),
                cls_info.get('file_path', ''),
                cls_info.get('line_number', 0),
                cls_info.get('is_uclass', False),
                cls_info.get('is_struct', False),
                cls_info.get('is_interface', False),
                cls_info.get('is_blueprintable', False),
                cls_info.get('method_count', 0),
                cls_info.get('property_count', 0)
            ))

        cursor.executemany("""
            INSERT OR REPLACE INTO class_index (
                name, module, namespace, parent_classes, interfaces,
                file_path, line_number,
                is_uclass, is_struct, is_interface, is_blueprintable,
                method_count, property_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data)

        self.conn.commit()

    def query_by_name(self, name: str, module_hint: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        按名称查询类（< 10ms）

        Args:
            name: 类名称
            module_hint: 模块提示（可选，用于加速查询）

        Returns:
            类信息列表
        """
        cursor = self.conn.cursor()

        if module_hint:
            cursor.execute("""
                SELECT * FROM class_index
                WHERE name = ? AND module LIKE ?
                ORDER BY is_uclass DESC, module ASC
            """, (name, f'%{module_hint}%'))
        else:
            cursor.execute("""
                SELECT * FROM class_index
                WHERE name = ?
                ORDER BY is_uclass DESC, module ASC
            """, (name,))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def search_by_keyword(self, keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        按关键字模糊搜索类

        Args:
            keyword: 搜索关键字
            limit: 限制返回数量

        Returns:
            类信息列表
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM class_index
            WHERE name LIKE ?
            ORDER BY is_uclass DESC, name ASC
            LIMIT ?
        """, (f'%{keyword}%', limit))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def query_by_module(self, module: str) -> List[Dict[str, Any]]:
        """
        查询模块中的所有类

        Args:
            module: 模块名称

        Returns:
            类信息列表
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM class_index WHERE module = ?
        """, (module,))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def query_by_parent(self, parent_class: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        查询继承自指定类的所有子类

        Args:
            parent_class: 父类名称
            limit: 限制返回数量

        Returns:
            子类信息列表
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM class_index
            WHERE parent_classes LIKE ?
            ORDER BY name ASC
            LIMIT ?
        """, (f'%"{parent_class}"%', limit))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def query_blueprintable(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        查询所有 Blueprint 可创建的类

        Args:
            limit: 限制返回数量

        Returns:
            类信息列表
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM class_index
            WHERE is_blueprintable = 1
            LIMIT ?
        """, (limit,))

        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """将数据库行转换为字典"""
        return {
            'id': row['id'],
            'name': row['name'],
            'module': row['module'],
            'namespace': row['namespace'],
            'parent_classes': json.loads(row['parent_classes']) if row['parent_classes'] else [],
            'interfaces': json.loads(row['interfaces']) if row['interfaces'] else [],
            'file_path': row['file_path'],
            'line_number': row['line_number'],
            'is_uclass': bool(row['is_uclass']),
            'is_struct': bool(row['is_struct']),
            'is_interface': bool(row['is_interface']),
            'is_blueprintable': bool(row['is_blueprintable']),
            'method_count': row['method_count'],
            'property_count': row['property_count']
        }

    def get_statistics(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        cursor = self.conn.cursor()

        # 总类数
        cursor.execute("SELECT COUNT(*) FROM class_index")
        total = cursor.fetchone()[0]

        # UClass 数量
        cursor.execute("SELECT COUNT(*) FROM class_index WHERE is_uclass = 1")
        uclass_count = cursor.fetchone()[0]

        # UStruct 数量
        cursor.execute("SELECT COUNT(*) FROM class_index WHERE is_struct = 1")
        struct_count = cursor.fetchone()[0]

        # Blueprintable 类数量
        cursor.execute("SELECT COUNT(*) FROM class_index WHERE is_blueprintable = 1")
        blueprintable_count = cursor.fetchone()[0]

        # 按模块统计
        cursor.execute("""
            SELECT module, COUNT(*) as count
            FROM class_index
            GROUP BY module
            ORDER BY count DESC
            LIMIT 10
        """)
        top_modules = [{'module': row[0], 'count': row[1]} for row in cursor.fetchall()]

        return {
            'total_classes': total,
            'uclass_count': uclass_count,
            'struct_count': struct_count,
            'blueprintable_count': blueprintable_count,
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
