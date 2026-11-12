"""Usage and configured price calculations for synchronous LLM operations."""

from decimal import Decimal

from app.config import Settings
from app.models.api import CostSummary, UsageSummary
from app.models.llm import LLMTokenUsage


def usage_and_cost(settings: Settings, usage: LLMTokenUsage | None) -> tuple[UsageSummary | None, CostSummary]:
    summary = UsageSummary.from_llm_usage(usage)
    input_rate = settings.llm_input_cost_per_million_tokens
    output_rate = settings.llm_output_cost_per_million_tokens
    version = settings.llm_pricing_version
    estimated: Decimal | None = None
    if (
        usage is not None
        and usage.prompt_tokens is not None
        and usage.completion_tokens is not None
        and input_rate is not None
        and output_rate is not None
        and version
    ):
        estimated = (
            Decimal(usage.prompt_tokens) * input_rate
            + Decimal(usage.completion_tokens) * output_rate
        ) / Decimal(1_000_000)
        estimated = estimated.quantize(Decimal("0.00000001"))
    return summary, CostSummary(
        estimated_cost_usd=estimated,
        pricing_version=version,
        input_cost_per_million_tokens=input_rate,
        output_cost_per_million_tokens=output_rate,
    )
