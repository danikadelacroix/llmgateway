how is this, now I should put both these files on github as well right?

# config/config_manager.py

import yaml

from pydantic import BaseModel, Field

from typing import Dict, List





class TierConfig(BaseModel):

    model: str

    priority: int

    timeout: int = Field(default=30)





class GatewayRules(BaseModel):

    default_tier: str

    failover_on: List[int]

    max_retries: int





class AppConfig(BaseModel):

    tiers: Dict[str, TierConfig]

    gateway: GatewayRules



    def ordered_tiers(self) -> List[tuple]:

        """Returns tiers sorted by priority — main.py calls this, not raw dict."""

        return sorted(self.tiers.items(), key=lambda x: x[1].priority)





def load_config(yaml_path: str = "config/gateway_config.yaml") -> AppConfig:

    try:

        with open(yaml_path, "r") as f:

            raw = yaml.safe_load(f)

        return AppConfig(**raw)



    except FileNotFoundError:

        raise RuntimeError(f"CRITICAL: Missing config at '{yaml_path}'. Gateway cannot start.")



    except Exception as e:

        raise RuntimeError(f"CRITICAL: Invalid config — {str(e)}")





if __name__ == "__main__":

    config = load_config()

    print("✅ Config loaded successfully!")

    print(f"Default tier : {config.gateway.default_tier}")

    print(f"Active model : {config.tiers[config.gateway.default_tier].model}")

    print(f"Failover on  : {config.gateway.failover_on}")

    print(f"Tier order   : {[name for name, _ in config.ordered_tiers()]}")