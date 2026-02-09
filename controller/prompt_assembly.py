from __future__ import annotations


def build_chat_messages(
    *,
    system_prompt_base: str,
    context_pack: str,
    controller_directive: str,
    instructions: str,
    anchor_block: str | None,
    recent_context: str,
    memory_pack: str | None,
    safe_prompt: str,
    max_chars: int,
) -> list[dict]:
    msgs = [
        {"role": "system", "content": (system_prompt_base or "")[:max_chars]},
        {"role": "system", "content": (context_pack or "")[:max_chars]},
        {"role": "system", "content": (controller_directive or "")[:max_chars]},
        {"role": "system", "content": (instructions or "")[:max_chars]},
    ]
    if anchor_block:
        msgs.append({"role": "system", "content": anchor_block[:max_chars]})
    msgs.append({"role": "system", "content": f"Recent channel context:\n{recent_context}"[:max_chars]})
    if memory_pack:
        msgs.append({"role": "system", "content": f"Relevant persistent memory:\n{memory_pack}"[:max_chars]})
    msgs.append({"role": "user", "content": (safe_prompt or "")[:max_chars]})
    return msgs
