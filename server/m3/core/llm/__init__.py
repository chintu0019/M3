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
from m3.core.llm.factories import (
    create_embedding_provider,
    create_llm_provider,
)

__all__ = [
    "AnthropicProvider",
    "OpenAICompatibleProvider",
    "EmbeddingProvider",
    "FastEmbedProvider",
    "LLMProvider",
    "Message",
    "Tool",
    "ToolResult",
    "create_embedding_provider",
    "create_llm_provider",
    "make_content_blocks",
]
