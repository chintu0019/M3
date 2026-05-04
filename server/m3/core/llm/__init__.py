"""M3 LLM provider package.

Re-exports the public surface so existing callers continue to import from
``m3.core.llm`` with no changes.  New code should import from the concrete
submodule (``m3.core.llm.anthropic`` etc.) where appropriate.
"""

from m3.core.llm.anthropic import (
    AnthropicProvider,
    OpenAICompatibleProvider,
    make_content_blocks,
)
from m3.core.llm.base import (
    EmbeddingProvider,
    LLMProvider,
    Message,
    Tool,
    ToolResult,
)
from m3.core.llm.embeddings import FastEmbedProvider
from m3.core.llm.local_agent import (
    KNOWN_AGENTS,
    LocalAgentProvider,
    detect_local_agents,
)
from m3.core.llm.ollama import OllamaProvider
from m3.core.llm.unconfigured import UnconfiguredProvider

__all__ = [
    "AnthropicProvider",
    "EmbeddingProvider",
    "FastEmbedProvider",
    "KNOWN_AGENTS",
    "LLMProvider",
    "LocalAgentProvider",
    "Message",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "Tool",
    "ToolResult",
    "UnconfiguredProvider",
    "detect_local_agents",
    "make_content_blocks",
]
