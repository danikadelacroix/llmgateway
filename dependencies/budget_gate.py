# dependencies/budget_gate.py
from fastapi import Request, HTTPException, Depends
from dependencies.rate_limiter import token_bucket_limit
from guardrails.cost_guardrail import BudgetGuardrail, BudgetConfig, ModelCostConfig
from telemetry.metrics import budget_rejections_total

# Temporary hardcoded guardrail for Phase 3
_temp_budget_config = BudgetConfig(
    enabled=True,
    max_request_cost_usd=0.01,
    model_costs={},
    default_cost_config=ModelCostConfig(
        input_cost_per_1k_tokens=0.10,
        output_cost_per_1k_tokens=0.20,
    ),
)
guardrail = BudgetGuardrail(config=_temp_budget_config)

async def enforce_budget(request: Request, body: dict, _=Depends(token_bucket_limit)):
    """
    Enforces the budget limit before routing to the cache or upstream provider.
    Must run after rate limiting (which is why token_bucket_limit is a Depends).
    Increments the budget_rejections_total Prometheus counter on 402 rejections.
    """
    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="The 'messages' array cannot be empty.")

    model = body.get("model", "auto")

    try:
        guardrail.check(messages, model=model)
    except HTTPException as exc:
        if exc.status_code == 402:
            # 🚨 Instrument: count every budget rejection for Prometheus / Grafana
            budget_rejections_total.inc()
        raise

