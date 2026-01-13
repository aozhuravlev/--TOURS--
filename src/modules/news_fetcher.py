"""
News and facts fetcher using Perplexity API.

Searches for relevant, up-to-date information about Batumi and Georgia
to enrich generated content with actual facts.
"""

import logging
import time
from typing import Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"


@dataclass
class NewsResult:
    """Result from news/facts search."""
    query: str
    content: str
    sources: list[str]
    success: bool
    error: Optional[str] = None


class NewsFetcher:
    """
    Fetches relevant news and facts using Perplexity API.

    Uses Perplexity's search-augmented LLM to find current information
    about topics related to Batumi and Georgia.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "sonar",
        timeout: int = 30,
        max_retries: int = 3,
    ):
        """
        Initialize news fetcher.

        Args:
            api_key: Perplexity API key
            model: Model to use (sonar models have online search)
            timeout: Request timeout in seconds
            max_retries: Number of retries on failure
        """
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    def search(
        self,
        topic: str,
        subtopic: str,
        language: str = "Russian",
    ) -> NewsResult:
        """
        Search for relevant facts and news about a topic.

        Args:
            topic: Main topic category (e.g., "Грузинская кухня")
            subtopic: Specific subtopic (e.g., "Хачапури по-аджарски")
            language: Response language

        Returns:
            NewsResult with found information
        """
        query = self._build_query(topic, subtopic, language)

        logger.info(f"Searching for: {subtopic}")

        for attempt in range(self.max_retries):
            try:
                response = self._make_request(query)
                return response

            except httpx.TimeoutException:
                logger.warning(f"Timeout on attempt {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error: {e.response.status_code}")
                return NewsResult(
                    query=query,
                    content="",
                    sources=[],
                    success=False,
                    error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
                )

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return NewsResult(
                    query=query,
                    content="",
                    sources=[],
                    success=False,
                    error=str(e),
                )

        return NewsResult(
            query=query,
            content="",
            sources=[],
            success=False,
            error="Max retries exceeded",
        )

    def _build_query(self, topic: str, subtopic: str, language: str) -> str:
        """Build search query for Perplexity."""
        return f"""Найди актуальную информацию о теме "{subtopic}" в контексте Батуми и Грузии.

Тема относится к категории: {topic}

Требования:
- Ответь на русском языке
- Приведи 3-5 интересных фактов или актуальных новостей
- Включи практическую информацию для туристов (цены, адреса, советы) если применимо
- Если есть недавние изменения или новости - упомяни их
- Будь конкретным и информативным

Формат ответа: краткие факты в виде списка."""

    def _make_request(self, query: str) -> NewsResult:
        """Make API request to Perplexity."""
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Ты - помощник для создания контента о Батуми и Грузии. "
                               "Предоставляй точную, актуальную информацию с фокусом на туризм."
                },
                {
                    "role": "user",
                    "content": query,
                }
            ],
            "temperature": 0.2,
            "max_tokens": 1000,
        }

        response = self.client.post(PERPLEXITY_API_URL, json=payload)
        response.raise_for_status()

        data = response.json()

        # Extract content
        content = ""
        if "choices" in data and len(data["choices"]) > 0:
            content = data["choices"][0].get("message", {}).get("content", "")

        # Extract sources/citations if available
        sources = []
        if "citations" in data:
            sources = data["citations"]

        logger.info(f"Perplexity response: {len(content)} chars, {len(sources)} sources")

        return NewsResult(
            query=query,
            content=content,
            sources=sources,
            success=True,
        )

    def search_simple(self, query: str) -> str:
        """
        Simple search that returns just the content string.

        Args:
            query: Free-form search query

        Returns:
            Response content or empty string on failure
        """
        result = self._make_request(query)
        return result.content if result.success else ""

    def close(self):
        """Close HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
