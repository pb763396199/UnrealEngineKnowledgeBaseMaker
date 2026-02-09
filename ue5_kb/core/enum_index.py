"""
UE5 知识库系统 - 枚举快速索引 (v2.14.0 新增)

提供基于 SQLite 的枚举快速查找和模糊搜索能力
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, List, Any, Optional


class EnumIndex:
    """
    枚举快速索引

    功能:
    - 基于 SQLite 的枚举名称索引
    - 支持 < 10ms 的快速查询
    - 支持模糊搜索 (LIKE 查询)
    - 存储枚举值列表和 UENUM 说明符
    """

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS enum_index (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                module TEXT NOT NULL,
                namespace TEXT,
                values_json TEXT,
                is_uenum BOOLEAN DEFAULT 0,
                file_path TEXT,
                line_number INTEGER,
                doc_comment TEXT,
                specifiers TEXT,
                UNIQUE(name, module, file_path, line_number)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_enum_name ON enum_index(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_enum_module ON enum_index(module)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_enum_uenum ON enum_index(is_uenum)")
        self.conn.commit()

    def add_enum(self, enum_info: Dict[str, Any]) -> None:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO enum_index (
                name, module, namespace, values_json, is_uenum,
                file_path, line_number, doc_comment, specifiers
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            enum_info['name'],
            enum_info['module'],
            enum_info.get('namespace', ''),
            json.dumps(enum_info.get('values', [])),
            enum_info.get('is_uenum', False),
            enum_info.get('file_path', ''),
            enum_info.get('line_number', 0),
            enum_info.get('doc_comment', ''),
            json.dumps(enum_info.get('specifiers', {}))
        ))

    def add_enums_batch(self, enum_infos: List[Dict[str, Any]]) -> None:
        cursor = self.conn.cursor()
        data = []
        for e in enum_infos:
            data.append((
                e['name'], e['module'], e.get('namespace', ''),
                json.dumps(e.get('values', [])), e.get('is_uenum', False),
                e.get('file_path', ''), e.get('line_number', 0),
                e.get('doc_comment', ''), json.dumps(e.get('specifiers', {}))
            ))
        cursor.executemany("""
            INSERT OR REPLACE INTO enum_index (
                name, module, namespace, values_json, is_uenum,
                file_path, line_number, doc_comment, specifiers
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data)
        self.conn.commit()

    def query_by_name(self, name: str, module_hint: Optional[str] = None) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        if module_hint:
            cursor.execute("""
                SELECT * FROM enum_index WHERE name = ? AND module LIKE ?
                ORDER BY is_uenum DESC, module ASC
            """, (name, f'%{module_hint}%'))
        else:
            cursor.execute("""
                SELECT * FROM enum_index WHERE name = ?
                ORDER BY is_uenum DESC, module ASC
            """, (name,))
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def search_by_keyword(self, keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM enum_index WHERE name LIKE ?
            ORDER BY is_uenum DESC, name ASC LIMIT ?
        """, (f'%{keyword}%', limit))
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def search_by_value(self, value_keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
        """搜索包含特定枚举值的枚举"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM enum_index WHERE values_json LIKE ?
            ORDER BY is_uenum DESC, name ASC LIMIT ?
        """, (f'%{value_keyword}%', limit))
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            'id': row['id'],
            'name': row['name'],
            'module': row['module'],
            'namespace': row['namespace'],
            'values': json.loads(row['values_json']) if row['values_json'] else [],
            'is_uenum': bool(row['is_uenum']),
            'file_path': row['file_path'],
            'line_number': row['line_number'],
            'doc_comment': row['doc_comment'] or '',
            'specifiers': json.loads(row['specifiers']) if row['specifiers'] else {}
        }

    def get_statistics(self) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM enum_index")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM enum_index WHERE is_uenum = 1")
        uenum_count = cursor.fetchone()[0]
        cursor.execute("""
            SELECT module, COUNT(*) as count FROM enum_index
            GROUP BY module ORDER BY count DESC LIMIT 10
        """)
        top_modules = [{'module': r[0], 'count': r[1]} for r in cursor.fetchall()]
        return {'total_enums': total, 'uenum_count': uenum_count, 'top_modules': top_modules}

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __del__(self):
        if hasattr(self, 'conn'):
            self.conn.close()
