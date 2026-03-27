"""LLM config utilities for per-stage model routing.

The novel module's ``LLMConfig`` defines per-stage model names (e.g.
``outline_generation``, ``scene_writing``).  The helper in this module
extracts the correct model for a given pipeline stage and returns a
clean config dict suitable for ``create_llm_client``.
"""

from __future__ import annotations

# All known stage keys defined in src/novel/config.py LLMConfig
_STAGE_KEYS = frozenset({
    "outline_generation",
    "character_design",
    "scene_writing",
    "quality_review",
    "consistency_check",
    "style_rewrite",
})


def get_stage_llm_config(state: dict, stage_key: str) -> dict:
    """Build LLM config with a stage-specific model override.

    Reads ``state["config"]["llm"]`` (a dict produced by
    ``NovelConfig.model_dump()``), pulls out the model name for
    *stage_key*, strips all stage keys so they don't confuse
    ``create_llm_client``, and sets ``model`` to the stage value.

    If the stage key is missing or its value is falsy, the returned dict
    simply omits ``model`` so that ``create_llm_client`` falls back to
    its default auto-detection behaviour.

    Args:
        state: The novel state dict (must contain ``config.llm``).
        stage_key: One of ``'outline_generation'``, ``'character_design'``,
            ``'scene_writing'``, ``'quality_review'``,
            ``'consistency_check'``, ``'style_rewrite'``.

    Returns:
        A **new** dict safe to pass to ``create_llm_client``.
    """
    config = state.get("config") or {}
    llm_cfg = dict(config.get("llm") or {})

    # Extract the stage-specific model name before stripping
    model = llm_cfg.get(stage_key)

    # Remove all stage keys — they are not recognised by create_llm_client
    for key in _STAGE_KEYS:
        llm_cfg.pop(key, None)

    if model:
        llm_cfg["model"] = model

    return llm_cfg
