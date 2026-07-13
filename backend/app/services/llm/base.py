from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, system_prompt: str, user_content: str) -> str:
        """
        Sends the system and user prompts to the LLM and returns the response as a raw JSON string.
        Implementations should enforce JSON formatting.
        """
        pass
