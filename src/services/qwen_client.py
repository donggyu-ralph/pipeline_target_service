"""Qwen API client for data analysis."""
import base64
import time
from typing import Any

import httpx

from src.config import QwenSettings
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class QwenClient:
    def __init__(self, settings: QwenSettings):
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(settings.timeout, connect=10.0),
            headers={"Authorization": f"Bearer {settings.api_key}"},
            verify=False,  # Self-signed cert on MLX server
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def chat(self, messages: list[dict], **kwargs) -> dict[str, Any]:
        """Send a chat completion request to Qwen API."""
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.settings.max_tokens),
            "temperature": kwargs.get("temperature", 0.1),
        }

        start = time.monotonic()
        response = await self.client.post("/chat/completions", json=payload)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        response.raise_for_status()
        result = response.json()

        tokens_used = result.get("usage", {}).get("total_tokens", 0)
        logger.info("qwen_chat_completed", elapsed_ms=elapsed_ms, tokens=tokens_used)

        return {
            "content": result["choices"][0]["message"]["content"],
            "tokens_used": tokens_used,
            "processing_time_ms": elapsed_ms,
            "model": result.get("model", self.settings.model),
        }

    async def analyze_text(self, text: str, task: str = "summarize") -> dict[str, Any]:
        """Analyze text content."""
        prompts = {
            "summarize": f"다음 텍스트를 분석하고 요약해주세요. JSON 형식으로 응답하세요.\n\n키: summary(요약), keywords(키워드 리스트), sentiment(감성: positive/negative/neutral)\n\n텍스트:\n{text}",
            "extract": f"다음 텍스트에서 핵심 정보를 추출해주세요. JSON 형식으로 응답하세요.\n\n텍스트:\n{text}",
        }

        messages = [{"role": "user", "content": prompts.get(task, prompts["summarize"])}]
        return await self.chat(messages)

    async def analyze_csv(self, csv_content: str) -> dict[str, Any]:
        """Analyze CSV data."""
        messages = [
            {
                "role": "user",
                "content": (
                    "다음 CSV 데이터를 분석해주세요. JSON 형식으로 응답하세요.\n\n"
                    "키: summary(데이터 요약), columns(컬럼 설명 리스트), "
                    "row_count(행 수), anomalies(이상치나 특이사항)\n\n"
                    f"CSV 데이터:\n{csv_content[:8000]}"  # Limit to avoid token overflow
                ),
            }
        ]
        return await self.chat(messages)

    async def analyze_image(self, image_data: bytes, file_type: str = "jpg") -> dict[str, Any]:
        """Analyze image using Qwen VLM."""
        b64 = base64.b64encode(image_data).decode()
        mime = f"image/{'jpeg' if file_type in ('jpg', 'jpeg') else file_type}"

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "이 이미지를 분석해주세요. JSON 형식으로 응답하세요.\n\n"
                            "키: description(이미지 설명), objects(감지된 객체 리스트), "
                            "text_content(이미지 내 텍스트, OCR), classification(이미지 분류)"
                        ),
                    },
                ],
            }
        ]
        return await self.chat(messages)
