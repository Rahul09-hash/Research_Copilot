from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LLMResult:
    content: str
    used_model: bool
    error: str | None = None


class LocalLLM:
    def __init__(self, host: str, model: str, num_ctx: int = 2048, num_predict: int = 512):
        self.host = host
        self.model = model
        self.num_ctx = num_ctx
        self.num_predict = num_predict

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> LLMResult:
        try:
            import ollama

            client = ollama.Client(host=self.host)
            response = client.chat(
                model=self.model,
                messages=messages,
                options=self._options(temperature),
            )
            content = response.get("message", {}).get("content", "").strip()
            return LLMResult(content=content or "The local model returned an empty response.", used_model=True)
        except Exception as exc:  # pragma: no cover - depends on local Ollama service
            return LLMResult(
                content="",
                used_model=False,
                error=f"{exc.__class__.__name__}: {exc}",
            )

    def stream_chat(self, messages: list[dict[str, str]], temperature: float = 0.2):
        import ollama

        client = ollama.Client(host=self.host)
        for chunk in client.chat(
            model=self.model,
            messages=messages,
            options=self._options(temperature),
            stream=True,
        ):
            content = chunk.get("message", {}).get("content", "")
            if content:
                yield content

    def _options(self, temperature: float) -> dict[str, float | int]:
        return {
            "temperature": temperature,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
        }
