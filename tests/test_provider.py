import json

import httpx
import pytest

from helpdesk_agent.provider import OpenAIProvider, ProviderError


@pytest.mark.asyncio
async def test_openai_adapter(monkeypatch):
    """Validate HTTP contract without using a key or claiming model quality."""
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-only")
    monkeypatch.setenv("OPENAI_MODEL", "account-model")
    d = dict(
        kind="clarify",
        question="Which error do you see?",
        diagnosis="",
        evidence_ids=[],
        queries=[],
        runbook_id="",
        action="none",
        resource="",
        justification="",
        condition_evidence=[],
    )

    async def post(client, url, **kw):
        assert url == "https://api.openai.com/v1/responses"
        body = kw["json"]
        assert body["store"] is False
        assert body["text"]["format"]["strict"] is True
        assert body["text"]["format"]["schema"]["additionalProperties"] is False
        assert "fake-test-only" not in json.dumps(body)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"content": [{"type": "output_text", "text": json.dumps(d)}]}
                ],
                "usage": {"input_tokens": 100, "output_tokens": 25},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    result, usage = await OpenAIProvider().decide({"conversation": []})
    assert result.kind == "clarify" and usage["input_tokens"] == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 400])
async def test_errors_do_not_expose_key(monkeypatch, status):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-only")
    monkeypatch.setenv("OPENAI_MODEL", "account-model")

    async def post(*a, **kw):
        return httpx.Response(status, json={"error": "sensitive body should not leak"})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(ProviderError, match=f"model_http_{status}") as exc:
        await OpenAIProvider().decide({})
    assert "fake-test-only" not in str(exc.value)


@pytest.mark.asyncio
async def test_refusal_is_not_parsed_as_decision(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-only")
    monkeypatch.setenv("OPENAI_MODEL", "account-model")

    async def post(*a, **kw):
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"content": [{"type": "refusal", "refusal": "Cannot comply"}]}
                ],
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(ProviderError):
        await OpenAIProvider().decide({})


@pytest.fixture(autouse=True)
def isolated_endpoint(monkeypatch):
    # Unit tests must not depend on the operator's project endpoint.
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base", ["https://api.anzhelyu.com/v1", "https://api.anzhelyu.com/v1/"]
)
async def test_project_relay_request(monkeypatch, base):
    monkeypatch.setenv("OPENAI_BASE_URL", base)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    monkeypatch.setenv("OPENAI_API_KEY", "relay-test-key")

    async def post(client, url, **kw):
        assert url == "https://api.anzhelyu.com/v1/responses"
        assert kw["headers"]["Authorization"] == "Bearer relay-test-key"
        assert kw["json"]["model"] == "gpt-6.1-sol"
        assert kw["json"]["store"] is False
        # Codex settings are not API request fields.
        assert (
            not {"goals", "review_model", "requires_openai_auth", "network_access"}
            & kw["json"].keys()
        )
        return httpx.Response(401, json={})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(ProviderError, match="model_http_401"):
        await OpenAIProvider().decide({})


@pytest.mark.parametrize(
    "base",
    [
        "",
        "https://user:secret@host/v1",
        "https://host/v1?key=secret",
        "https://host/v1#frag",
        "http://external.invalid/v1",
        "ftp://host/v1",
        "https://host/v1/responses",
    ],
)
def test_bad_base_url_rejected(monkeypatch, base):
    monkeypatch.setenv("OPENAI_BASE_URL", base)
    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        OpenAIProvider()
