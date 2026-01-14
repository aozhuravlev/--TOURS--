"""
Text generator using DeepSeek API.

Generates and humanizes content for Instagram posts and stories.
Uses two-step process: generation -> humanization.
Prompts are loaded from external .txt files for easy editing.
"""

import logging
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"


@dataclass
class GeneratedText:
    """Result of text generation."""
    raw_text: str
    humanized_text: str
    content_type: str  # "story" or "post"
    topic: str
    subtopic: str
    success: bool
    error: Optional[str] = None


class TextGenerator:
    """
    Generates Instagram content using DeepSeek API.

    Two-step process:
    1. Generate initial text based on topic and facts
    2. Humanize to make it sound natural and engaging

    Prompts are loaded from .txt files in prompts_dir:
    - story_generator.txt
    - story_humanizer.txt
    - post_generator.txt
    - post_humanizer.txt
    """

    def __init__(
        self,
        api_key: str,
        prompts_dir: Path,
        model: str = "deepseek-chat",
        timeout: int = 60,
        max_retries: int = 3,
    ):
        """
        Initialize text generator.

        Args:
            api_key: DeepSeek API key
            prompts_dir: Directory containing prompt .txt files
            model: Model to use
            timeout: Request timeout in seconds
            max_retries: Number of retries on failure
        """
        self.api_key = api_key
        self.prompts_dir = Path(prompts_dir)
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

        logger.info(f"TextGenerator initialized, prompts dir: {self.prompts_dir}")

    def _load_prompt(self, name: str) -> str:
        """
        Load prompt from .txt file.

        Args:
            name: Prompt name without extension (e.g., "story_generator")

        Returns:
            Prompt content or empty string if not found
        """
        path = self.prompts_dir / f"{name}.txt"
        if path.exists():
            content = path.read_text(encoding="utf-8")
            logger.debug(f"Loaded prompt: {name} ({len(content)} chars)")
            return content
        else:
            logger.warning(f"Prompt file not found: {path}")
            return ""

    def generate_story(
        self,
        topic: str,
        subtopic: str,
        facts: str = "",
    ) -> GeneratedText:
        """
        Generate text for Instagram Story.

        Args:
            topic: Category name (e.g., "Грузинская кухня")
            subtopic: Specific subtopic (e.g., "Хачапури по-аджарски")
            facts: Optional facts from Perplexity to include

        Returns:
            GeneratedText with raw and humanized versions
        """
        return self._generate(
            content_type="story",
            topic=topic,
            subtopic=subtopic,
            facts=facts,
        )

    def generate_post(
        self,
        topic: str,
        subtopic: str,
        facts: str = "",
    ) -> GeneratedText:
        """
        Generate text for Instagram feed post.

        Args:
            topic: Category name
            subtopic: Specific subtopic
            facts: Optional facts to include

        Returns:
            GeneratedText with raw and humanized versions
        """
        return self._generate(
            content_type="post",
            topic=topic,
            subtopic=subtopic,
            facts=facts,
        )

    def _generate(
        self,
        content_type: str,
        topic: str,
        subtopic: str,
        facts: str,
    ) -> GeneratedText:
        """
        Internal generation method.

        Two-step process:
        1. Generate initial text using {content_type}_generator.txt
        2. Humanize using {content_type}_humanizer.txt
        """
        logger.info(f"Generating {content_type} for: {subtopic}")

        # Step 1: Generate raw text
        generator_prompt = self._load_prompt(f"{content_type}_generator")
        if not generator_prompt:
            return GeneratedText(
                raw_text="",
                humanized_text="",
                content_type=content_type,
                topic=topic,
                subtopic=subtopic,
                success=False,
                error=f"Prompt file not found: {content_type}_generator.txt",
            )

        raw_text = self._call_api(
            prompt=generator_prompt,
            topic=topic,
            subtopic=subtopic,
            facts=facts,
        )

        if not raw_text:
            return GeneratedText(
                raw_text="",
                humanized_text="",
                content_type=content_type,
                topic=topic,
                subtopic=subtopic,
                success=False,
                error="Failed to generate raw text",
            )

        logger.info(f"Raw text generated: {len(raw_text)} chars")

        # Step 2: Humanize
        humanizer_prompt = self._load_prompt(f"{content_type}_humanizer")
        if humanizer_prompt:
            humanized_text = self._call_api(
                prompt=humanizer_prompt,
                topic=topic,
                subtopic=subtopic,
                facts=facts,
                raw_text=raw_text,
            )

            # Use raw text if humanization fails
            if not humanized_text:
                humanized_text = raw_text
                logger.warning("Humanization failed, using raw text")
            else:
                logger.info(f"Humanized text: {len(humanized_text)} chars")
        else:
            humanized_text = raw_text
            logger.warning("No humanizer prompt, using raw text")

        return GeneratedText(
            raw_text=raw_text,
            humanized_text=humanized_text,
            content_type=content_type,
            topic=topic,
            subtopic=subtopic,
            success=True,
        )

    def _call_api(
        self,
        prompt: str,
        topic: str,
        subtopic: str,
        facts: str = "",
        raw_text: str = "",
    ) -> str:
        """
        Make API call to DeepSeek.

        Substitutes placeholders in prompt:
        - {topic} -> topic
        - {subtopic} -> subtopic
        - {facts} -> facts
        - {raw_text} -> raw_text

        Returns:
            Generated text or empty string on failure
        """
        # Substitute variables in prompt
        filled_prompt = prompt.format(
            topic=topic,
            subtopic=subtopic,
            facts=facts or "Нет дополнительных фактов",
            raw_text=raw_text,
        )

        for attempt in range(self.max_retries):
            try:
                response = self.client.post(
                    DEEPSEEK_API_URL,
                    json={
                        "model": self.model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Ты - копирайтер для туристического Instagram-аккаунта tours.batumi. "
                                           "Пишешь увлекательно, информативно, на русском языке. "
                                           "Твоя аудитория - русскоязычные туристы, планирующие посетить Батуми."
                            },
                            {
                                "role": "user",
                                "content": filled_prompt,
                            }
                        ],
                        "temperature": 0.7,
                        "max_tokens": 1500,
                    },
                )
                response.raise_for_status()

                data = response.json()
                content = data["choices"][0]["message"]["content"]

                return content.strip()

            except httpx.TimeoutException:
                logger.warning(f"Timeout on attempt {attempt + 1}/{self.max_retries}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)

            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error: {e.response.status_code} - {e.response.text[:200]}")
                return ""

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return ""

        return ""

    def extract_english_keywords(self, russian_text: str, max_keywords: int = 5) -> str:
        """
        Extract English keywords from Russian text for image search.

        Uses DeepSeek to translate and extract relevant search terms.

        Args:
            russian_text: Russian text to extract keywords from
            max_keywords: Maximum number of keywords to return

        Returns:
            Space-separated English keywords for image search
        """
        prompt = f"""Extract {max_keywords} most important visual keywords from this Russian text for image search.
Return ONLY English keywords separated by spaces, nothing else.
Focus on concrete visual objects (food, places, buildings, nature).
Skip abstract concepts and emotions.

Russian text: {russian_text}

English keywords:"""

        try:
            response = self.client.post(
                DEEPSEEK_API_URL,
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You extract English keywords for image search. "
                                       "Return only keywords, no explanations."
                        },
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 50,
                },
            )
            response.raise_for_status()

            keywords = response.json()["choices"][0]["message"]["content"].strip()
            # Clean up: remove punctuation, extra spaces
            keywords = ' '.join(keywords.replace(',', ' ').replace('.', ' ').split())

            logger.debug(f"Extracted English keywords: {keywords}")
            return keywords

        except Exception as e:
            logger.warning(f"Failed to extract keywords: {e}")
            return ""

    def close(self):
        """Close HTTP client."""
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
