"""
UE5 知识库系统 - 代码示例提取器

功能：
- 从测试代码和示例代码中提取使用示例
- 构建代码示例索引
- 支持 "如何使用" 类型的查询
"""

import re
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional


class ExampleExtractor:
    """
    代码示例提取器

    数据来源：
    - 测试代码（*Test.cpp, *Tests.cpp）
    - 示例代码（Examples/, Samples/）
    """

    def __init__(self, db_path: str):
        """
        初始化示例提取器

        Args:
            db_path: SQLite 数据库路径
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def _create_schema(self) -> None:
        """创建数据库表"""
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS code_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_name TEXT NOT NULL,
                target_type TEXT NOT NULL,       -- 'class', 'function', 'property'
                example_code TEXT NOT NULL,
                context_before TEXT,             -- 前5行上下文
                context_after TEXT,              -- 后5行上下文
                source_file TEXT,
                line_number INTEGER,
                description TEXT,                -- 示例描述
                is_verified BOOLEAN DEFAULT 0,  -- 是否经过验证
                quality_score REAL DEFAULT 0.5   -- 质量评分（0-1）
            )
        """)

        # 索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_target_name ON code_examples(target_name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_target_type ON code_examples(target_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quality ON code_examples(quality_score)")

        self.conn.commit()

    def scan_test_directory(self, test_dir: str) -> int:
        """
        扫描测试目录提取示例

        Args:
            test_dir: 测试代码目录

        Returns:
            提取的示例数量
        """
        test_dir = Path(test_dir)
        if not test_dir.exists():
            return 0

        count = 0

        # 查找所有测试文件
        for test_file in test_dir.rglob('*Test*.cpp'):
            examples = self.extract_from_file(str(test_file))
            count += len(examples)

            # 批量插入
            if examples:
                self._insert_examples(examples)

        self.conn.commit()
        return count

    def extract_from_file(self, file_path: str) -> List[Dict[str, Any]]:
        """
        从文件提取代码示例

        Args:
            file_path: 文件路径

        Returns:
            示例列表
        """
        if not os.path.exists(file_path):
            return []

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        examples = []

        # 查找示例代码块
        for i, line in enumerate(lines):
            # 检测类的使用（对象创建）
            class_usage = self._detect_class_usage(line)
            if class_usage:
                example = self._extract_example_context(lines, i, class_usage, 'class')
                example['source_file'] = file_path
                example['line_number'] = i + 1
                examples.append(example)

            # 检测函数调用
            function_calls = self._detect_function_calls(line)
            for func in function_calls:
                example = self._extract_example_context(lines, i, func, 'function')
                example['source_file'] = file_path
                example['line_number'] = i + 1
                examples.append(example)

        # 去重
        examples = self._deduplicate_examples(examples)

        return examples

    def _detect_class_usage(self, line: str) -> Optional[str]:
        """
        检测类的使用（对象创建）

        示例:
        - NewObject<UMyClass>()
        - CreateDefaultSubobject<UMyComponent>("Name")
        - TSharedPtr<FMyClass> Ptr = ...
        """
        # NewObject/CreateDefaultSubobject 模式
        match = re.search(r'(?:NewObject|CreateDefaultSubobject)<([A-Z]\w+)>', line)
        if match:
            return match.group(1)

        # 智能指针模式
        match = re.search(r'T(?:Shared|Unique|Weak)Ptr<([A-Z]\w+)>', line)
        if match:
            return match.group(1)

        # 直接构造
        match = re.search(r'([A-Z]\w+)\s+\w+\s*\(', line)
        if match and not match.group(1).startswith('F'):
            return match.group(1)

        return None

    def _detect_function_calls(self, line: str) -> List[str]:
        """检测函数调用"""
        calls = []

        # 匹配：标识符后跟 (
        for match in re.finditer(r'(\w+)\s*\(', line):
            func_name = match.group(1)

            # 过滤关键字和短名称
            if func_name not in CallAnalyzer.CPP_KEYWORDS and len(func_name) > 2:
                calls.append(func_name)

        return calls

    def _extract_example_context(self, lines: List[str], line_idx: int,
                                 target_name: str, target_type: str) -> Dict[str, Any]:
        """
        提取代码示例及其上下文

        Args:
            lines: 所有行
            line_idx: 当前行索引
            target_name: 目标名称（类名或函数名）
            target_type: 目标类型

        Returns:
            示例字典
        """
        # 提取前后5行上下文
        start = max(0, line_idx - 5)
        end = min(len(lines), line_idx + 6)

        context_before = ''.join(lines[start:line_idx])
        example_line = lines[line_idx]
        context_after = ''.join(lines[line_idx + 1:end])

        # 生成描述
        description = self._generate_description(example_line, target_name, target_type)

        # 质量评分（简化：基于代码长度和注释）
        quality = self._calculate_quality(context_before + example_line + context_after)

        return {
            'target_name': target_name,
            'target_type': target_type,
            'example_code': example_line.strip(),
            'context_before': context_before,
            'context_after': context_after,
            'description': description,
            'quality_score': quality
        }

    def _generate_description(self, code_line: str, target_name: str, target_type: str) -> str:
        """生成示例描述"""
        if target_type == 'class':
            if 'NewObject' in code_line:
                return f"使用 NewObject 创建 {target_name} 实例"
            elif 'CreateDefaultSubobject' in code_line:
                return f"使用 CreateDefaultSubobject 创建 {target_name} 组件"
            else:
                return f"{target_name} 的基本使用"
        else:
            return f"调用 {target_name} 函数"

    def _calculate_quality(self, code: str) -> float:
        """
        计算示例质量评分（0-1）

        考虑因素：
        - 代码长度（太短或太长都降分）
        - 是否有注释
        - 是否有错误处理
        """
        score = 0.5  # 基础分

        # 长度评分
        code_length = len(code.strip())
        if 50 < code_length < 500:
            score += 0.2

        # 注释评分
        if '//' in code or '/*' in code:
            score += 0.1

        # 错误处理评分
        if 'if' in code and ('!' in code or 'nullptr' in code):
            score += 0.2

        return min(score, 1.0)

    def _deduplicate_examples(self, examples: List[Dict]) -> List[Dict]:
        """去重示例"""
        seen = set()
        unique = []

        for ex in examples:
            # 使用 target_name + example_code 作为去重键
            key = (ex['target_name'], ex['example_code'])

            if key not in seen:
                seen.add(key)
                unique.append(ex)

        return unique

    def _insert_examples(self, examples: List[Dict[str, Any]]) -> None:
        """批量插入示例"""
        cursor = self.conn.cursor()

        data = [
            (
                ex['target_name'],
                ex['target_type'],
                ex['example_code'],
                ex.get('context_before', ''),
                ex.get('context_after', ''),
                ex.get('source_file', ''),
                ex.get('line_number', 0),
                ex.get('description', ''),
                ex.get('is_verified', False),
                ex.get('quality_score', 0.5)
            )
            for ex in examples
        ]

        cursor.executemany("""
            INSERT OR IGNORE INTO code_examples (
                target_name, target_type, example_code,
                context_before, context_after,
                source_file, line_number,
                description, is_verified, quality_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data)

    def query_examples(self, target_name: str, min_quality: float = 0.5, limit: int = 5) -> List[Dict]:
        """
        查询代码示例

        Args:
            target_name: 目标名称
            min_quality: 最低质量评分
            limit: 限制返回数量

        Returns:
            示例列表
        """
        cursor = self.conn.cursor()

        cursor.execute("""
            SELECT * FROM code_examples
            WHERE target_name = ? AND quality_score >= ?
            ORDER BY quality_score DESC, is_verified DESC
            LIMIT ?
        """, (target_name, min_quality, limit))

        return [dict(row) for row in cursor.fetchall()]

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        cursor = self.conn.cursor()

        # 总示例数
        cursor.execute("SELECT COUNT(*) FROM code_examples")
        total = cursor.fetchone()[0]

        # 已验证示例数
        cursor.execute("SELECT COUNT(*) FROM code_examples WHERE is_verified = 1")
        verified = cursor.fetchone()[0]

        # 按类型统计
        cursor.execute("""
            SELECT target_type, COUNT(*) as count
            FROM code_examples
            GROUP BY target_type
        """)
        by_type = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            "total_examples": total,
            "verified_examples": verified,
            "by_type": by_type
        }

    def close(self) -> None:
        """关闭数据库连接"""
        self.conn.close()
