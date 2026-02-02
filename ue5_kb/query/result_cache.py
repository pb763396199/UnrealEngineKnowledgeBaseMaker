"""
UE5 知识库系统 - 查询结果缓存

基于 Observation Masking 理论：
- 替换冗长的输出为紧凑的引用
- 保留关键信息摘要
- 按需加载完整结果
"""

from typing import Dict, List, Any, Optional
import uuid
import time
import json


class ResultCache:
    """
    查询结果缓存系统

    功能：
    - 存储大型查询结果
    - 返回引用 ID 和摘要
    - 支持按需检索完整结果
    - 自动过期管理
    """

    def __init__(self, ttl_seconds: int = 3600):
        """
        初始化结果缓存

        Args:
            ttl_seconds: 缓存生存时间（秒）
        """
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.ttl = ttl_seconds

    def store(self, result: Any, summary: Optional[Dict] = None) -> str:
        """
        存储查询结果，返回引用 ID

        Args:
            result: 完整结果
            summary: 可选的摘要信息

        Returns:
            引用 ID
        """
        # 生成唯一引用 ID
        ref_id = f"ref_{uuid.uuid4().hex[:8]}"

        # 存储结果和元数据
        self.cache[ref_id] = {
            'result': result,
            'summary': summary or self._generate_summary(result),
            'created_at': time.time(),
            'access_count': 0
        }

        return ref_id

    def retrieve(self, ref_id: str) -> Optional[Any]:
        """
        通过引用 ID 获取完整结果

        Args:
            ref_id: 引用 ID

        Returns:
            完整结果，如果过期则返回 None
        """
        if ref_id not in self.cache:
            return None

        entry = self.cache[ref_id]

        # 检查是否过期
        if time.time() - entry['created_at'] > self.ttl:
            del self.cache[ref_id]
            return None

        # 增加访问计数
        entry['access_count'] += 1

        return entry['result']

    def get_summary(self, ref_id: str) -> Optional[Dict]:
        """获取摘要信息（不增加访问计数）"""
        if ref_id not in self.cache:
            return None

        return self.cache[ref_id].get('summary')

    def mask_large_result(self, result: Any, threshold: int = 5) -> Dict[str, Any]:
        """
        屏蔽大型结果（Observation Masking）

        Args:
            result: 查询结果
            threshold: 阈值（超过此数量触发屏蔽）

        Returns:
            屏蔽后的结果（摘要 + 引用 ID）
        """
        # 判断结果是否需要屏蔽
        if isinstance(result, list) and len(result) > threshold:
            # 生成摘要
            summary = {
                "type": "list",
                "total_count": len(result),
                "sample": result[:threshold],  # 仅显示前N个
                "item_type": type(result[0]).__name__ if result else "unknown"
            }

            # 存储完整结果
            ref_id = self.store(result, summary)

            return {
                "masked": True,
                "summary": f"找到 {len(result)} 个结果",
                "sample": result[:threshold],
                "ref_id": ref_id,
                "tip": f"使用 get_full_results('{ref_id}') 查看完整列表"
            }

        elif isinstance(result, dict) and self._estimate_tokens(result) > 1000:
            # 字典结果过大
            summary = {
                "type": "dict",
                "keys": list(result.keys()),
                "size_estimate": f"~{self._estimate_tokens(result)} tokens"
            }

            ref_id = self.store(result, summary)

            return {
                "masked": True,
                "summary": f"大型结果（{len(result)} 个字段）",
                "keys": list(result.keys())[:10],  # 仅显示前10个键
                "ref_id": ref_id,
                "tip": f"使用 get_full_results('{ref_id}') 查看完整内容"
            }

        else:
            # 结果不大，直接返回
            return {
                "masked": False,
                "result": result
            }

    def _generate_summary(self, result: Any) -> Dict[str, Any]:
        """自动生成结果摘要"""
        if isinstance(result, list):
            return {
                "type": "list",
                "count": len(result),
                "sample": result[:3]
            }
        elif isinstance(result, dict):
            return {
                "type": "dict",
                "keys": list(result.keys())[:10]
            }
        else:
            return {
                "type": type(result).__name__,
                "value": str(result)[:100]
            }

    def _estimate_tokens(self, obj: Any) -> int:
        """估算对象的 token 数量（粗略）"""
        # 简化估算：4个字符 ≈ 1个 token
        json_str = json.dumps(obj, ensure_ascii=False)
        return len(json_str) // 4

    def cleanup_expired(self) -> int:
        """清理过期缓存"""
        now = time.time()
        expired = [
            ref_id for ref_id, entry in self.cache.items()
            if now - entry['created_at'] > self.ttl
        ]

        for ref_id in expired:
            del self.cache[ref_id]

        return len(expired)

    def get_statistics(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_items = len(self.cache)
        total_accesses = sum(entry['access_count'] for entry in self.cache.values())

        return {
            "cached_items": total_items,
            "total_accesses": total_accesses,
            "avg_accesses": total_accesses / total_items if total_items > 0 else 0,
            "cache_refs": list(self.cache.keys())
        }


# 全局单例（会话级）
_global_result_cache = None


def get_result_cache(ttl_seconds: int = 3600) -> ResultCache:
    """获取全局结果缓存实例"""
    global _global_result_cache
    if _global_result_cache is None:
        _global_result_cache = ResultCache(ttl_seconds)
    return _global_result_cache
