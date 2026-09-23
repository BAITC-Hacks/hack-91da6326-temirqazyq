"""Validated backend-only AI configuration. Secrets never enter public metadata."""

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


ROOT = Path(__file__).resolve().parents[3]
COMPATIBLE_MODELS = frozenset({"gpt-4.1-mini", "gpt-4.1-mini-2025-04-14"})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai_enabled: bool = True
    ai_provider: str = "openai"
    openai_model: str = "gpt-4.1-mini"
    openai_api_key: str = Field(default="", repr=False, exclude=True)
    ai_allow_template_fallback: bool = False
    ai_max_model_calls_per_run: int = Field(default=6, ge=1, le=6)
    ai_max_tool_calls_per_run: int = Field(default=8, ge=1, le=8)
    ai_max_repair_rounds: int = Field(default=2, ge=0, le=2)
    ai_max_candidates: int = Field(default=3, ge=1, le=3)
    ai_max_input_tokens: int = Field(default=12000, ge=1, le=12000)
    ai_max_output_tokens: int = Field(default=2500, ge=1, le=2500)
    ai_run_timeout_seconds: float = Field(default=120, gt=0, le=120)
    ai_max_concurrent_runs: int = Field(default=1, ge=1, le=1)
    ai_daily_spend_limit_usd: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    ai_run_estimated_cost_limit_usd: float = Field(default=0.10, gt=0, allow_inf_nan=False)
    allow_live_ai_tests: bool = False
    db_path: Path = ROOT / "var" / "akim.sqlite3"
    ai_pricing_path: Path = ROOT / "data" / "ai_pricing.json"

    @classmethod
    def from_env(cls, *, load_dotenv: bool = True) -> "Settings":
        if load_dotenv:
            from dotenv import load_dotenv as load_environment

            load_environment(ROOT / ".env", override=False)
        values = {
            name: os.environ[name.upper()]
            for name in cls.model_fields
            if name.upper() in os.environ
        }
        return cls.model_validate(values)

    def public(self) -> dict[str, Any]:
        result = self.model_dump(mode="json", exclude={"db_path", "ai_pricing_path"})
        result["key_configured"] = bool(self.openai_api_key.strip())
        result["model_compatible"] = self.openai_model in COMPATIBLE_MODELS
        result["provider_available"] = (
            self.ai_enabled
            and self.ai_provider == "openai"
            and result["key_configured"]
            and result["model_compatible"]
        )
        return result
