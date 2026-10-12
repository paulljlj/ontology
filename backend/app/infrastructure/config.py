from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://ontology:ontology@localhost:5432/ontology_ai"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # === 图数据库配置 ===
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "ontology"
    neo4j_database: str = "ontology"

    # === LLM 配置 ===
    # 默认走 rule-based；要接真 LLM 就填下面三个值
    llm_provider: str = "rule-based"  # 可选: "rule-based" | "openai"
    llm_api_key: str = ""
    llm_base_url: str = ""  # 留空走官方 API；填了就走代理（如 DeepSeek/通义/本地 Ollama）
    llm_model: str = "gpt-4o-mini"
    llm_timeout: int = 60  # 秒

    # === 飞书 (Lark) 集成 ===
    # 留空 = 走 mock 降级；填齐 = 调真实 API
    feishu_app_id: str = ""  # 飞书应用 App ID（来自 .env）
    feishu_app_secret: str = ""  # 飞书应用 App Secret（来自 .env，**不要提交到 git**）
    feishu_approval_code: str = "DE79D47F-CC81-4044-B7CC-F40CC8942751"  # 审批模板编码（飞书后台创建后得到）
    feishu_default_approver: str = "ou_727be3e59a667917446ccaa76f29e175"  # 默认审批人 open_id
    feishu_form_title_id: str = "widget16500094298477484625790733479"  # 审批表单"标题"控件 id
    feishu_form_content_id: str = "widget16500094292359699894458073106"  # 审批表单"内容"控件 id
    feishu_event_enabled: bool = True  # 是否启动 WebSocket 事件监听

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def llm_enabled(self) -> bool:
        """是否启用 LLM：provider=openai 且 key 非空"""
        return self.llm_provider == "openai" and bool(self.llm_api_key.strip())

    @property
    def feishu_enabled(self) -> bool:
        """是否启用真实飞书 API：app_id + app_secret 都非空"""
        return bool(self.feishu_app_id.strip() and self.feishu_app_secret.strip())


settings = Settings()