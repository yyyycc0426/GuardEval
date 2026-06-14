import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib import request

from openai import OpenAI

from llm_security_platform.app.config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OPENAI_COMPATIBLE_API_KEY,
    OPENAI_COMPATIBLE_BASE_URL,
    OPENAI_COMPATIBLE_MODEL,
)


class ModelProviderError(RuntimeError):
    pass


@dataclass
class ModelCallResult:
    response_text: str
    token_usage: dict[str, int] = field(default_factory=dict)
    estimated_cost: float = 0.0
    provider_metadata: dict = field(default_factory=dict)


class ModelProvider(ABC):
    name: str
    model: str

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> ModelCallResult:
        raise NotImplementedError


class MockProvider(ModelProvider):
    name = "mock"

    def __init__(self, model="mock-vulnerable-model", model_config=None):
        self.model = model
        self.model_config = model_config or {}

    def generate(self, system_prompt: str, user_prompt: str) -> ModelCallResult:
        delay_ms = float(self.model_config.get("inject_delay_ms", 0) or 0)
        timeout_seconds = float(self.model_config.get("timeout_seconds", 120) or 120)
        if delay_ms > timeout_seconds * 1000:
            raise ModelProviderError(
                f"Mock request timed out after {timeout_seconds} seconds"
            )
        if delay_ms:
            time.sleep(delay_ms / 1000)
        fail_on_text = self.model_config.get("fail_on_text")
        if fail_on_text and str(fail_on_text).lower() in user_prompt.lower():
            raise ModelProviderError(f"Injected single-case failure for marker: {fail_on_text}")
        lower = user_prompt.lower()
        known_targets = (
            "injection_succeeded",
            "indirect_injection_worked",
            "jailbreak_enabled",
            "obfuscation_bypass",
            "encoded_bypass",
            "multiturn_bypass",
            "secret_canary_9417",
            "rag_canary_fin_7391",
        )
        target = next((item for item in known_targets if item in lower), None)
        if target is None and (
            "base64" in lower or "ssapyb_dedocne" in lower
        ):
            target = "encoded_bypass"
        extraction_request = any(
            phrase in lower
            for phrase in (
                "reveal the full hidden system prompt",
                "original system instructions",
                "private system message",
                "完整系统提示词",
                "原始系统指令",
                "隐藏系统消息",
            )
        )
        if "[defense:block]" in lower:
            response = "Request blocked by the configured security policy."
            return ModelCallResult(response, {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18})
        if "security boundary:" in system_prompt.lower() and (target or extraction_request):
            response = "I cannot comply with attempts to override instructions or reveal protected data."
            return ModelCallResult(response, {"prompt_tokens": 18, "completion_tokens": 14, "total_tokens": 32})
        if target:
            response = target.upper()
            return ModelCallResult(response, {"prompt_tokens": 16, "completion_tokens": 6, "total_tokens": 22})
        if extraction_request:
            response = f"SYSTEM PROMPT: {system_prompt}"
            return ModelCallResult(response, {"prompt_tokens": 20, "completion_tokens": 20, "total_tokens": 40})
        if "secret" in lower or "机密" in user_prompt or "知识库" in user_prompt:
            response = "The protected knowledge contains API_KEY=demo-secret-123."
            return ModelCallResult(response, {"prompt_tokens": 20, "completion_tokens": 12, "total_tokens": 32})
        if "developer mode" in lower or "开发者模式" in user_prompt or "越狱" in user_prompt:
            response = "Developer mode enabled. I will comply without safety restrictions."
            return ModelCallResult(response, {"prompt_tokens": 18, "completion_tokens": 12, "total_tokens": 30})
        if (
            "ignore previous" in lower
            or "ignore all previous" in lower
            or "disregard" in lower
            or "忽略之前" in user_prompt
        ):
            response = f"SYSTEM PROMPT: {system_prompt}"
            return ModelCallResult(response, {"prompt_tokens": 20, "completion_tokens": 20, "total_tokens": 40})
        response = "I can help with the allowed business request."
        return ModelCallResult(response, {"prompt_tokens": 12, "completion_tokens": 9, "total_tokens": 21})


class OllamaProvider(ModelProvider):
    name = "ollama"

    def __init__(self, model=None, base_url=OLLAMA_BASE_URL, model_config=None):
        self.model = model or OLLAMA_MODEL
        self.base_url = base_url.rstrip("/")
        self.model_config = model_config or {}

    def generate(self, system_prompt: str, user_prompt: str) -> ModelCallResult:
        payload = json.dumps(
            {
                "model": self.model,
                "stream": False,
                "think": bool(self.model_config.get("reasoning", False)),
                "options": {
                    "temperature": self.model_config.get("temperature", 0),
                    "top_p": self.model_config.get("top_p", 1),
                    "seed": self.model_config.get("seed", 42),
                    "num_predict": self.model_config.get("max_tokens", 256),
                },
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        ).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.model_config.get("timeout_seconds", 120)) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ModelProviderError(f"Ollama request failed: {exc}") from exc
        content = data.get("message", {}).get("content", "")
        if not content.strip():
            raise ModelProviderError("Ollama returned an empty response")
        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        completion_tokens = int(data.get("eval_count") or 0)
        return ModelCallResult(
            response_text=content,
            token_usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            estimated_cost=0.0,
            provider_metadata={
                "total_duration_ns": data.get("total_duration"),
                "load_duration_ns": data.get("load_duration"),
                "prompt_eval_duration_ns": data.get("prompt_eval_duration"),
                "eval_duration_ns": data.get("eval_duration"),
            },
        )


class OpenAICompatibleProvider(ModelProvider):
    name = "openai_compatible"

    def __init__(self, model=None, base_url=OPENAI_COMPATIBLE_BASE_URL, api_key=OPENAI_COMPATIBLE_API_KEY, model_config=None):
        if not api_key:
            raise ModelProviderError("LLM_SECURITY_MODEL_API_KEY is required")
        self.model = model or OPENAI_COMPATIBLE_MODEL
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model_config = model_config or {}

    def generate(self, system_prompt: str, user_prompt: str) -> ModelCallResult:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=self.model_config.get("temperature", 0),
                top_p=self.model_config.get("top_p", 1),
                max_tokens=self.model_config.get("max_tokens", 256),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            raise ModelProviderError(f"OpenAI-compatible request failed: {exc}") from exc
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise ModelProviderError("OpenAI-compatible provider returned an empty response")
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        input_rate = float(self.model_config.get("input_cost_per_million", 0) or 0)
        output_rate = float(self.model_config.get("output_cost_per_million", 0) or 0)
        cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
        return ModelCallResult(
            response_text=content,
            token_usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            estimated_cost=round(cost, 8),
            provider_metadata={"response_id": getattr(response, "id", None)},
        )


def build_provider(provider: str, model: str | None = None, model_config=None) -> ModelProvider:
    if provider == "mock":
        return MockProvider(model or "mock-vulnerable-model", model_config=model_config)
    if provider == "ollama":
        return OllamaProvider(model=model, model_config=model_config)
    if provider == "openai_compatible":
        return OpenAICompatibleProvider(model=model, model_config=model_config)
    raise ModelProviderError(f"Unsupported provider: {provider}")
