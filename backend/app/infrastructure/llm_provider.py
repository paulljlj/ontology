"""
LLM Provider：通过 OpenAI 兼容协议调用大模型。

支持：
- OpenAI 官方（设 LLM_BASE_URL 留空）
- DeepSeek、通义千问、月之暗面等（设对应的 base_url）
- 本地 Ollama（设 http://localhost:11434/v1）

调用流程：
1. build_prompt 拼系统提示（含本体 schema 约束）+ 用户输入
2. 调 /chat/completions，强制 json_object 输出
3. 解析返回 JSON
4. 推理机校验（callers 负责，本类只生成）
"""
import json
import logging
from typing import Any

import httpx

from app.domain import reasoner
from app.domain.schemas import OntologyInstanceRead
from app.infrastructure.config import settings

logger = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    """LLM 调用失败（网络/解析/校验错误）"""


class LLMProvider:
    def __init__(self):
        if not settings.llm_enabled:
            raise LLMProviderError(
                "LLM 未启用。请在 backend/.env 里设置 LLM_PROVIDER=openai 和 LLM_API_KEY=..."
            )
        base = settings.llm_base_url.strip() or "https://api.openai.com/v1"
        self._client = httpx.Client(
            base_url=base,
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            timeout=settings.llm_timeout,
        )
        self._model = settings.llm_model

    # ---------- 三个工作流入口 ----------
    def generate_spec(self, feature: OntologyInstanceRead) -> dict:
        """
        根据 Feature 生成 Spec 数据。

        返回 dict：{"title", "goal", "stories": [...], "acceptance": [...], "clarifications": [...]}
        """
        schema_desc = reasoner.describe_class_for_llm("Spec")
        user_msg = self._build_feature_prompt(feature, task="生成需求规格 Spec")

        system_prompt = f"""你是一名资深软件需求分析师。
请根据用户给出的 Feature，生成一个结构化的 Spec JSON。

{schema_desc}

【输出规则 - 非常重要】
1. 你的回复必须是【纯 JSON 文本】，不要任何解释、Markdown 代码块、<think> 标签
2. 必须是合法 JSON，可被 Python json.loads 解析
3. stories 至少 2 条，每条含 title 和 body
4. acceptance 至少 2 条，描述可验证的验收标准
5. clarifications 至少 1 条，列出仍需澄清的开放问题
6. 不要输出 Spec schema 之外的字段
7. 标题、目标、故事必须紧密围绕 Feature 的实际意图，不要泛泛而谈

【示例输出格式】
{{"title": "...", "goal": "...", "stories": [{{"title":"...","body":"..."}}], "acceptance": ["..."], "clarifications": ["..."]}}
"""

        raw = self._chat_json(system_prompt, user_msg)
        return self._coerce_spec(raw, feature.title)

    def generate_plan(self, spec: OntologyInstanceRead) -> dict:
        """
        根据 Spec 生成 Plan 数据。
        返回 dict：{"title", "summary", "data_models": [...], "contracts": [...], "adrs": [...]}
        """
        schema_desc = reasoner.describe_class_for_llm("Plan")
        spec_props = spec.properties or {}
        user_msg = f"""Spec 标题: {spec.title}
Spec 目标 (goal): {spec_props.get("goal", "")}
Spec 全部属性: {json.dumps(spec_props, ensure_ascii=False)}

请基于此 Spec 生成 Plan。"""

        system_prompt = f"""你是一名软件架构师。
请根据用户给出的 Spec，生成一个结构化的 Plan JSON。

{schema_desc}

【输出规则 - 非常重要】
1. 你的回复必须是【纯 JSON 文本】，不要任何解释、Markdown 代码块、<think> 标签
2. 必须是合法 JSON
3. data_models 至少 1 条，每条含 title 和 body
4. contracts 至少 1 条，描述对外接口（API endpoint / 事件 / 协议）
5. adrs 至少 1 条，含 title、decision、status（status 用 "accepted"）
6. 不要输出 Plan schema 之外的字段
7. Plan 必须实际回应 Spec 中的 stories 和 acceptance，不要泛泛而谈
"""

        raw = self._chat_json(system_prompt, user_msg)
        return self._coerce_plan(raw, spec.title)

    def generate_tasks(self, plan: OntologyInstanceRead) -> list[dict]:
        """
        根据 Plan 生成 Task 列表。
        返回 list[dict]，每条含 title、layer、definition_of_done。
        """
        schema_desc = reasoner.describe_class_for_llm("Task")
        plan_props = plan.properties or {}
        user_msg = f"""Plan 标题: {plan.title}
Plan 概述 (summary): {plan_props.get("summary", "")}
Plan 全部属性: {json.dumps(plan_props, ensure_ascii=False)}

请基于此 Plan 拆解 Task。"""

        system_prompt = f"""你是一名技术负责人。
请根据用户给出的 Plan，拆解为可执行的 Task 列表。

{schema_desc}

【输出规则 - 非常重要】
1. 你的回复必须是【纯 JSON 数组文本】，不要任何解释、Markdown 代码块、<think> 标签
2. 输出必须是 JSON 数组（list），不要包在对象里
3. 每条 task 必须含 title、layer、definition_of_done
4. layer 必须是: domain / application / api / infrastructure / test 之一
5. 至少 3 条 task，覆盖 Plan 中的主要设计点
6. definition_of_done 是数组，每条是可验证的完成标准
7. 不要输出 Task schema 之外的字段
8. Task 标题要具体（不要"实现功能"，要"实现 User ORM 模型"）
"""

        raw = self._chat_json(system_prompt, user_msg)
        if not isinstance(raw, list):
            raise LLMProviderError(f"LLM 返回的不是列表: {type(raw).__name__}")
        return raw

    # ---------- 内部工具 ----------
    def _build_feature_prompt(self, feature: OntologyInstanceRead, task: str) -> str:
        props = feature.properties or {}
        return f"""任务: {task}

Feature 标题: {feature.title}
Feature 状态: {feature.status}
Feature 全部属性:
{json.dumps(props, ensure_ascii=False, indent=2)}

请基于以上 Feature 上下文，生成结构化内容。"""

    def _chat_json(self, system_prompt: str, user_msg: str) -> Any:
        """调 LLM 并解析 JSON 输出。兼容多种网关：自动剥 <think> 标签、提取 JSON 块"""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.4,
        }
        try:
            resp = self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.exception("LLM HTTP 调用失败")
            raise LLMProviderError(f"LLM HTTP 调用失败: {e}") from e

        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            logger.exception("LLM 响应结构异常")
            raise LLMProviderError(f"LLM 响应结构异常: {e}，原文: {resp.text[:300]}") from e

        # 1) 尝试直接解析
        cleaned = self._strip_think_tags(content).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 2) 尝试从 markdown ```json ... ``` 块里提取
        import re
        match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # 3) 尝试找第一个 { 或 [ 开始的位置
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = cleaned.find(start_char)
            if start == -1:
                continue
            # 配对找最近的结束符
            depth = 0
            for i in range(start, len(cleaned)):
                if cleaned[i] == start_char:
                    depth += 1
                elif cleaned[i] == end_char:
                    depth -= 1
                    if depth == 0:
                        candidate = cleaned[start : i + 1]
                        try:
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break
        raise LLMProviderError(
            f"LLM 返回无法解析为 JSON。原文: {content[:300]}"
        )

    @staticmethod
    def _strip_think_tags(content: str) -> str:
        """去掉 <think>...</think> / <thinking>...</thinking> 这种推理标签"""
        import re
        return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)

    def _coerce_spec(self, raw: dict, feature_title: str) -> dict:
        """保证 Spec 字段齐全，缺失则补默认"""
        if not isinstance(raw, dict):
            raise LLMProviderError("LLM 返回的 Spec 不是 dict")
        return {
            "title": raw.get("title") or f"Spec: {feature_title}",
            "goal": raw.get("goal") or "",
            "stories": raw.get("stories") or [],
            "acceptance": raw.get("acceptance") or [],
            "clarifications": raw.get("clarifications") or [],
        }

    def _coerce_plan(self, raw: dict, spec_title: str) -> dict:
        """保证 Plan 字段齐全"""
        if not isinstance(raw, dict):
            raise LLMProviderError("LLM 返回的 Plan 不是 dict")
        return {
            "title": raw.get("title") or f"Plan: {spec_title.replace('Spec: ', '')}",
            "summary": raw.get("summary") or "",
            "data_models": raw.get("data_models") or [],
            "contracts": raw.get("contracts") or [],
            "adrs": raw.get("adrs") or [],
        }