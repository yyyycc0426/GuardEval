import sys
from pathlib import Path
import logging

from llm_security_platform.app.config import RAG_INTEGRATION_MODE

logger = logging.getLogger(__name__)


def _get_proj5_retrieve_fn():
    proj5_path = Path(__file__).resolve().parents[3] / "proj5"
    if proj5_path.is_dir():
        sys_path_str = str(proj5_path)
        if sys_path_str not in sys.path:
            sys.path.insert(0, sys_path_str)
        try:
            from knowledge_base import embedding_retrieve
            return embedding_retrieve
        except ImportError as exc:
            logger.warning(f"Could not import embedding_retrieve from proj5: {exc}")
    else:
        logger.warning(f"proj5 directory not found at: {proj5_path}")
    return None


def retrieved_documents_for_case(case: dict) -> list[dict]:
    """Return retrieved documents without mutating the benchmark case."""
    metadata = case.get("metadata", {})
    configured = metadata.get("retrieved_documents")
    if configured is not None:
        return [dict(document) for document in configured]

    if RAG_INTEGRATION_MODE == "real":
        retrieve_fn = _get_proj5_retrieve_fn()
        if retrieve_fn is not None:
            try:
                results = retrieve_fn(case["prompt"])
                documents = []
                for chunk in results:
                    documents.append({
                        "source": f"proj5:{chunk.get('chunk_id')}",
                        "permission": chunk.get("permission", "allowed"),
                        "content": chunk.get("stitched_text") or chunk.get("text", ""),
                    })
                return documents
            except Exception as e:
                logger.error(f"Failed to query real RAG from proj5: {e}")

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
