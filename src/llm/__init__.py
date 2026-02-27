"""LLM 统一抽象层 - 多后端支持 (OpenAI/DeepSeek/Gemini/Ollama)。"""

from src.llm.llm_client import LLMClient, LLMResponse, create_llm_client, is_llm_available

__all__ = ["LLMClient", "LLMResponse", "create_llm_client", "is_llm_available"]
