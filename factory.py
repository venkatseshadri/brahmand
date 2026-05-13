"""
Brahmand Agent & Tool Factory — Dynamic CrewAI agent creation from YAML registries.

Reads agents_registry.yaml and tools_registry.yaml at runtime.
Populates {variable} slots from daily_config / market context.
Returns configured CrewAI Agent and Tool instances.
"""

from pathlib import Path

import yaml
from crewai import Agent

REGISTRY_DIR = Path(__file__).parent / "config"


def _load_yaml(filename: str) -> dict:
    """Load and parse a YAML registry file."""
    path = REGISTRY_DIR / filename
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _resolve_variables(template: str, variables: dict) -> str:
    """Replace {variable} slots in template string with values from variables dict."""
    result = template
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


class AgentFactory:
    """Creates CrewAI Agent instances from agents_registry.yaml blueprints."""

    def __init__(self, registry_path: str = "agents_registry.yaml"):
        self._blueprints = _load_yaml(registry_path)

    def create_agent(
        self,
        role_key: str,
        variables: dict | None = None,
        tools: list = None,
    ) -> Agent:
        """
        Create a CrewAI Agent from its YAML blueprint.

        Args:
            role_key: Key in agents_registry.yaml (e.g. 'execution_agent')
            variables: Dict of {variable} → value for template substitution
            tools: Pre-built list of CrewAI Tool instances
        """
        blueprint = self._blueprints.get(role_key)
        if blueprint is None:
            raise KeyError(
                f"Unknown agent role: {role_key}. "
                f"Available: {list(self._blueprints.keys())}"
            )

        variables = variables or {}

        role = _resolve_variables(blueprint["role"], variables)
        goal = _resolve_variables(blueprint["goal"], variables)
        backstory = _resolve_variables(blueprint["backstory"], variables)
        llm = blueprint.get("llm", "deepseek/deepseek-chat")

        return Agent(
            role=role,
            goal=goal,
            backstory=backstory,
            tools=tools or [],
            llm=llm,
            verbose=True,
        )

    def list_agents(self) -> list[str]:
        """Return available agent role keys."""
        return list(self._blueprints.keys())


class ToolFactory:
    """Maps market types to Tool sets from tools_registry.yaml."""

    def __init__(self, registry_path: str = "tools_registry.yaml"):
        self._market_tools = _load_yaml(registry_path)

    def get_tool_names(self, market_type: str) -> list[str]:
        """Return tool name list for a market type."""
        market_config = self._market_tools.get(market_type)
        if market_config is None:
            raise KeyError(
                f"Unknown market type: {market_type}. "
                f"Available: {list(self._market_tools.keys())}"
            )
        return market_config.get("tools", [])

    def get_broker_info(self, market_type: str) -> dict:
        """Return broker + fallback config for a market type."""
        market_config = self._market_tools.get(market_type, {})
        return {
            "primary": market_config.get("broker"),
            "fallback": market_config.get("broker_fallback"),
        }

    def list_markets(self) -> list[str]:
        """Return available market types."""
        return list(self._market_tools.keys())
