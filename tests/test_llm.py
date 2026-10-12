import pytest

from delay_ai.llm import missing_api_key


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "ANTHROPIC_API_KEY"),
        ({"ANTHROPIC_API_KEY": ""}, "ANTHROPIC_API_KEY"),  # an empty line in .env
        ({"ANTHROPIC_API_KEY": "sk-ant-x"}, None),
        ({"LLM_MODEL": "openai/gpt-x"}, "OPENAI_API_KEY"),
        ({"LLM_MODEL": "ollama/llama"}, None),  # unknown provider: don't guess
    ],
)
def test_missing_api_key(monkeypatch, env, expected):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    assert missing_api_key() == expected
