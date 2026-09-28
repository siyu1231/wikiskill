"""Chat client: OpenAI-compatible HTTP client + MockLLM for deterministic tests."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from typing import Callable


class LLM:
    """Protocol: chat(messages, system=None) -> str. messages = [{"role","content"},...]."""

    def chat(self, messages: list[dict], system: str | None = None) -> str:  # pragma: no cover
        raise NotImplementedError


class OpenAICompatLLM(LLM):
    def __init__(self, model: str, base_url: str | None = None, api_key: str | None = None,
                 temperature: float = 0.0, timeout: int = 300):
        self.model = model
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or ""
        self.temperature = temperature
        self.timeout = timeout

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + list(messages)
        body = json.dumps({"model": self.model, "messages": msgs, "temperature": self.temperature}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"]


class MockLLM(LLM):
    """Scripted responses for tests. responses: list (popped in order) or callable(messages, system)->str."""

    def __init__(self, responses: list[str] | Callable[[list[dict], str | None], str]):
        self._responses = list(responses) if isinstance(responses, list) else None
        self._fn = responses if callable(responses) else None
        self.calls: list[dict] = []

    def chat(self, messages: list[dict], system: str | None = None) -> str:
        self.calls.append({"messages": list(messages), "system": system})
        if self._fn is not None:
            return self._fn(messages, system)
        if not self._responses:
            raise RuntimeError("MockLLM script exhausted")
        return self._responses.pop(0)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> dict | list | None:
    """Tolerant extraction of the first JSON object/array from an LLM reply."""
    if not text:
        return None
    candidates = [m.group(1) for m in _FENCE_RE.finditer(text)]
    candidates.append(text)
    for cand in candidates:
        for opener, closer in (("{", "}"), ("[", "]")):
            start = cand.find(opener)
            if start == -1:
                continue
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(cand)):
                ch = cand[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cand[start:i + 1])
                        except json.JSONDecodeError:
                            break
    return None
