# guardrails/cost_guardrail.py
#
# =============================================================================
# STEP 1 — SDD: DEFINE THE CONTRACT (Schemas First, Logic Second)
#
# Before writing a single line of business logic, SDD demands we define:
#   (a) What configuration does this module accept?     → BudgetConfig
#   (b) What is the output data shape of a check?       → CostEstimate
#
# These two models ARE the spec. The implementation below is just fulfillment
# of that spec. FastAPI will auto-document them in /docs.
# ===========
==================================================================

from __future__ import annotations

from typing import Dict, List
from pydantic import BaseModel, Field
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# SDD SCHEMA (a): Configuration contract
# ---------------------------------------------------------------------------

class ModelCostConfig(BaseModel):
    """Per-model token pricing (USD). Define this before writing any math."""

    input_cost_per_1k_tokens: float = Field(
        ..., gt=0, description="USD charged per 1,000 input (prompt) tokens."
    )
    output_cost_per_1k_tokens: float = Field(
        ..., gt=0, description="USD charged per 1,000 output (completion) tokens."
    )


class BudgetConfig(BaseModel):
    """Top-level guardrail configuration. Validates at startup, not at request time."""

    enabled: bool = Field(
        default=True, description="Set False to disable cost checking globally."
    )
    max_request_cost_usd: float = Field(
        ..., gt=0, description="Hard ceiling per request in USD. Requests estimated above this are rejected 402."
    )
    model_costs: Dict[str, ModelCostConfig] = Field(
        default_factory=dict,
        description="Known per-model pricing. Key must match the LiteLLM model string."
    )
    default_cost_config: ModelCostConfig = Field(
        ..., description="Fallback pricing used when a model is not found in model_costs."
    )


# ---------------------------------------------------------------------------
# SDD SCHEMA (b): Output contract — what every .check() call returns
# ---------------------------------------------------------------------------

class CostEstimate(BaseModel):
    """The structured result of a budget check. Serialisable — can be returned as JSON."""

    model_resolved: str = Field(..., description="The model key whose cost config was used.")
    estimated_input_tokens: int = Field(..., description="Estimated prompt token count.")
    estimated_cost_usd: float = Field(..., description="Projected cost in USD for this request.")
    within_budget: bool = Field(..., description="True if cost is at or below the budget ceiling.")
    budget_limit_usd: float = Field(..., description="The configured ceiling this check was evaluated against.")


# =============================================================================
# STEP 2 — IMPLEMENTATION (driven entirely by the schemas above)
# =============================================================================

class BudgetGuardrail:
    """
    Intercepts requests before they reach LiteLLM and rejects any whose estimated
    cost exceeds the configured budget ceiling.

    Sits in the request pipeline AFTER the rate limiter and BEFORE the cache
    lookup, because if the request is over budget we should not pollute the cache.

    Integration in main.py:
        guardrail = BudgetGuardrail(config=BudgetConfig(...))

        @app.post("/v1/chat", dependencies=[Depends(token_bucket_limit)])
        async def proxy(body: ChatCompletionRequest, request: Request):
            guardrail.check(messages=body.messages_as_dicts(), model=body.model)
            # ... rest of pipeline
    """

    # Average English characters per BPE token (conservative estimate; avoids
    # importing tiktoken as a hard dependency and keeps startup fast).
    _CHARS_PER_TOKEN: int = 4

    def __init__(self, config: BudgetConfig) -> None:
        # Config is validated by Pydantic at construction time — never at request time.
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def estimate(self, messages: List[dict], model: str = "auto") -> CostEstimate:
        """
        Calculate the cost of `messages` for `model` without enforcing limits.
        """
        if not self.config.enabled:
            return CostEstimate(
                model_resolved="disabled",
                estimated_input_tokens=0,
                estimated_cost_usd=0.0,
                within_budget=True,
                budget_limit_usd=self.config.max_request_cost_usd,
            )

        cost_cfg, resolved_key = self._resolve_cost_config(model)
        token_count = self._estimate_tokens(messages)
        estimated_cost = round((token_count / 1000) * cost_cfg.input_cost_per_1k_tokens, 8)
        within_budget = estimated_cost <= self.config.max_request_cost_usd

        return CostEstimate(
            model_resolved=resolved_key,
            estimated_input_tokens=token_count,
            estimated_cost_usd=estimated_cost,
            within_budget=within_budget,
            budget_limit_usd=self.config.max_request_cost_usd,
        )

    def check(self, messages: List[dict], model: str = "auto") -> CostEstimate:
        """
        Estimate the cost of `messages` for `model` and raise HTTP 402 if it
        exceeds the configured budget.

        Args:
            messages: The raw messages list from the incoming request body.
            model:    The LiteLLM model string (e.g. "groq/llama3-8b-8192").

        Returns:
            CostEstimate — the structured check result (caller can log/return it).

        Raises:
            HTTPException(402) — if cost exceeds budget and guardrail is enabled.
        """
        estimate_result = self.estimate(messages, model)

        if not estimate_result.within_budget:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "request_exceeds_budget",
                    "failed_cap": "per_request",
                    "cap_limit_usd": self.config.max_request_cost_usd,
                    "message": (
                        f"Estimated cost ${estimate_result.estimated_cost_usd:.6f} exceeds the "
                        f"configured budget of ${self.config.max_request_cost_usd:.6f}."
                    ),
                    "estimate": estimate_result.model_dump(),
                },
            )

        return estimate_result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_cost_config(self, model: str):
        """Return (ModelCostConfig, resolved_key). Falls back to default."""
        if model in self.config.model_costs:
            return self.config.model_costs[model], model
        return self.config.default_cost_config, "__default__"

    def _estimate_tokens(self, messages: List[dict]) -> int:
        """Estimate total input tokens from raw message dicts."""
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return max(1, total_chars // self._CHARS_PER_TOKEN)
