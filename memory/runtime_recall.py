from __future__ import annotations


async def maybe_build_memory_pack(
    *,
    stage_at_least,
    infer_scope,
    recall_memory_func,
    format_memory_for_llm,
    safe_prompt: str,
    max_chars: int,
) -> tuple[list[dict], list[dict], list[int], str]:
    retrieved_memory_ids: list[int] = []
    events: list[dict] = []
    summaries: list[dict] = []
    memory_pack = ""

    if stage_at_least("M1"):
        scope = infer_scope(safe_prompt) if stage_at_least("M2") else "auto"
        events, summaries = await recall_memory_func(safe_prompt, scope=scope)
        retrieved_memory_ids = [int(e["id"]) for e in events if e.get("id") is not None]
        memory_pack = format_memory_for_llm(events, summaries, max_chars=max_chars)[:max_chars]

    return events, summaries, retrieved_memory_ids, memory_pack
