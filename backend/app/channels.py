"""Shared inbound/outbound contract for website chat and future channel adapters."""

from typing import Protocol
from pydantic import BaseModel, Field


class InboundMessage(BaseModel):
    content: str = Field(min_length=1, max_length=16000)
    client_id: str = Field(min_length=1, max_length=100)


class ChannelAdapter(Protocol):
    name: str

    def inbound(self, payload: dict) -> InboundMessage: ...
    def outbound(self, message) -> dict: ...


class WebChatChannel:
    name = "web"

    def inbound(self, payload):
        return InboundMessage.model_validate(payload)

    def outbound(self, message):
        return {
            k: getattr(message, k)
            for k in ("id", "role", "content", "sources", "created", "client_id")
        }


web_chat: ChannelAdapter = WebChatChannel()
