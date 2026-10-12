"""
AI Provider 入口：根据配置自动选 RuleBased 还是 LLM。

行为：
- settings.llm_provider == "openai" 且 LLM_API_KEY 非空 → 走 LLMProvider（真 AI）
- 否则 → 走 RuleBasedAIProvider（假 AI，模板字符串）

这样不填 API key 也能跑（用模板），填了就自动升级到 LLM。
"""
import logging
from typing import Protocol

from app.domain.schemas import OntologyInstanceRead
from app.infrastructure.config import settings

logger = logging.getLogger(__name__)


class AIProvider(Protocol):
    """AI 能力标准接口, 所有实现都要遵守这套方法签名"""

    def generate_spec(self, feature: OntologyInstanceRead) -> dict:
        ...

    def generate_plan(self, spec: OntologyInstanceRead) -> dict:
        ...

    def generate_tasks(self, plan: OntologyInstanceRead) -> list[dict]:
        ...


class RuleBasedAIProvider:
    """确定性规则提供者（fallback）；保留供离线/无 key 时使用"""

    def generate_spec(self, feature: OntologyInstanceRead) -> dict:
        title = feature.title
        return {
            "title": f"Spec: {title}",
            "goal": f"围绕「{title}」形成可验收、可拆解、可追踪的软件需求。",
            "stories": [
                {
                    "title": "作为架构师，我希望看清本体关系",
                    "body": "系统需要展示 Feature、Spec、Plan、Task 之间的语义链路。",
                },
                {
                    "title": "作为开发者，我希望任务足够具体",
                    "body": "每个 Task 应该能对应到清晰的代码层或测试目标。",
                },
                {
                    "title": "作为运维人员，我希望发布动作可追踪",
                    "body": "CI/CD 和日志检索应以本体实例记录，方便复盘。",
                },
            ],
            "acceptance": [
                "Feature 下至少生成一个 Spec。",
                "Spec 下至少包含 User Story 和 Acceptance。",
                "Plan 可以继续拆解为 Data Model、Contract、ADR 和 Task。",
            ],
            "clarifications": [
                "v1 使用规则模拟 AI 输出，不接真实大模型。",
                "v1 使用 PostgreSQL 表存储图节点和边。",
            ],
        }

    def generate_plan(self, spec: OntologyInstanceRead) -> dict:
        return {
            "title": f"Plan: {spec.title.replace('Spec: ', '')}",
            "summary": "按照 DDD 分层组织实现:领域模型、应用用例、基础设施适配器、API/UI 展示。",
            "data_models": [
                "OntologyClass:定义软件工程概念类型。",
                "OntologyInstance:记录具体工程制品。",
                "OntologyRelation:表达实例之间的语义边。",
            ],
            "contracts": [
                "search instances:按 class、状态、关键词检索。",
                "get detail:读取实例详情和属性。",
                "save instance:创建或更新本体实例。",
                "get graph:读取一个根节点附近的拓扑图。",
            ],
            "adrs": [
                "ADR-001:MVP 使用 PostgreSQL 表表达图结构，避免过早引入 Neo4j。",
                "ADR-002:AI Provider 使用接口隔离，默认规则实现可替换。",
            ],
        }

    def generate_tasks(self, plan: OntologyInstanceRead) -> list[dict]:
        layers = [
            ("domain", "定义本体类、实例、关系类型和基础校验规则"),
            ("application", "实现 Spec、Plan、Task、Checklist 工作流"),
            ("infrastructure", "实现 PostgreSQL Repository 和 Mock 集成适配器"),
            ("api", "暴露 Agent 友好的 search/get/save/graph HTTP 接口"),
            ("frontend", "实现端到端交付看板、拓扑图和详情面板"),
            ("tests", "覆盖核心工作流和 Mock DevOps 闭环"),
        ]
        return [
            {
                "title": f"{layer}: {body}",
                "layer": layer,
                "definition_of_done": [
                    "代码路径清晰，初学者能在文档中找到对应说明。",
                    "和相关本体实例建立关系。",
                    "至少有一个可验证的测试或演示入口。",
                ],
            }
            for layer, body in layers
        ]


def _build_ai_provider() -> AIProvider:
    """工厂函数：根据 settings 决定具体实现"""
    if settings.llm_enabled:
        # 延迟 import：避免没装 httpx/owlready2 时也能跑（rule-based 模式）
        from app.infrastructure.llm_provider import LLMProvider

        try:
            provider = LLMProvider()
            logger.info("AI Provider: LLMProvider (model=%s)", settings.llm_model)
            return provider
        except Exception as e:
            logger.warning("LLM 初始化失败，降级为 RuleBasedAIProvider。原因: %s", e)
    logger.info("AI Provider: RuleBasedAIProvider (llm_enabled=%s)", settings.llm_enabled)
    return RuleBasedAIProvider()


# 全局单例
ai_provider: AIProvider = _build_ai_provider()