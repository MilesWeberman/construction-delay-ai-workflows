"""Thin wrapper over litellm, so the model can be swapped with one env var."""

import os

import litellm
from pydantic import BaseModel

DEFAULT_MODEL = "anthropic/claude-sonnet-5"
KEY_FOR_PROVIDER = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}

litellm.suppress_debug_info = True  # hide litellm's "Give Feedback" banner on errors


def model() -> str:
    return os.environ.get("LLM_MODEL") or DEFAULT_MODEL


def missing_api_key() -> str | None:
    """The env var the configured model needs but doesn't have, if any."""
    key = KEY_FOR_PROVIDER.get(model().split("/", 1)[0])
    return key if key and not os.environ.get(key, "").strip() else None


def complete_structured[T: BaseModel](system: str, user: str, schema: type[T]) -> T:
    """Ask the model for a JSON answer matching schema."""
    response = litellm.completion(
        model=model(),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=schema,
        max_tokens=4096,
    )
    return schema.model_validate_json(response.choices[0].message.content)
