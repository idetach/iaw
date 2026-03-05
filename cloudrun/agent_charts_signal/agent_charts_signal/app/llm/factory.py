from __future__ import annotations

from .claude import ClaudeVisionProvider
from ..config import Settings


def build_provider(
    settings: Settings,
    provider_override: str | None = None,
    model_pass1_override: str | None = None,
    model_pass2_override: str | None = None,
):
    p = (provider_override or settings.vision_provider).lower().strip()
    if p == "claude":
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for VISION_PROVIDER=claude")
        return ClaudeVisionProvider(
            api_key=settings.anthropic_api_key,
            model_pass1=model_pass1_override or settings.claude_model_pass1,
            model_pass2=model_pass2_override or settings.claude_model_pass2,
            model_fallbacks=[m.strip() for m in settings.claude_model_fallbacks.split(",") if m.strip()],
            max_leverage=settings.max_leverage,
            max_margin_percent=settings.max_margin_percent,
        )
    if p == "openai":
        from .openai_provider import OpenAIVisionProvider

        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for VISION_PROVIDER=openai")
        return OpenAIVisionProvider(
            api_key=settings.openai_api_key,
            model_pass1=model_pass1_override or settings.openai_model_pass1,
            model_pass2=model_pass2_override or settings.openai_model_pass2,
            model_fallbacks=[m.strip() for m in settings.openai_model_fallbacks.split(",") if m.strip()],
            max_leverage=settings.max_leverage,
            max_margin_percent=settings.max_margin_percent,
        )
    if p == "gemini":
        from .gemini_provider import GeminiVisionProvider

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required for VISION_PROVIDER=gemini")
        return GeminiVisionProvider(
            api_key=settings.gemini_api_key,
            model_pass1=model_pass1_override or settings.gemini_model_pass1,
            model_pass2=model_pass2_override or settings.gemini_model_pass2,
            model_fallbacks=[m.strip() for m in settings.gemini_model_fallbacks.split(",") if m.strip()],
            max_leverage=settings.max_leverage,
            max_margin_percent=settings.max_margin_percent,
        )
    raise ValueError("VISION_PROVIDER must be one of: claude, openai, gemini")
