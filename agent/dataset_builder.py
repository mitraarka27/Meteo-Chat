"""
dataset_builder.py
------------------
Utilities to generate training data for the tiny writer LLM:
- Calls MCP server (describe → resolve → plan → execute)
- Builds JSONL with {"system","input","output"} pairs.
"""
from typing import List, Dict, Any

def build_examples(mcp_base: str, places: List[str], bundles: List[List[str]], modes: List[str], outfile: str, max_examples: int = 1000) -> None:
    """
    Deterministic dataset builder (skeleton). See tools/data_generation for full script.
    """
    raise NotImplementedError("See tools/data_generation/make_dataset_full.py for a complete script.")