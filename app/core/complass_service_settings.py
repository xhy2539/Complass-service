"""合规罗盘服务配置模块，统一读取环境变量和默认启动参数。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ComplassServiceSettings(BaseSettings):
    """集中管理环境变量，避免配置散落在业务代码中。"""

    app_name: str = "合规罗盘后端服务"
    app_version: str = "0.1.0"
    service_name: str = "complass-service"
    app_env: str = "local"
    database_url: str = "sqlite:///./complass.db"
    coze_api_base_url: str = "https://api.coze.cn"
    coze_api_token: str = ""
    coze_workflow_id: str = ""
    coze_mock_enabled: bool = True
    max_upload_size_mb: int = 20

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_complass_service_settings() -> ComplassServiceSettings:
    """缓存配置对象，减少重复读取环境变量的开销。"""
    return ComplassServiceSettings()
