"""环境优先配置：环境变量 > config.yaml > 代码默认值。

Globex 同款纪律：config.yaml 里只放"站点源、模型档案、密钥的环境变量名"，
真实密钥只存在于环境变量（.env），且 .env 永不入库。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# src/contest_agent/settings.py -> 项目根（config.yaml / data/ 所在处）
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DATABASE_URL = f"sqlite:///{PROJECT_ROOT / 'data' / 'contest_agent.db'}"


class ModelProfile(BaseModel):
    """一个可热切换的模型档案（openai 兼容层）。"""

    name: str
    base_url: str
    api_key_env: str
    model: str

    def resolve_api_key(self) -> str | None:
        return os.environ.get(self.api_key_env)


class SourceConfig(BaseModel):
    """一个待扫描的站点源（P1 爬虫的输入）。"""

    name: str
    base_url: str
    list_path: str
    detail_pattern: str = ""
    request_interval: float = Field(default=1.5, ge=0.5)  # 爬虫合规：>=1.5s


class YamlConfig(BaseModel):
    """config.yaml 的结构化映射。"""

    active_model: str = "deepseek"
    models: dict[str, ModelProfile]
    sources: list[SourceConfig]


class Settings(BaseModel):
    """组装后的运行时配置。"""

    database_url: str = DEFAULT_DATABASE_URL
    active_model: str = "deepseek"
    yaml_config: YamlConfig

    @property
    def active_profile(self) -> ModelProfile:
        profile = self.yaml_config.models.get(self.active_model)
        if profile is None:
            raise KeyError(f"active_model '{self.active_model}' 不在 config.yaml models 中")
        return profile


def load_yaml_config(path: Path | None = None) -> YamlConfig:
    config_path = path or PROJECT_ROOT / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    # yaml 里档案键名即档案名，注入到 profile.name，避免配置里重复写
    for name, profile in (raw.get("models") or {}).items():
        profile.setdefault("name", name)
    return YamlConfig.model_validate(raw)


@lru_cache
def load_settings() -> Settings:
    """env 优先：ACTIVE_MODEL / DATABASE_URL 环境变量可覆盖 config.yaml。"""
    yaml_config = load_yaml_config()
    return Settings(
        database_url=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
        active_model=os.environ.get("ACTIVE_MODEL", yaml_config.active_model),
        yaml_config=yaml_config,
    )
