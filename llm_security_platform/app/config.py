import os
from pathlib import Path


def normalize_http_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized.startswith(("http://", "https://")):
        normalized = f"http://{normalized}"
    return normalized


BASE_DIR = Path(__file__).resolve().parents[1]
DATABASE_PATH = Path(os.getenv("LLM_SECURITY_DATABASE_PATH", BASE_DIR / "security_eval.db"))
DATABASE_URL = os.getenv(
    "LLM_SECURITY_DATABASE_URL",
    f"sqlite:///{(BASE_DIR / 'stage_five.db').as_posix()}",
)
API_KEY = os.getenv("LLM_SECURITY_API_KEY", "dev-security-key")
API_KEYS_JSON = os.getenv("LLM_SECURITY_API_KEYS_JSON", "")
REDIS_URL = os.getenv("LLM_SECURITY_REDIS_URL", "redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = os.getenv("LLM_SECURITY_CELERY_EAGER", "false").lower() == "true"
OLLAMA_BASE_URL = normalize_http_base_url(
    os.getenv("OLLAMA_BASE_URL")
    or os.getenv("OLLAMA_HOST")
    or "http://127.0.0.1:11434"
)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OPENAI_COMPATIBLE_BASE_URL = os.getenv("LLM_SECURITY_MODEL_BASE_URL", "https://api.deepseek.com")
OPENAI_COMPATIBLE_API_KEY = os.getenv("LLM_SECURITY_MODEL_API_KEY", "")
OPENAI_COMPATIBLE_MODEL = os.getenv("LLM_SECURITY_MODEL_NAME", "deepseek-chat")
