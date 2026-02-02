"""
UE5 知识库系统 - Token 预算管理

基于 Context Optimization 理论：
- 显式的 Token 预算分配
- 监控使用情况并触发优化
- 防止 context 过载
"""

from typing import Dict, Any, Optional
from enum import Enum


class ContextCategory(Enum):
    """Context 分类"""
    SYSTEM_PROMPT = "system_prompt"      # 稳定，KV-cacheable
    TOOL_DEFINITIONS = "tool_definitions"  # 稳定，KV-cacheable
    QUERY_RESULTS = "query_results"      # 动态，需优化
    MESSAGE_HISTORY = "message_history"  # 需压缩
    RESERVED = "reserved"                # 保留缓冲区


class TokenBudget:
    """
    Token 预算管理器

    功能：
    - 为不同类型的 context 分配预算
    - 监控使用情况
    - 触发优化策略
    """

    # 默认预算分配（总共 ~7000 tokens，为 200K context 预留空间）
    DEFAULT_BUDGETS = {
        ContextCategory.SYSTEM_PROMPT: 500,      # 稳定内容
        ContextCategory.TOOL_DEFINITIONS: 1000,  # 工具定义
        ContextCategory.QUERY_RESULTS: 2000,     # 查询结果（最易超标）
        ContextCategory.MESSAGE_HISTORY: 3000,   # 对话历史
        ContextCategory.RESERVED: 500            # 保留
    }

    # 优化触发阈值（使用率）
    OPTIMIZATION_THRESHOLD = 0.8  # 80%

    def __init__(self, budgets: Optional[Dict[ContextCategory, int]] = None):
        """
        初始化 Token 预算管理器

        Args:
            budgets: 自定义预算分配
        """
        self.budgets = budgets or self.DEFAULT_BUDGETS.copy()
        self.usage = {cat: 0 for cat in ContextCategory}
        self.optimization_triggered = {cat: False for cat in ContextCategory}

    def allocate(self, category: ContextCategory, tokens: int) -> bool:
        """
        分配 tokens 给指定类别

        Args:
            category: Context 类别
            tokens: 需要的 token 数量

        Returns:
            是否成功分配
        """
        budget = self.budgets[category]
        current = self.usage[category]

        if current + tokens > budget:
            # 超出预算，触发优化
            self.trigger_optimization(category, current + tokens, budget)
            return False

        # 分配成功
        self.usage[category] += tokens
        return True

    def get_utilization(self, category: ContextCategory) -> float:
        """
        获取类别的使用率

        Args:
            category: Context 类别

        Returns:
            使用率（0.0 - 1.0+）
        """
        budget = self.budgets[category]
        usage = self.usage[category]
        return usage / budget if budget > 0 else 0.0

    def check_threshold(self, category: ContextCategory) -> bool:
        """
        检查是否接近预算上限

        Args:
            category: Context 类别

        Returns:
            是否需要优化
        """
        utilization = self.get_utilization(category)
        return utilization >= self.OPTIMIZATION_THRESHOLD

    def trigger_optimization(self, category: ContextCategory, required: int, budget: int) -> None:
        """
        触发优化策略

        Args:
            category: 超标的类别
            required: 需要的 tokens
            budget: 预算上限
        """
        if not self.optimization_triggered[category]:
            print(f"[WARNING]  Token 预算警告: {category.value}")
            print(f"   需要: {required} tokens")
            print(f"   预算: {budget} tokens")
            print(f"   超出: {required - budget} tokens ({(required/budget - 1)*100:.1f}%)")

            # 根据类别应用不同的优化策略
            if category == ContextCategory.QUERY_RESULTS:
                print("   → 建议: 使用 Observation Masking 屏蔽大型结果")
            elif category == ContextCategory.MESSAGE_HISTORY:
                print("   → 建议: 压缩对话历史或启动新会话")
            elif category == ContextCategory.TOOL_DEFINITIONS:
                print("   → 建议: 减少工具数量或使用工具分组")

            self.optimization_triggered[category] = True

    def get_statistics(self) -> Dict[str, Any]:
        """获取预算统计信息"""
        stats = {}

        for category in ContextCategory:
            budget = self.budgets[category]
            usage = self.usage[category]
            utilization = self.get_utilization(category)

            stats[category.value] = {
                "budget": budget,
                "usage": usage,
                "utilization": f"{utilization * 100:.1f}%",
                "remaining": budget - usage,
                "needs_optimization": utilization >= self.OPTIMIZATION_THRESHOLD
            }

        # 总计
        total_budget = sum(self.budgets.values())
        total_usage = sum(self.usage.values())

        stats["total"] = {
            "budget": total_budget,
            "usage": total_usage,
            "utilization": f"{(total_usage / total_budget) * 100:.1f}%",
            "remaining": total_budget - total_usage
        }

        return stats

    def reset_category(self, category: ContextCategory) -> None:
        """重置类别的使用统计"""
        self.usage[category] = 0
        self.optimization_triggered[category] = False

    def reset_all(self) -> None:
        """重置所有统计"""
        self.usage = {cat: 0 for cat in ContextCategory}
        self.optimization_triggered = {cat: False for cat in ContextCategory}


class QueryResultOptimizer:
    """
    查询结果优化器

    根据 Token 预算自动压缩查询结果
    """

    def __init__(self, token_budget: TokenBudget):
        """
        初始化优化器

        Args:
            token_budget: Token 预算管理器
        """
        self.budget = token_budget

    def optimize_result(self, result: Any, category: ContextCategory = ContextCategory.QUERY_RESULTS) -> Any:
        """
        根据预算优化结果

        Args:
            result: 原始结果
            category: 结果类别

        Returns:
            优化后的结果
        """
        # 估算 token 数量
        estimated_tokens = self._estimate_tokens(result)

        # 检查预算
        if not self.budget.allocate(category, estimated_tokens):
            # 超出预算，应用压缩
            return self._compress_result(result)

        # 在预算内，直接返回
        return result

    def _estimate_tokens(self, obj: Any) -> int:
        """估算对象的 token 数量"""
        import json
        json_str = json.dumps(obj, ensure_ascii=False, default=str)
        # 简化估算：4个字符 ≈ 1个 token
        return len(json_str) // 4

    def _compress_result(self, result: Any) -> Any:
        """压缩结果"""
        if isinstance(result, list):
            # 列表：仅返回前3个 + 总数
            return {
                "compressed": True,
                "total": len(result),
                "sample": result[:3],
                "message": f"结果已压缩（显示前3个，共{len(result)}个）"
            }
        elif isinstance(result, dict):
            # 字典：仅返回关键字段
            key_fields = ['name', 'module', 'signature', 'type']
            compressed = {k: v for k, v in result.items() if k in key_fields}
            compressed['_compressed'] = True
            compressed['_full_keys'] = list(result.keys())
            return compressed
        else:
            return result


# 全局单例
_global_token_budget = None


def get_token_budget() -> TokenBudget:
    """获取全局 Token 预算管理器"""
    global _global_token_budget
    if _global_token_budget is None:
        _global_token_budget = TokenBudget()
    return _global_token_budget


def reset_token_budget() -> None:
    """重置全局预算"""
    global _global_token_budget
    _global_token_budget = None
