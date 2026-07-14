"""TokenJuice Plugin — transparent tool-output compression for Hermes Agent.

Registers a ``transform_tool_result`` hook that applies 10 deterministic
text-compression rules to every tool result before it enters the LLM context.
Saves token budget on every query. Zero LLM calls — pure text processing.

Toggle per-god via config:
  plugins:
    tokenjuice:
      enabled: true          # master switch
      max_output_chars: 8000 # cap total result size (default 8000)
"""

from __future__ import annotations

import logging

logger = logging.getLogger("tokenjuice_plugin")


def register(ctx):
    """Plugin entry point — register the transform_tool_result hook."""
    from .compress import _compress_tool_result

    ctx.register_hook("transform_tool_result", _compress_tool_result)
    logger.info("TokenJuice plugin: registered transform_tool_result hook (10 rules)")
