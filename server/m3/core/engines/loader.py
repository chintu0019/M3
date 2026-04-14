"""
M3 Engine Loader -- load compilation engine by name or custom path.
"""

import importlib.util
import logging

from m3.config import ProcessingSettings
from m3.core.engines.base import CompilationEngine
from m3.core.llm import LLMProvider

logger = logging.getLogger("m3.engine.loader")


def load_engine(settings: ProcessingSettings, llm: LLMProvider) -> CompilationEngine:
    """Load the compilation engine based on config.

    - engine: "basic" -> built-in BasicEngine
    - engine_path: "/path/to/engine.py" -> custom engine loaded dynamically
    """
    if settings.engine_path:
        logger.info(f"Loading custom engine from {settings.engine_path}")
        spec = importlib.util.spec_from_file_location("custom_engine", settings.engine_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Could not load engine from {settings.engine_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, CompilationEngine)
                and attr is not CompilationEngine
            ):
                logger.info(f"Found engine class: {attr_name}")
                return attr(llm)

        raise ValueError(f"No CompilationEngine subclass found in {settings.engine_path}")

    if settings.engine == "basic":
        from m3.core.engines.basic import BasicEngine

        return BasicEngine(llm)

    raise ValueError(f"Unknown engine: {settings.engine}")
