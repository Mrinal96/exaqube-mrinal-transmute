"""LLM client boundary. No fake conversion behavior is provided in this milestone."""

from app.config import Settings


class LLMNotConfiguredError(RuntimeError):
    pass


class LLMService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_available(self) -> bool:
        return self.settings.mock_llm or self.settings.llm_configured

    async def transform(self, *_: object, **__: object) -> None:
        raise NotImplementedError("Semantic document transformation is planned for a later milestone.")

