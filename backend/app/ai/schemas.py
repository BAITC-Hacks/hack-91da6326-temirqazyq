from typing import Literal

from pydantic import BaseModel, ConfigDict


class ExplanationText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    strengths: list[str]
    risks: list[str]
    tradeoffs: list[str]
    recommendations: list[str]


class Explanation(ExplanationText):
    source: Literal["template", "openai"] = "template"

