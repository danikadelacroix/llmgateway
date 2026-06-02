# router/traffic_router.py — Cost-aware payload router
# TODO: inspect payload size + token estimate
# Small/simple  → cheap upstream (Haiku / GPT-3.5)
# Large/complex → expensive upstream (Sonnet / GPT-4o)
# Routing decision based on payload signals only — not semantic meaning
