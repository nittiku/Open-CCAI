import json
import httpx
from jsonschema import Draft202012Validator
from sqlalchemy import select
from .db import Session
from .models import Credential, Invocation
from .security import decrypt, outbound_url
from .config import settings


class ToolError(Exception):
    pass


class UncertainOutcome(ToolError):
    pass


def call_tool(tool, arguments, conversation_id, invocation_key):
    Draft202012Validator(tool.input_schema).validate(arguments)
    outbound_url(tool.url, settings.tool_hosts)
    headers = {"Idempotency-Key": invocation_key, "Accept": "application/json"}
    with Session() as db:
        prior = db.scalar(
            select(Invocation)
            .where(Invocation.invocation_key == invocation_key)
            .with_for_update()
        )
        if prior:
            if prior.status == "succeeded":
                return prior.result
            if not tool.safe_retry:
                prior.status = "uncertain"
                db.commit()
                raise UncertainOutcome("tool_outcome_uncertain")
        else:
            prior = Invocation(
                conversation_id=conversation_id,
                tool_id=tool.id,
                invocation_key=invocation_key,
            )
            db.add(prior)
        if tool.credential_id:
            credential = db.get(Credential, tool.credential_id)
            if not credential:
                raise ToolError("credential_missing")
            headers["Authorization"] = f"Bearer {decrypt(credential.ciphertext)}"
        prior.status = "started"
        db.commit()
        invocation_id = prior.id
    try:
        # Redirects and environment HTTP proxies are deliberately disabled.
        with httpx.Client(
            timeout=tool.timeout, follow_redirects=False, trust_env=False
        ) as client:
            kwargs = (
                {"params": arguments} if tool.method == "GET" else {"json": arguments}
            )
            with client.stream(
                tool.method, tool.url, headers=headers, **kwargs
            ) as response:
                if response.status_code >= 300:
                    raise ToolError("tool_http_error")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > 1_000_000:
                        raise ToolError("tool_response_too_large")
                result = json.loads(content)
        Draft202012Validator(tool.output_schema).validate(result)
        with Session() as db:
            row = db.get(Invocation, invocation_id)
            row.status, row.result = "succeeded", result
            db.commit()
        return result
    except Exception:
        with Session() as db:
            row = db.get(Invocation, invocation_id)
            row.status = "failed" if tool.safe_retry else "uncertain"
            db.commit()
        # A response/schema error can still follow a successful remote side effect.
        raise ToolError(
            "tool_failed" if tool.safe_retry else "tool_outcome_uncertain"
        ) from None
