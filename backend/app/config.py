from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VendorLens AI API"
    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://vendorlens:vendorlens@localhost:5432/vendorlens"
    )
    frontend_origin: str = "http://localhost:5173"
    upload_dir: Path = Path("uploads")
    chroma_path: Path = Path("data/chroma")
    max_upload_size_mb: int = 10
    admin_email: str | None = None
    admin_password: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_extraction_model: str = "openai/gpt-4o-mini"
    openrouter_answer_model: str = "openai/gpt-4o-mini"
    openrouter_embedding_model: str = "openai/text-embedding-3-small"
    openrouter_site_url: str | None = None
    openrouter_app_name: str = "VendorLens AI"
    openai_api_key: SecretStr | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    openai_extraction_model: str = "gpt-4o-mini"
    openai_answer_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    extraction_max_completion_tokens: int = Field(default=4096, ge=1024, le=16384)
    extraction_prompt_version: str = "extraction-v4"
    answer_prompt_version: str = "rag-answer-v3"
    assistant_prompt_version: str = "supplier-assistant-v2"
    langfuse_enabled: bool = True
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_capture_content: bool = False
    langfuse_release: str | None = None
    chunk_size_tokens: int = 500
    chunk_overlap_tokens: int = 75
    rag_top_k: int = 4
    rag_max_distance: float = 0.72
    mock_erp_mcp_url: str | None = None
    mock_erp_timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def use_openrouter(self) -> bool:
        return bool(
            self.openrouter_api_key
            and self.openrouter_api_key.get_secret_value().strip()
        )

    @property
    def ai_provider(self) -> str:
        return "openrouter" if self.use_openrouter else "azure"

    @property
    def ai_configured(self) -> bool:
        return self.use_openrouter or bool(
            self.openai_api_key and self.openai_api_key.get_secret_value().strip()
            and self.azure_openai_endpoint and self.azure_openai_endpoint.strip()
        )

    @property
    def active_extraction_model(self) -> str:
        if self.use_openrouter:
            return self.openrouter_extraction_model
        return self.openai_extraction_model

    @property
    def active_answer_model(self) -> str:
        if self.use_openrouter:
            return self.openrouter_answer_model
        return self.openai_answer_model

    @property
    def active_embedding_model(self) -> str:
        if self.use_openrouter:
            return self.openrouter_embedding_model
        return self.openai_embedding_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
