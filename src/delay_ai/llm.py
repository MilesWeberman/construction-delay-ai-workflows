"""Thin wrapper over litellm, so the model can be swapped with one env var."""

import os

import litellm
from pydantic import BaseModel

DEFAULT_MODEL = "anthropic/claude-sonnet-5"


def complete_structured[T: BaseModel](system: str, user: str, schema: type[T]) -> T:
    """Ask the model for a JSON answer matching schema."""
    response = litellm.completion(
        model=os.environ.get("LLM_MODEL", DEFAULT_MODEL),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=schema,
        max_tokens=4096,
    )
    return schema.model_validate_json(response.choices[0].message.content)
