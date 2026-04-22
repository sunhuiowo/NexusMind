"""
CodeAgent - Claude Code-like agent with tool execution capability.

基于 Anthropic Agent 工作流设计优化：
1. Sprint 概念 - 每步执行后评估是否完成
2. Evaluator 模式 - 执行后评估结果质量
3. 上下文重置 - 长对话时压缩历史
4. 硬性阈值 - 工具失败尝试替代方案
"""

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from tools.mcp_tools import search_memory, get_recent, get_stats
from tools.exec_tools import bash, file_read, file_write, glob_search, web_read, pdf_read

logger = logging.getLogger(__name__)


class EventType(Enum):
    CONTENT = "content"
    THINKING = "thinking"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    DONE = "done"
    ERROR = "error"
    EVALUATION = "evaluation"  # Evaluator 评估结果


@dataclass
class ToolCall:
    id: str
    tool: str
    params: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None
    status: str = "pending"  # pending | running | done | error


@dataclass
class Message:
    role: str  # user | assistant | system
    content: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


class CodeAgent:
    """
    CodeAgent - 基于 Anthropic 工作流优化的 Agent

    核心改进:
    1. Evaluator 模式 - 每次工具执行后评估结果质量
    2. Sprint 概念 - 明确的完成定义，失败后修复
    3. 上下文重置 - 长对话时压缩历史
    4. 替代方案尝试 - 工具失败时自动尝试其他方法
    """

    # 危险命令黑名单
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+/(?:\*)?",
        r"rm\s+-rf\s+/System",
        r":\(\)\{:|:&\};:",
        r"dd\s+if=.*of=/dev/sd",
        r"mv\s+/\s+",
    ]

    # JSON 提取正则
    JSON_PATTERN = r'\{(?:[^{}]|\{[^{}]*\})*\}'

    def __init__(self, user_id: str, session_id: str):
        self.user_id = user_id
        self.session_id = session_id
        self.conversation_history: List[Message] = []

        # 工具注册表
        self.tools: Dict[str, Any] = {
            "search_memory": search_memory,
            "get_recent": get_recent,
            "get_stats": get_stats,
            "bash": bash,
            "file_read": file_read,
            "file_write": file_write,
            "glob": glob_search,
            "web_read": web_read,
            "pdf_read": pdf_read,
        }

        # 工作目录
        self.work_dir = Path(f"/tmp/nexusmind/{user_id}/{session_id}")
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Agent 配置
        self.max_iterations = 10
        self.bash_timeout = 30
        self.context_limit = 10  # 超过此数量则压缩上下文

    # ── 主入口 ────────────────────────────────────────────────────────────────

    async def query(
        self,
        prompt: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Agent 主入口 - 采用 Evaluator 模式的循环

        Flow:
        1. LLM 决策 (Planner)
        2. 执行工具 (Generator)
        3. 评估结果 (Evaluator)
        4. 判断是否继续 / 修复
        """
        history_text = self._build_history_text(conversation_history or [])

        yield {"type": EventType.THINKING.value, "data": {"text": "正在分析你的请求..."}}

        tool_results = []
        iteration = 0

        # 上下文检查 - 必要时压缩
        if conversation_history and len(conversation_history) > self.context_limit:
            history_text = await self._compress_context(conversation_history)

        while iteration < self.max_iterations:
            # 1. Planner: LLM 决定下一步
            decision = await self._llm_decide(prompt, tool_results, history_text)

            if decision.get("reasoning"):
                yield {"type": EventType.REASONING.value, "data": {"text": decision["reasoning"]}}

            action = decision.get("action", "response")

            # 2. 判断行动
            if action == "done":
                break

            if action == "response":
                response_text = decision.get("text", "我明白了。")
                for chunk in self._chunk_text(response_text):
                    yield {"type": EventType.CONTENT.value, "data": {"text": chunk}}
                yield {"type": EventType.DONE.value, "data": {"message": "完成"}}
                return

            if action == "tool_call":
                tool_name = decision.get("tool", "")
                params = decision.get("params", {})

                if not tool_name or tool_name not in self.tools:
                    yield {
                        "type": EventType.TOOL_ERROR.value,
                        "data": {"tool": tool_name, "error": f"未知工具: {tool_name}"}
                    }
                    # Evaluator: 评估失败，尝试替代方案
                    alt_decision = await self._llm_alternative(prompt, tool_results, tool_name)
                    if alt_decision and alt_decision.get("tool"):
                        tool_name = alt_decision["tool"]
                        params = alt_decision.get("params", {})
                        yield {"type": EventType.REASONING.value, "data": {"text": f"尝试替代方案: {tool_name}"}}
                    else:
                        iteration += 1
                        continue

                # 检查危险命令
                if tool_name == "bash":
                    danger = self._check_danger(params.get("command", ""))
                    if danger:
                        yield {"type": EventType.TOOL_ERROR.value, "data": {"tool": tool_name, "error": f"危险命令被拦截"}}
                        # Evaluator: 硬性阈值 - 危险命令失败，尝试替代
                        alt_decision = await self._llm_alternative(prompt, tool_results, "dangerous_bash")
                        if alt_decision and alt_decision.get("tool"):
                            tool_name = alt_decision["tool"]
                            params = alt_decision.get("params", {})
                            yield {"type": EventType.REASONING.value, "data": {"text": f"改用安全方案: {tool_name}"}}
                        else:
                            iteration += 1
                            continue

                # Generator: 执行工具
                tool_id = str(uuid.uuid4())
                yield {"type": EventType.TOOL_CALL.value, "data": {"id": tool_id, "tool": tool_name, "params": params}}

                try:
                    result = await self._execute_tool(tool_name, params)
                    tool_results.append({"tool": tool_name, "result": result, "params": params})

                    result_preview = str(result)[:500] if len(str(result)) > 500 else str(result)
                    yield {"type": EventType.TOOL_RESULT.value, "data": {"id": tool_id, "tool": tool_name, "result": result_preview}}

                    # 3. Evaluator: 评估结果质量
                    evaluation = await self._evaluate_result(prompt, tool_name, params, result, tool_results)
                    yield {"type": EventType.EVALUATION.value, "data": {"text": evaluation["reasoning"]}}

                    # 如果评估认为失败，尝试修复
                    if not evaluation.get("success", True):
                        yield {"type": EventType.REASONING.value, "data": {"text": "评估不通过，尝试修复..."}}
                        repair_decision = await self._llm_repair(prompt, tool_results, evaluation)
                        if repair_decision and repair_decision.get("tool"):
                            # 继续循环，尝试修复
                            iteration += 1
                            continue

                except Exception as e:
                    yield {"type": EventType.TOOL_ERROR.value, "data": {"id": tool_id, "tool": tool_name, "error": str(e)}}
                    # Evaluator: 异常时尝试替代
                    alt_decision = await self._llm_alternative(prompt, tool_results, tool_name)
                    if alt_decision and alt_decision.get("tool"):
                        tool_name = alt_decision["tool"]
                        params = alt_decision.get("params", {})
                        yield {"type": EventType.REASONING.value, "data": {"text": f"工具异常，尝试替代: {tool_name}"}}
                        # 继续循环
                        iteration += 1
                        continue

            iteration += 1

            # 4. 检查是否应该继续
            should_continue = await self._should_continue(prompt, tool_results, iteration)
            if not should_continue:
                break

            if iteration >= self.max_iterations:
                yield {"type": EventType.THINKING.value, "data": {"text": "已达最大迭代次数"}}
                break

        # 5. 生成最终响应
        yield {"type": EventType.THINKING.value, "data": {"text": "正在生成响应..."}}
        response = await self._generate_response(prompt, tool_results, history_text)
        for chunk in self._chunk_text(response):
            yield {"type": EventType.CONTENT.value, "data": {"text": chunk}}
        yield {"type": EventType.DONE.value, "data": {"message": "完成"}}

    # ── Planner: 决策 ─────────────────────────────────────────────────────────

    async def _llm_decide(
        self,
        prompt: str,
        tool_results: List[Dict[str, Any]],
        history_text: str,
    ) -> Dict[str, Any]:
        """LLM 决定下一步行动 (Planner)"""
        from tools.llm import get_llm
        llm = get_llm()

        tool_descriptions = "\n".join(f"- {name}" for name in self.tools.keys())

        results_summary = ""
        if tool_results:
            lines = []
            for r in tool_results[-3:]:
                tool_name = r.get('tool', 'unknown')
                result = r.get('result', {})
                if isinstance(result, dict):
                    status = "成功" if result.get('success') else "失败"
                    content = str(result.get('content', result.get('stdout', '')))[:200]
                    lines.append(f"- [{tool_name}] {status}: {content}...")
                else:
                    lines.append(f"- [{tool_name}]: {str(result)[:200]}...")
            results_summary = "\n最近结果:\n" + "\n".join(lines)

        system_prompt = (
            "你是一个 Agent Planner。你的任务是根据用户请求和执行历史，决定下一步行动。\n\n"
            f"可用工具:\n{tool_descriptions}\n\n"
            "决策规则:\n"
            "1. 如果用户只是问候或简单问题，返回 action: response\n"
            "2. 如果需要获取信息或执行操作，返回 action: tool_call\n"
            "3. 如果任务已完成，返回 action: done\n\n"
            "重要:\n"
            "- 每次只决定一个工具\n"
            "- 工具参数要具体，url 参数必须是完整 URL\n"
            "- PDF 链接用 pdf_read，普通网页用 web_read\n"
            "- 如果需要搜索知识库，用 search_memory"
        )

        json_example = '{"action": "tool_call" | "response" | "done", "tool": "工具名", "params": {...}, "reasoning": "中文理由", "text": "直接回复（仅response时）"}'
        user_prompt = f"""用户请求: {prompt}
{history_text}
{results_summary}

返回 JSON（只返回 JSON，不要其他内容）:
{json_example}"""

        try:
            response = llm.complete(prompt=user_prompt, system=system_prompt, max_tokens=600, temperature=0.2)
            if response:
                try:
                    decision = json.loads(response)
                    if "action" in decision:
                        return decision
                except json.JSONDecodeError:
                    pass
                # 尝试提取 JSON
                match = re.search(self.JSON_PATTERN, response, re.DOTALL)
                if match:
                    decision = json.loads(match.group(0))
                    if "action" in decision:
                        return decision
        except Exception as e:
            logger.error(f"[CodeAgent] Planner 决策失败: {e}")

        return {"action": "response", "reasoning": "决策失败，使用默认回复", "text": "抱歉，我遇到了一些问题。能否重新描述一下你的请求？"}

    # ── Evaluator: 评估 ─────────────────────────────────────────────────────────

    async def _evaluate_result(
        self,
        prompt: str,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
        tool_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """评估工具执行结果 (Evaluator)"""
        from tools.llm import get_llm
        llm = get_llm()

        # 判断结果是否成功
        success = True
        if isinstance(result, dict):
            success = result.get('success', False) if 'success' in result else True

        result_str = str(result)[:500]

        system_prompt = (
            "你是一个 Evaluator。评估工具执行结果是否满足用户需求。\n\n"
            "评估标准:\n"
            "- 工具是否成功执行\n"
            "- 结果是否与用户请求相关\n"
            "- 结果是否完整\n\n"
            "返回 JSON:\n"
            '{"success": true/false, "reasoning": "中文评估理由"}\n'
            "只返回 JSON。"
        )

        user_prompt = f"""用户请求: {prompt}
工具: {tool_name}
参数: {params}
结果: {result_str}

评估结果:"""

        try:
            response = llm.complete(prompt=user_prompt, system=system_prompt, max_tokens=200, temperature=0.1)
            if response:
                try:
                    eval_result = json.loads(response)
                    eval_result["success"] = eval_result.get("success", True) and success
                    return eval_result
                except json.JSONDecodeError:
                    pass
        except Exception as e:
            logger.error(f"[CodeAgent] Evaluator 评估失败: {e}")

        return {"success": success, "reasoning": "评估完成"}

    async def _llm_alternative(
        self,
        prompt: str,
        tool_results: List[Dict[str, Any]],
        failed_tool: str,
    ) -> Optional[Dict[str, Any]]:
        """当工具失败时，LLM 提供替代方案"""
        from tools.llm import get_llm
        llm = get_llm()

        tool_descriptions = "\n".join(f"- {name}" for name in self.tools.keys())

        system_prompt = (
            "当工具执行失败时，提供替代工具。\n\n"
            f"可用工具:\n{tool_descriptions}\n\n"
            "返回 JSON:\n"
            '{"tool": "替代工具名", "params": {参数}, "reasoning": "为什么这个替代方案可行"}\n'
            "如果没有合适的替代方案，返回空对象 {{}}。只返回 JSON。"
        )

        user_prompt = f"""用户请求: {prompt}
失败工具: {failed_tool}

替代方案:"""

        try:
            response = llm.complete(prompt=user_prompt, system=system_prompt, max_tokens=300, temperature=0.2)
            if response:
                try:
                    return json.loads(response)
                except json.JSONDecodeError:
                    pass
                match = re.search(self.JSON_PATTERN, response)
                if match:
                    return json.loads(match.group(0))
        except Exception as e:
            logger.error(f"[CodeAgent] 替代方案生成失败: {e}")

        return None

    async def _llm_repair(
        self,
        prompt: str,
        tool_results: List[Dict[str, Any]],
        evaluation: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """根据评估失败原因，LLM 生成修复方案"""
        from tools.llm import get_llm
        llm = get_llm()

        tool_descriptions = "\n".join(f"- {name}" for name in self.tools.keys())

        system_prompt = (
            "根据评估失败的原因，生成修复方案。\n\n"
            f"可用工具:\n{tool_descriptions}\n\n"
            "返回 JSON:\n"
            '{"tool": "工具名", "params": {参数}, "reasoning": "修复策略"}\n'
            "如果无法修复，返回空对象 {{}}。只返回 JSON。"
        )

        user_prompt = f"""用户请求: {prompt}
评估结果: {evaluation}
最近执行: {str(tool_results[-2:]) if tool_results else "无"}

修复方案:"""

        try:
            response = llm.complete(prompt=user_prompt, system=system_prompt, max_tokens=300, temperature=0.2)
            if response:
                try:
                    return json.loads(response)
                except json.JSONDecodeError:
                    pass
                match = re.search(self.JSON_PATTERN, response)
                if match:
                    return json.loads(match.group(0))
        except Exception as e:
            logger.error(f"[CodeAgent] 修复方案生成失败: {e}")

        return None

    async def _should_continue(
        self,
        prompt: str,
        tool_results: List[Dict[str, Any]],
        iteration: int,
    ) -> bool:
        """判断是否继续迭代"""
        if iteration >= self.max_iterations - 1:
            return False

        if not tool_results:
            return True

        from tools.llm import get_llm
        llm = get_llm()

        results_lines = []
        for r in tool_results[-3:]:
            tool_name = r.get('tool', 'unknown')
            result = r.get('result', {})
            status = "成功" if (isinstance(result, dict) and result.get('success', True)) else "失败"
            results_lines.append(f"- [{tool_name}] {status}")

        system_prompt = "判断任务是否已完成。只返回 yes 或 no。"
        user_prompt = f"""用户请求: {prompt}
结果:
{chr(10).join(results_lines)}

是否需要继续？"""

        try:
            response = llm.complete(prompt=user_prompt, system=system_prompt, max_tokens=10, temperature=0.0)
            if response and "yes" in response.lower():
                return True
        except Exception as e:
            logger.error(f"[CodeAgent] _should_continue 失败: {e}")

        return False

    async def _compress_context(self, history: List[Dict[str, str]]) -> str:
        """压缩上下文 (Context Reset)"""
        from tools.llm import get_llm
        llm = get_llm()

        # 提取关键信息
        key_info = []
        for h in history[-10:]:
            role = "用户" if h.get('role') == 'user' else "助手"
            content = h.get('content', '')[:100]
            key_info.append(f"{role}: {content}")

        system_prompt = "你是一个上下文压缩器。将对话历史压缩为关键信息摘要，保留重要上下文。"
        user_prompt = f"""压缩以下对话历史，保留关键信息:

{chr(10).join(key_info)}

摘要:"""

        try:
            summary = llm.complete(prompt=user_prompt, system=system_prompt, max_tokens=300, temperature=0.3)
            if summary:
                return f"[上下文已压缩]\n{summary}"
        except Exception as e:
            logger.error(f"[CodeAgent] 上下文压缩失败: {e}")

        return ""

    # ── 工具执行 ───────────────────────────────────────────────────────────────

    async def _execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """执行单个工具 (Generator)"""
        if tool_name not in self.tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        tool_func = self.tools[tool_name]

        if tool_name == "bash":
            return await asyncio.get_event_loop().run_in_executor(
                None, lambda: bash(params.get("command", ""), params.get("timeout", self.bash_timeout), str(self.work_dir))
            )

        if tool_name == "file_write":
            path = params.get("path", "")
            if not Path(path).is_absolute():
                path = str(self.work_dir / path)
            return file_write(path=path, content=params.get("content", ""))

        if tool_name == "file_read":
            path = params.get("path", "")
            if not Path(path).is_absolute():
                path = str(self.work_dir / path)
            return file_read(path=path, base_dir=str(self.work_dir))

        if tool_name == "glob":
            return glob_search(pattern=params.get("pattern", "*"), base_dir=str(self.work_dir))

        if tool_name in ("search_memory", "get_recent", "get_stats"):
            return await asyncio.get_event_loop().run_in_executor(
                None, lambda: tool_func(**params, user_id=self.user_id)
            )

        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: tool_func(**params)
        )

    # ── 响应生成 ───────────────────────────────────────────────────────────────

    async def _generate_response(
        self,
        prompt: str,
        tool_results: List[Dict[str, Any]],
        history_text: str,
    ) -> str:
        """基于工具结果生成最终响应"""
        if not tool_results:
            return "没有找到相关信息"

        context_parts = []
        for r in tool_results:
            tool_name = r.get('tool', 'unknown')
            result = r.get('result', {})
            if isinstance(result, dict):
                if result.get('success') and result.get('content'):
                    context_parts.append(f"[{tool_name}] {result.get('content', '')[:5000]}")
                elif result.get('error'):
                    context_parts.append(f"[{tool_name}] 错误: {result['error']}")
                elif result.get('files'):
                    context_parts.append(f"[{tool_name}] 文件: {', '.join(result.get('files', [])[:20])}")
                elif result.get('stdout'):
                    context_parts.append(f"[{tool_name}] 输出:\n{result.get('stdout', '')[:2000]}")
                else:
                    context_parts.append(f"[{tool_name}]: {str(result)[:500]}")
            else:
                context_parts.append(f"[{tool_name}]: {str(result)[:500]}")

        context = "\n\n".join(context_parts)

        from tools.llm import get_llm
        llm = get_llm()

        system_prompt = "你是一个专业的 AI 助手，根据工具执行结果回答用户问题。\n用简洁专业的语言回复，突出重点。"

        user_prompt = f"""用户请求: {prompt}
{history_text}

工具结果:
{context}

回复:"""

        try:
            response = llm.complete(prompt=user_prompt, system=system_prompt, max_tokens=1500, temperature=0.3)
            if response:
                return response
        except Exception as e:
            logger.error(f"[CodeAgent] 生成响应失败: {e}")

        return f"结果:\n{context[:2000]}"

    # ── 辅助方法 ───────────────────────────────────────────────────────────────

    def _check_danger(self, command: str) -> Optional[str]:
        """检查危险命令"""
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                return pattern
        return None

    def _extract_url(self, prompt: str) -> Optional[str]:
        match = re.search(r"https?://[^\s<>\"'\)\]]+", prompt)
        if match:
            return re.sub(r"[^\w:/.-]$", "", match.group(0))
        return None

    def _build_history_text(self, history: List[Dict[str, str]]) -> str:
        if not history:
            return ""
        return "\n".join([
            f"{'用户' if h.get('role') == 'user' else '助手'}: {h.get('content', '')[:200]}"
            for h in history[-5:]
        ])

    def _chunk_text(self, text: str, chunk_size: int = 20) -> List[str]:
        result = []
        current = ""
        for char in text:
            current += char
            if len(current) >= chunk_size and char in "。！？\n ":
                result.append(current)
                current = ""
        if current:
            result.append(current)
        return result if result else [text]


# ── 全局 Agent 管理 ────────────────────────────────────────────────────────────

_agents: Dict[str, 'CodeAgent'] = {}


def get_code_agent(user_id: str, session_id: str) -> 'CodeAgent':
    key = f"{user_id}:{session_id}"
    if key not in _agents:
        _agents[key] = CodeAgent(user_id, session_id)
    return _agents[key]
