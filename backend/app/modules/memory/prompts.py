"""记忆压缩 / 抽取提示词（精简版：只保留影响结果的约束）。"""

from __future__ import annotations

from typing import Any

MEMORY_COMPRESS_SYSTEM = """你是会话记忆压缩器。把窗口外的历史对话压缩成可复用的记忆。
要求：
- summary 保留关键实体（城市/日期/人数/预算/景点/车次）、已确认事实、未解决问题；
- 优先保留用户需求、关键决策和未完成事项，闲聊只保留结论；
- 不确定的信息放进 pending_facts，并在句末标注“（待确认）”，不要猜测或改写事实；
- confirmed_facts 只放稳定的用户确认信息；天气、余票、票价等实时信息只留在 summary；
- 若新对话明确推翻或替代了“已知事实”中的某条，把那条旧事实原文放进 removed_facts，不要同时保留新旧两条矛盾事实；
- 不要写寒暄和重复内容，summary 不超过 {max_chars} 字。
只输出结构化结果。"""

MEMORY_MERGE_SYSTEM = """你是记忆摘要合并器。把旧摘要和新摘要合并成一段不超过 {max_chars} 字的摘要。
保留双方的关键实体、已确认事实和未解决问题；不确定的信息保留“（待确认）”标记；
不要新增、推断或删除事实。只输出合并后的摘要正文。"""

MEMORY_EXTRACT_SYSTEM = """从对话中抽取值得跨会话记住的信息。只抽取用户明确表达或已稳定确认的内容：
- preference：长期偏好（口味、节奏、住宿、交通方式等）
- fact：稳定的个人事实（常住地、同行人、忌口等）
- rule：用户给出的硬性规则（预算上限、禁忌、必须满足的条件）
- task_result：已完成的旅行任务结论（已选目的地、已定行程等）
- workflow：可复用的操作流程或工具用法
- lesson：工具失败、信息缺失或踩坑教训
不要抽取一次性话题、寒暄、未确认的猜测、天气/余票等实时信息；
不要保存密码、身份证、银行卡等敏感信息。
每条一句话；importance 1-5；confidence 0-1。只输出结构化结果。"""


def build_compress_user(
    old_summary: str,
    transcript: str,
    facts: Any,
    task_state: Any,
) -> str:
    """摘要压缩的用户提示：旧摘要 + 待压缩对话 + 已知事实。"""
    return (
        f"已有摘要：\n{old_summary or '无'}\n\n"
        f"已知事实：{facts or '无'}\n"
        f"已知任务状态：{task_state or '无'}\n\n"
        f"待压缩对话：\n{transcript}"
    )


def build_merge_user(old_summary: str, new_summary: str, max_chars: int) -> str:
    """摘要合并的用户提示。"""
    return (
        f"旧摘要：\n{old_summary}\n\n"
        f"新摘要：\n{new_summary}\n\n"
        f"合并后不超过 {max_chars} 字。"
    )


def build_extract_user(query: str, reply: str, transcript: str) -> str:
    """长期记忆抽取的用户提示。"""
    return (
        f"用户本轮输入：{query}\n"
        f"助手本轮回复：{(reply or '无')[:800]}\n\n"
        f"最近对话：\n{transcript}"
    )


MEMORY_CONFLICT_SYSTEM = """你负责维护用户的长期记忆，判断新记忆是否推翻已有记忆。
规则：
- 只有当新记忆与某条已有记忆属于同一主题（同一个偏好、事实、规则或任务结论），
  且新记忆明确推翻、更新或替代旧记忆时，才把旧记忆判为被取代；
- 同一主题的补充信息（例如又多喜欢了一样东西）不算冲突，不要标记；
- 仅措辞不同、内容一致的不算冲突，不要标记；
- 只能从给定候选里选择，不要编造 id 或事实；无法确定时宁可保留，不要删除；
- 被取代的旧事实只从“已有会话事实”里选取原文。
只输出结构化结果。"""


def build_conflict_user(
    new_items: str,
    memory_candidates: str,
    facts: str,
) -> str:
    """冲突判定的用户提示：新记忆 + 已有长期记忆候选 + 会话事实。"""
    return (
        f"新抽取的记忆：\n{new_items or '无'}\n\n"
        f"已有长期记忆候选（id | 类别 | 内容）：\n{memory_candidates or '无'}\n\n"
        f"已有会话事实：\n{facts or '无'}"
    )
