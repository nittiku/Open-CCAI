"""Provider-neutral contracts. No proxy or hosted project service is required."""

import os

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol
from .models import Credential
from .security import decrypt, outbound_url
from .config import settings


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass
class Reply:
    text: str = ""
    calls: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0


class ProviderAdapter(Protocol):
    def generate(
        self,
        db,
        provider,
        messages: list,
        tools: list,
        on_chunk: Callable,
        timeout: float = 30,
        output_schema=None,
    ) -> Reply: ...
    def embed(self, db, provider, texts: list[str]) -> list[list[float]]: ...


class LiteLLMAdapter:
    def kwargs(self, db, p):
        credential = db.get(Credential, p.credential_id)
        if not credential:
            raise ProviderError("credential_missing")
        prefix = {
            "openai": "openai",
            "anthropic": "anthropic",
            "gemini": "gemini",
            "compatible": "openai",
        }[p.kind]
        result = {
            "model": f"{prefix}/{p.model}",
            "api_key": decrypt(credential.ciphertext),
            "num_retries": 0,
        }
        if p.base_url:
            outbound_url(p.base_url, settings.provider_hosts)
            result["api_base"] = p.base_url
        return result

    def generate(
        self, db, provider, messages, tools, on_chunk, timeout=30, output_schema=None
    ):
        import litellm

        # Disable optional SDK logging integrations and exception payload verbosity.
        litellm.suppress_debug_info = True
        litellm.telemetry = False
        started = time.monotonic()
        try:
            kwargs = self.kwargs(db, provider)
            kwargs.update(messages=messages, timeout=timeout, max_tokens=1024)
            if tools:
                if not provider.capabilities.get("tools"):
                    raise ProviderError("tools_unsupported")
                kwargs["tools"] = tools
            if output_schema:
                if not provider.capabilities.get("structured"):
                    raise ProviderError("structured_unsupported")
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "result",
                        "schema": output_schema,
                        "strict": True,
                    },
                }
            reply = Reply()
            if provider.capabilities.get("streaming", False):
                stream = litellm.completion(
                    **kwargs, stream=True, stream_options={"include_usage": True}
                )
                calls = {}
                try:
                    for part in stream:
                        if time.monotonic() - started > timeout:
                            raise ProviderError("timeout")
                        if getattr(part, "usage", None):
                            reply.input_tokens = part.usage.prompt_tokens or 0
                            reply.output_tokens = part.usage.completion_tokens or 0
                        if not part.choices:
                            continue
                        delta = part.choices[0].delta
                        if delta.content:
                            reply.text += delta.content
                            on_chunk(delta.content)
                        for call in delta.tool_calls or []:
                            item = calls.setdefault(
                                call.index,
                                {
                                    "id": "",
                                    "type": "function",
                                    "function": {"name": "", "arguments": ""},
                                },
                            )
                            if call.id:
                                item["id"] = call.id
                            if call.function:
                                if call.function.name:
                                    item["function"]["name"] += call.function.name
                                if call.function.arguments:
                                    item["function"][
                                        "arguments"
                                    ] += call.function.arguments
                    reply.calls = [calls[k] for k in sorted(calls)]
                finally:
                    if hasattr(stream, "close"):
                        stream.close()
            else:
                response = litellm.completion(**kwargs)
                message = response.choices[0].message
                reply.text = message.content or ""
                reply.calls = [c.model_dump() for c in (message.tool_calls or [])]
                if response.usage:
                    reply.input_tokens = response.usage.prompt_tokens or 0
                    reply.output_tokens = response.usage.completion_tokens or 0
                if reply.text:
                    on_chunk(reply.text)
            reply.latency_ms = (time.monotonic() - started) * 1000
            return reply
        except ProviderError:
            raise
        except Exception as exc:
            # Never expose provider exceptions: they may contain requests and credentials.
            code = "provider_error"
            status = getattr(exc, "status_code", None)
            if status in (401, 403):
                code = "authentication_failed"
            elif status == 429:
                code = "rate_limited"
            elif "timeout" in type(exc).__name__.lower():
                code = "timeout"
            raise ProviderError(code) from None

    def embed(self, db, provider, texts):
        import litellm

        if provider.purpose != "embedding":
            raise ProviderError("embedding_provider_required")
        try:
            response = litellm.embedding(
                **self.kwargs(db, provider), input=texts, timeout=30
            )
            return [
                r["embedding"] for r in sorted(response.data, key=lambda x: x["index"])
            ]
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("embedding_failed") from None


adapter: ProviderAdapter = LiteLLMAdapter()
