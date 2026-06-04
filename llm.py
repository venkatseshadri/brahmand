"""Shared LLM provider for DeepSeek CrewAI agents."""

import os


def get_llm():
    """Return DeepSeek LLM or None if API key is unavailable."""
    from crewai import LLM

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return None
    return LLM(
        model="deepseek-v4-pro",
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        api_key=api_key,
        temperature=0,
    )
