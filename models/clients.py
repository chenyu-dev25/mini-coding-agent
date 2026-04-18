"""Simple model clients for optional LLM-backed skills."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class ChatModelClient(ABC):
    """Abstract chat completion client."""

    @abstractmethod
    def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> str:
        """Return the assistant text content."""


class MoonshotModelClient(ChatModelClient):
    """Minimal Moonshot/Kimi client using the OpenAI-compatible REST API."""

    def __init__(
        self,
        api_key: str,
        model: str = "kimi-k2.5",
        base_url: str = "https://api.moonshot.ai/v1",
        timeout: int = 60,
        disable_thinking: bool = True,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.disable_thinking = disable_thinking

    def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> str:
        payload: Dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Moonshot API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Moonshot API request failed: {exc}") from exc

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Moonshot response: {data}") from exc


class FakeChatModelClient(ChatModelClient):
    """Deterministic fake client for tests."""

    def __init__(self, outputs: List[str]):
        self.outputs = list(outputs)
        self.prompts: List[List[Dict[str, str]]] = []

    def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        max_tokens: int = 1200,
        temperature: float = 0.2,
    ) -> str:
        self.prompts.append(messages)
        if not self.outputs:
            raise RuntimeError("fake client ran out of outputs")
        return self.outputs.pop(0)


def build_moonshot_client_from_env(
    model: str = "kimi-k2.5",
    api_key_env: str = "MOONSHOT_API_KEY",
    base_url_env: str = "MOONSHOT_BASE_URL",
) -> Optional[MoonshotModelClient]:
    """Create a Moonshot client from environment variables if configured."""
    api_key = os.getenv(api_key_env)
    if not api_key:
        return None
    return MoonshotModelClient(
        api_key=api_key,
        model=model,
        base_url=os.getenv(base_url_env, "https://api.moonshot.ai/v1"),
    )


def extract_json_object(text: str) -> Dict:
    """Best-effort JSON extraction from model output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"No JSON object found in model output: {text[:200]}")
    return json.loads(text[start : end + 1])
