"""分层记忆业务：滑动窗口、情景摘要压缩、跨会话长期记忆读写。

约束
----
- 消息原文仍以 LangGraph checkpointer 为准；摘要只是派生的提示词材料；
- 任何记忆读写失败都只记 warning，绝不阻断对话主流程；
- 长期记忆只存 Milvus ``user_memories``，会话摘要/事实/任务状态存 PostgreSQL。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.database import get_session_factory
from backend.app.core.logging import get_logger
from backend.app.integrations.llm import get_fast_llm
from backend.app.integrations.memory_milvus import (
    acount_memories,
    adelete_memory_ids,
    adelete_user_memories,
    ainsert_memories,
    aquery_memories,
    aquery_memory_by_hash,
    asearch_memories,
)
from backend.app.modules.memory.models import SessionMemory
from backend.app.modules.memory.prompts import (
    MEMORY_COMPRESS_SYSTEM,
    MEMORY_CONFLICT_SYSTEM,
    MEMORY_EXTRACT_SYSTEM,
    MEMORY_MERGE_SYSTEM,
    build_compress_user,
    build_conflict_user,
    build_extract_user,
    build_merge_user,
)
from backend.app.modules.memory.repository import SessionMemoryRepository
from backend.app.modules.memory.types import (
    MemoryCompression,
    MemoryConflict,
    MemoryExtraction,
    MemoryItem,
    MemoryKind,
)

logger = get_logger(__name__)

_REMEMBER_RE = re.compile(
    r"(记住|请记住|帮我记住|记一下|以后都|今后都|下次要|我的偏好|我更喜欢|我习惯)"
)
_TRANSCRIPT_MAX_CHARS = 12000
_ITEM_MAX_CHARS = 2000
_TASK_FIELDS = ("city", "days", "people", "budget", "dates", "notes")
_KIND_LABELS = {
    MemoryKind.preference.value: "偏好",
    MemoryKind.fact.value: "事实",
    MemoryKind.rule.value: "规则",
    MemoryKind.task_result.value: "任务结果",
    MemoryKind.workflow.value: "工作流",
    MemoryKind.lesson.value: "经验教训",
    MemoryKind.gap.value: "知识缺口",
}
# 只有语义记忆参与冲突消解；程序记忆（工作流/经验/知识缺口）保持追加语义
_CONFLICT_KINDS = {
    MemoryKind.preference,
    MemoryKind.fact,
    MemoryKind.rule,
    MemoryKind.task_result,
}
_CONFLICT_KIND_VALUES = {kind.value for kind in _CONFLICT_KINDS}

_background_tasks: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# 消息处理
# ---------------------------------------------------------------------------


def _message_text(message: Any) -> str:
    """把字符串或多模态内容块统一成文本。"""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _last_human_text(messages: Sequence[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _message_text(message)
    return ""


def _last_ai_text(messages: Sequence[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            text = _message_text(message)
            if text.strip():
                return text
    return ""


def window_messages(messages: Sequence[AnyMessage], rounds: int) -> List[AnyMessage]:
    """保留最近 N 轮（含用户消息与其后的助手/工具消息）完整原文。"""
    start = _window_start(messages, rounds)
    return list(messages[start:]) if start > 0 else list(messages)


def _window_start(messages: Sequence[AnyMessage], rounds: int) -> int:
    """窗口起点的绝对下标；窗口前的消息才进入摘要。"""
    if rounds <= 0 or not messages:
        return 0
    count = 0
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            count += 1
            if count >= rounds:
                return index
    return 0


def _render_messages(messages: Sequence[AnyMessage]) -> str:
    """把消息渲染成压缩/抽取用文本；从新到旧取，控制总长度。"""
    blocks: List[str] = []
    total = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            text = f"用户：{_message_text(message).strip()}"
        elif isinstance(message, AIMessage):
            text = _message_text(message).strip()
            if text:
                text = f"助手：{text}"
            elif getattr(message, "tool_calls", None):
                names = "、".join(
                    str(call.get("name") or "") for call in message.tool_calls
                )
                text = f"助手调用工具：{names}"
        elif isinstance(message, ToolMessage):
            name = getattr(message, "name", "") or "工具"
            text = f"工具结果（{name}）：{_message_text(message).strip()[:300]}"
        else:
            continue

        text = text.strip()
        if not text:
            continue
        if total + len(text) > _TRANSCRIPT_MAX_CHARS:
            break
        blocks.append(text)
        total += len(text)
    return "\n".join(reversed(blocks))


def _dedupe_text(items: Sequence[Any], limit: int = 20) -> List[str]:
    """去空白、去重并截断。"""
    seen: set[str] = set()
    result: List[str] = []
    for item in items:
        text = " ".join(str(item or "").split())
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _norm_fact(text: Any) -> str:
    """事实文本归一化：合并空白并去掉“待确认”标记，用于冲突匹配。"""
    value = " ".join(str(text or "").split())
    return value.replace("（待确认）", "").replace("(待确认)", "").strip()


def _merge_facts(
    existing: Any,
    confirmed: Sequence[str],
    pending: Sequence[str],
    removed: Sequence[str] = (),
) -> dict:
    """合并已确认/待确认事实；被推翻的旧事实先剔除，待确认项统一加标记。"""
    base = existing if isinstance(existing, dict) else {}
    removed_set = {_norm_fact(item) for item in removed if _norm_fact(item)}
    kept_confirmed = [
        item
        for item in list(base.get("confirmed") or [])
        if _norm_fact(item) not in removed_set
    ]
    kept_pending = [
        item
        for item in list(base.get("pending") or [])
        if _norm_fact(item) not in removed_set
    ]
    confirmed_items = _dedupe_text(kept_confirmed + list(confirmed))
    pending_items = [
        item if "待确认" in item else f"{item}（待确认）"
        for item in kept_pending + list(pending)
    ]
    return {
        "confirmed": confirmed_items,
        "pending": _dedupe_text(pending_items),
    }


def _merge_task_state(existing: Any, new_state: Any) -> dict:
    """合并任务状态，空值不覆盖已有值。"""
    merged = dict(existing) if isinstance(existing, dict) else {}
    if isinstance(new_state, dict):
        for key in _TASK_FIELDS:
            value = str(new_state.get(key) or "").strip()
            if value:
                merged[key] = value
    return merged


def _content_hash(user_id: str, kind: str, city: str, content: str) -> str:
    """长期记忆去重哈希。"""
    raw = f"{user_id}|{kind}|{city}|{content}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _scan_tool_signals(messages: Sequence[AnyMessage]) -> List[MemoryItem]:
    """扫描工具失败与知识库空结果，转成程序/知识缺口记忆。"""
    call_map: Dict[str, tuple[str, dict]] = {}
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in getattr(message, "tool_calls", None) or []:
            call_id = str(call.get("id") or "")
            if call_id:
                call_map[call_id] = (
                    str(call.get("name") or ""),
                    call.get("args") if isinstance(call.get("args"), dict) else {},
                )

    items: List[MemoryItem] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        content = _message_text(message).strip()
        name = getattr(message, "name", "") or call_map.get(
            str(message.tool_call_id), ("", {})
        )[0]
        if name == "search_knowledge" and "未检索到" in content:
            args = call_map.get(str(message.tool_call_id), ("", {}))[1]
            query = str(args.get("query") or "").strip()
            if query:
                items.append(
                    MemoryItem(
                        kind=MemoryKind.gap,
                        content=f"知识库未覆盖查询「{query}」，回答时不要编造细节",
                        importance=2,
                        confidence=0.8,
                    )
                )
        if "执行失败" in content or "当前不可用" in content:
            items.append(
                MemoryItem(
                    kind=MemoryKind.lesson,
                    content=f"工具 {name or '未知'} 失败：{content[:150]}",
                    importance=2,
                    confidence=0.8,
                )
            )
    return items


# ---------------------------------------------------------------------------
# 业务服务
# ---------------------------------------------------------------------------


class MemoryService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = SessionMemoryRepository(db)

    async def get_session_memory(
        self, session_id: str, user_id: str
    ) -> Optional[SessionMemory]:
        """读取会话情景记忆并校验归属。"""
        return await self.repo.get(session_id, user_id)

    async def list_memories(
        self,
        user_id: str,
        *,
        city: str = "",
        kind: str = "",
        limit: int = 100,
    ) -> List[dict]:
        """列出用户长期记忆（调试与管理 API 使用）。"""
        return await aquery_memories(
            user_id, city=city, kind=kind, limit=limit
        )

    async def delete_memory(self, memory_id: str, user_id: str) -> int:
        """删除单条长期记忆，按 user_id 限定归属。"""
        return await adelete_memory_ids([memory_id], user_id)

    async def clear_user(self, user_id: str) -> int:
        """清空一个用户的全部长期记忆。"""
        return await adelete_user_memories(user_id)

    async def build_context(self, user_id: str, city: str, query: str) -> str:
        """召回用户长期记忆并格式化成提示词区块。"""
        if (
            not settings.memory.enabled
            or not settings.memory.long_term_enabled
            or not user_id
            or not (query or "").strip()
        ):
            return ""
        try:
            # 新用户没有任何 confirmed 记忆时跳过 embedding，省一次外部调用
            if await acount_memories(user_id, city=city) <= 0:
                return ""
            rows = await asearch_memories(
                user_id,
                query,
                city=city,
                limit=settings.memory.long_term_top_k,
                min_importance=settings.memory.long_term_min_importance,
            )
        except Exception as exc:
            logger.warning("长期记忆召回失败，跳过注入", error=str(exc))
            return ""

        lines: List[str] = []
        used = 0
        for row in rows:
            content = " ".join(str(row.get("content") or "").split())
            if not content:
                continue
            kind = str(row.get("kind") or "")
            label = _KIND_LABELS.get(kind, kind or "记忆")
            line = f"- [{label}] {content}"
            if used + len(line) > settings.memory.context_max_chars:
                break
            lines.append(line)
            used += len(line)
        if not lines:
            return ""
        return "【用户长期记忆（跨会话）】\n" + "\n".join(lines)

    async def refresh_session_memory(
        self,
        session_id: str,
        user_id: str,
        messages: Sequence[AnyMessage],
        city: str = "",
    ) -> SessionMemory:
        """更新轮次；窗口外消息达到阈值时做滚动摘要压缩。"""
        row = await self.repo.get(session_id, user_id)
        if row is None:
            row = await self.repo.upsert(session_id, user_id, turn_count=1)
        else:
            row.turn_count = int(row.turn_count or 0) + 1
            await self.db.flush()

        messages = list(messages)
        summarized = min(int(row.summarized_messages or 0), len(messages))
        window_start = _window_start(messages, settings.memory.window_rounds)
        new_slice = messages[summarized:window_start]
        if (
            len(messages) < settings.memory.summary_trigger_messages
            or len(new_slice) < settings.memory.summary_min_new_messages
        ):
            return row

        result = await self._compress(
            old_summary=row.summary or "",
            messages=new_slice,
            facts=row.facts or {},
            task_state=row.task_state or {},
        )
        if result is None:
            return row

        summary = await self._merge_summary(row.summary or "", result.summary or "")
        facts = _merge_facts(
            row.facts,
            result.confirmed_facts if isinstance(result.confirmed_facts, list) else [],
            result.pending_facts if isinstance(result.pending_facts, list) else [],
            result.removed_facts if isinstance(result.removed_facts, list) else [],
        )
        task_payload = result.task_state
        if hasattr(task_payload, "model_dump"):
            task_payload = task_payload.model_dump()
        task_state = _merge_task_state(row.task_state, task_payload)
        row = await self.repo.upsert(
            session_id,
            user_id,
            summary=summary,
            facts=facts,
            task_state=task_state,
            summarized_messages=window_start,
            turn_count=row.turn_count,
        )
        logger.info(
            "会话记忆已压缩",
            session_id=session_id,
            summarized=window_start,
            summary_chars=len(summary),
        )
        return row

    async def _compress(
        self,
        *,
        old_summary: str,
        messages: Sequence[AnyMessage],
        facts: Any,
        task_state: Any,
    ) -> Optional[MemoryCompression]:
        """调用快模型压缩窗口外历史；失败返回 None。"""
        transcript = _render_messages(messages)
        if not transcript.strip():
            return None
        try:
            model = get_fast_llm().with_structured_output(MemoryCompression)
            async with asyncio.timeout(settings.memory.summary_timeout):
                result = await model.ainvoke(
                    [
                        SystemMessage(
                            content=MEMORY_COMPRESS_SYSTEM.format(
                                max_chars=max(400, settings.memory.summary_max_chars // 2)
                            )
                        ),
                        HumanMessage(
                            content=build_compress_user(
                                old_summary, transcript, facts, task_state
                            )
                        ),
                    ]
                )
        except Exception as exc:
            logger.warning("会话记忆压缩失败，保留旧摘要", error=str(exc))
            return None
        if isinstance(result, dict):
            try:
                return MemoryCompression(**result)
            except Exception:
                return None
        return result if isinstance(result, MemoryCompression) else None

    async def _merge_summary(self, old_summary: str, new_summary: str) -> str:
        """滚动拼接摘要；超长时用模型合并，失败才保留最新部分。"""
        new_summary = (new_summary or "").strip()
        if not new_summary:
            return old_summary
        if not old_summary:
            return new_summary[: settings.memory.summary_max_chars]

        merged = f"{old_summary}\n---\n{new_summary}"
        limit = settings.memory.summary_max_chars
        if len(merged) <= limit:
            return merged

        try:
            async with asyncio.timeout(settings.memory.summary_timeout):
                response = await get_fast_llm().ainvoke(
                    [
                        SystemMessage(
                            content=MEMORY_MERGE_SYSTEM.format(max_chars=limit)
                        ),
                        HumanMessage(
                            content=build_merge_user(old_summary, new_summary, limit)
                        ),
                    ]
                )
            text = _message_text(response).strip()
            if text:
                return text[:limit]
        except Exception as exc:
            logger.warning("摘要合并失败，保留最新部分", error=str(exc))
        return merged[-limit:]

    # ------------------------------------------------------------------
    # 写入侧冲突消解：新记忆推翻旧记忆时删除旧条目
    # ------------------------------------------------------------------

    async def _conflict_candidates(
        self, user_id: str, city: str, kinds: Sequence[str]
    ) -> List[dict]:
        """按类别读取已确认的现有记忆，作为冲突判定候选（不触发 embedding）。"""
        limit = max(1, int(settings.memory.conflict_candidates))
        # Milvus 的 query 在过滤后按任意顺序截断，先多取再按 created_at 排序
        query_limit = min(100, max(limit * 3, 30))
        rows: List[dict] = []
        seen: set[str] = set()
        for kind in kinds:
            try:
                items = await aquery_memories(
                    user_id, city=city, kind=kind, limit=query_limit
                )
            except Exception as exc:
                logger.warning("冲突候选读取失败", kind=kind, error=str(exc))
                continue
            for item in items:
                memory_id = str(item.get("id") or "")
                if not memory_id or memory_id in seen:
                    continue
                if str(item.get("status") or "") != "confirmed":
                    continue
                seen.add(memory_id)
                rows.append(item)
        rows.sort(key=lambda row: int(row.get("created_at") or 0), reverse=True)
        return rows[: limit * 2]

    async def _resolve_conflicts(
        self,
        items: Sequence[MemoryItem],
        user_id: str,
        city: str,
        session_id: str,
    ) -> Optional[MemoryConflict]:
        """用快模型判断新记忆是否推翻已有记忆；失败返回 None（按追加处理）。"""
        if not settings.memory.conflict_enabled:
            return None
        # 只有达到 confirmed 的新记忆才允许取代旧记忆
        semantic = [
            (
                item,
                item.kind.value if hasattr(item.kind, "value") else str(item.kind),
            )
            for item in items
            if float(item.confidence or 0.0) >= 0.7
        ]
        semantic = [
            (item, kind)
            for item, kind in semantic
            if kind in _CONFLICT_KIND_VALUES
        ]
        if not semantic:
            return None

        kinds = sorted({kind for _, kind in semantic})
        candidates = await self._conflict_candidates(user_id, city, kinds)
        confirmed_facts: List[str] = []
        if session_id:
            row = await self.repo.get(session_id, user_id)
            facts = (
                row.facts if row is not None and isinstance(row.facts, dict) else {}
            )
            confirmed_facts = [
                str(fact)
                for fact in (facts.get("confirmed") or [])
                if str(fact).strip()
            ]
        if not candidates and not confirmed_facts:
            return None

        lines: List[str] = []
        for item, kind in semantic:
            content = " ".join(str(item.content or "").split())[:200]
            lines.append(
                f"- [{_KIND_LABELS.get(kind, kind)}] {content}"
                f"（城市：{item.city or city or '不限'}）"
            )
        new_items_text = "\n".join(lines)
        memory_text = "\n".join(
            f"{row.get('id')} | "
            f"{_KIND_LABELS.get(str(row.get('kind') or ''), str(row.get('kind') or ''))}"
            f" | {str(row.get('content') or '')[:160]}"
            for row in candidates
        )
        facts_text = "\n".join(f"- {fact}" for fact in confirmed_facts)

        try:
            model = get_fast_llm().with_structured_output(MemoryConflict)
            async with asyncio.timeout(settings.memory.summary_timeout):
                result = await model.ainvoke(
                    [
                        SystemMessage(content=MEMORY_CONFLICT_SYSTEM),
                        HumanMessage(
                            content=build_conflict_user(
                                new_items_text, memory_text, facts_text
                            )
                        ),
                    ]
                )
        except Exception as exc:
            logger.warning("记忆冲突判定失败，按追加处理", error=str(exc))
            return None
        if isinstance(result, dict):
            try:
                result = MemoryConflict(**result)
            except Exception:
                return None
        if not isinstance(result, MemoryConflict):
            return None

        # 只接受候选里真实存在的 id / 事实，防止模型编造
        valid_ids = {str(row.get("id") or "") for row in candidates}
        superseded_ids: List[str] = []
        for memory_id in result.superseded_memory_ids:
            memory_id = str(memory_id)
            if memory_id in valid_ids and memory_id not in superseded_ids:
                superseded_ids.append(memory_id)
        original_facts = {_norm_fact(fact): str(fact) for fact in confirmed_facts}
        superseded_facts: List[str] = []
        for fact in result.superseded_facts:
            original = original_facts.get(_norm_fact(fact))
            if original and original not in superseded_facts:
                superseded_facts.append(original)
        if not superseded_ids and not superseded_facts:
            return None
        return MemoryConflict(
            superseded_memory_ids=superseded_ids,
            superseded_facts=superseded_facts,
        )

    async def _apply_conflicts(
        self, conflict: Optional[MemoryConflict], user_id: str, session_id: str
    ) -> None:
        """新记忆写入成功后，删除被取代的旧记忆与旧事实。"""
        if conflict is None:
            return
        if conflict.superseded_memory_ids:
            try:
                deleted = await adelete_memory_ids(
                    conflict.superseded_memory_ids, user_id
                )
                if deleted:
                    logger.info(
                        "旧长期记忆已被新记忆取代",
                        user_id=user_id,
                        deleted=deleted,
                    )
            except Exception as exc:
                logger.warning("删除被取代的长期记忆失败", error=str(exc))
        if conflict.superseded_facts and session_id:
            await self._drop_session_facts(
                session_id, user_id, conflict.superseded_facts
            )

    async def _drop_session_facts(
        self, session_id: str, user_id: str, removed: Sequence[str]
    ) -> None:
        """从会话记忆里删除被新对话推翻的事实。"""
        drop = {_norm_fact(item) for item in removed if _norm_fact(item)}
        if not drop:
            return
        row = await self.repo.get(session_id, user_id)
        if row is None:
            return
        facts = row.facts if isinstance(row.facts, dict) else {}
        confirmed = [
            fact
            for fact in (facts.get("confirmed") or [])
            if _norm_fact(fact) not in drop
        ]
        pending = [
            fact
            for fact in (facts.get("pending") or [])
            if _norm_fact(fact) not in drop
        ]
        if len(confirmed) == len(facts.get("confirmed") or []) and len(
            pending
        ) == len(facts.get("pending") or []):
            return
        await self.repo.upsert(
            session_id,
            user_id,
            facts={"confirmed": confirmed, "pending": pending},
            turn_count=row.turn_count,
        )
        logger.info("会话事实已被新对话推翻", session_id=session_id, count=len(removed))

    async def remember_items(
        self,
        items: Sequence[MemoryItem],
        user_id: str,
        session_id: str = "",
        city: str = "",
    ) -> int:
        """把抽取结果写入 Milvus；按内容哈希去重，冲突时删除被取代的旧记忆。"""
        if (
            not settings.memory.enabled
            or not settings.memory.long_term_enabled
            or not user_id
            or not items
        ):
            return 0

        now = int(time.time())
        rows: List[dict] = []
        kept: List[MemoryItem] = []
        seen: set[str] = set()
        for item in items:
            if len(rows) >= 10:
                break
            content = " ".join(str(item.content or "").split())[:_ITEM_MAX_CHARS]
            if len(content) < 2:
                continue
            kind = item.kind.value if hasattr(item.kind, "value") else str(item.kind)
            item_city = (item.city or city or "").strip()
            status = "confirmed" if item.confidence >= 0.7 else "pending"
            digest = _content_hash(user_id, kind, item_city, content)
            if digest in seen:
                continue
            seen.add(digest)
            try:
                existing = await aquery_memory_by_hash(user_id, digest)
            except Exception as exc:
                logger.warning("长期记忆去重查询失败", error=str(exc))
                existing = []
            if existing:
                continue
            kept.append(item)
            rows.append(
                {
                    "id": uuid.uuid4().hex,
                    "user_id": user_id,
                    "kind": kind,
                    "city": item_city,
                    "content": content,
                    "text": f"{_KIND_LABELS.get(kind, kind)} {item_city} {content}",
                    "content_hash": digest,
                    "source_session_id": session_id or "",
                    "importance": int(item.importance or 2),
                    "confidence": float(item.confidence or 0.8),
                    "status": status,
                    "created_at": now,
                    "last_used_at": 0,
                }
            )

        if not rows:
            return 0
        # 写入前先判定冲突；写入成功后才删除旧条目，避免删除后写入失败丢记忆
        conflict = await self._resolve_conflicts(kept, user_id, city, session_id)
        try:
            count = await ainsert_memories(rows)
        except Exception as exc:
            logger.warning("长期记忆写入失败", error=str(exc))
            return 0
        await self._apply_conflicts(conflict, user_id, session_id)
        logger.info("长期记忆已写入", user_id=user_id, count=count)
        return count

    async def _extract(
        self, query: str, reply: str, transcript: str
    ) -> List[MemoryItem]:
        """调用快模型抽取长期记忆条目；失败返回空列表。"""
        if not (query or "").strip():
            return []
        try:
            model = get_fast_llm().with_structured_output(MemoryExtraction)
            async with asyncio.timeout(settings.memory.summary_timeout):
                result = await model.ainvoke(
                    [
                        SystemMessage(content=MEMORY_EXTRACT_SYSTEM),
                        HumanMessage(
                            content=build_extract_user(query, reply, transcript)
                        ),
                    ]
                )
        except Exception as exc:
            logger.warning("长期记忆抽取失败", error=str(exc))
            return []
        if isinstance(result, dict):
            try:
                result = MemoryExtraction(**result)
            except Exception:
                return []
        if not isinstance(result, MemoryExtraction):
            return []
        return [
            item
            for item in result.items
            if item.content.strip() and item.confidence >= 0.55
        ][:8]

    async def extract_and_persist(
        self,
        *,
        user_id: str,
        session_id: str,
        city: str,
        turn_count: int,
        messages: Sequence[AnyMessage],
        memory_facts: Any = None,
    ) -> int:
        """轮末异步入口：显式指令、定期批量、工具信号四类触发写入。"""
        if (
            not settings.memory.enabled
            or not settings.memory.long_term_enabled
            or not user_id
            or not session_id
        ):
            return 0

        messages = list(messages)
        query = _last_human_text(messages)
        reply = _last_ai_text(messages)
        items: List[MemoryItem] = []

        # 事实确认触发：把会话摘要确认过的事实升级为长期记忆
        facts = memory_facts if isinstance(memory_facts, dict) else {}
        confirmed_facts = facts.get("confirmed")
        for fact in confirmed_facts if isinstance(confirmed_facts, list) else []:
            items.append(
                MemoryItem(
                    kind=MemoryKind.fact,
                    content=str(fact),
                    city=city,
                    importance=3,
                    confidence=0.9,
                )
            )

        # 明确指令触发 + 定期批量触发
        explicit = bool(_REMEMBER_RE.search(query or ""))
        interval = max(1, int(settings.memory.extract_interval_rounds or 1))
        periodic = turn_count > 0 and turn_count % interval == 0
        if query and (explicit or periodic):
            transcript = _render_messages(window_messages(messages, 2))
            extracted = await self._extract(query, reply, transcript)
            if explicit:
                # 用户明确要求“记住”时提升为已确认，避免置信度偏低被过滤
                for item in extracted:
                    item.confidence = max(item.confidence, 0.9)
                    item.importance = max(item.importance, 3)
            items.extend(extracted)

        # 检索失败 / 工具失败回写
        signals = _scan_tool_signals(messages[-12:])
        if not settings.memory.writeback_knowledge_gap:
            signals = [item for item in signals if item.kind != MemoryKind.gap]
        items.extend(signals)

        if not items:
            return 0
        return await self.remember_items(
            items, user_id, session_id=session_id, city=city
        )


# ---------------------------------------------------------------------------
# 轮末异步写入
# ---------------------------------------------------------------------------


async def _run_background_save(
    *,
    user_id: str,
    session_id: str,
    city: str,
    turn_count: int,
    messages: List[AnyMessage],
    memory_facts: Any,
) -> None:
    """后台任务：独立数据库会话，写失败不影响已返回的回复。"""
    try:
        factory = get_session_factory()
        async with factory() as db:
            service = MemoryService(db)
            await service.extract_and_persist(
                user_id=user_id,
                session_id=session_id,
                city=city,
                turn_count=turn_count,
                messages=messages,
                memory_facts=memory_facts,
            )
            await db.commit()
    except Exception as exc:
        logger.warning("后台记忆写入失败", session_id=session_id, error=str(exc))


def schedule_memory_save(
    *,
    user_id: str,
    session_id: str,
    city: str,
    turn_count: int,
    messages: List[AnyMessage],
    memory_facts: Any = None,
) -> None:
    """把轮末记忆写入挂到后台任务，避免推迟 SSE done 事件。"""
    if (
        not settings.memory.enabled
        or not settings.memory.long_term_enabled
        or not user_id
        or not session_id
    ):
        return
    try:
        task = asyncio.create_task(
            _run_background_save(
                user_id=user_id,
                session_id=session_id,
                city=city,
                turn_count=turn_count,
                messages=messages,
                memory_facts=memory_facts,
            )
        )
    except RuntimeError as exc:
        logger.warning("无法创建记忆后台任务", error=str(exc))
        return
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
