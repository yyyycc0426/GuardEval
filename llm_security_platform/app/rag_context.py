def retrieved_documents_for_case(case: dict) -> list[dict]:
    """Return retrieved documents without mutating the benchmark case."""
    metadata = case.get("metadata", {})
    configured = metadata.get("retrieved_documents")
    if configured is not None:
        return [dict(document) for document in configured]

    method = metadata.get("attack_method")
    if method in {"indirect_injection", "rag_malicious_document"}:
        return [
            {
                "source": f"benchmark:{case['case_id']}",
                "permission": "allowed",
                "content": case["prompt"],
            }
        ]
    return []


def render_untrusted_documents(documents: list[dict]) -> str:
    """Render the raw retrieval result used when no RAG defense is enabled."""
    if not documents:
        return ""
    rendered = ["[Retrieved Documents - Untrusted]"]
    for document in documents:
        source = str(document.get("source", "unknown"))
        permission = str(document.get("permission", "unknown"))
        content = str(document.get("content", ""))
        rendered.append(
            f'<doc source="{source}" permission="{permission}">\n{content}\n</doc>'
        )
    return "\n".join(rendered)
