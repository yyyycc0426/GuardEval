import os
from pathlib import Path


KNOWN_ENV_VARS = {
    "LLM_SECURITY_ENV",
    "LLM_SECURITY_API_KEY",
    "LLM_SECURITY_API_KEYS_JSON",
    "LLM_SECURITY_DATABASE_URL",
    "LLM_SECURITY_DATABASE_PATH",
    "LLM_SECURITY_REDIS_URL",
    "LLM_SECURITY_CELERY_EAGER",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "LLM_SECURITY_MODEL_BASE_URL",
    "LLM_SECURITY_MODEL_API_KEY",
    "LLM_SECURITY_MODEL_NAME",
    "LLM_SECURITY_RAG_MODE",
    "SILICONFLOW_API_KEY",
    "SILICONFLOW_BASE_URL",
    "LLM_SECURITY_STALE_RUN_TIMEOUT_SECONDS",
    "LLM_SECURITY_PRE_ALLOCATED_TOKENS"
}

TOML_MAPPINGS = {
    ("core", "env"): "LLM_SECURITY_ENV",
    ("core", "api_key"): "LLM_SECURITY_API_KEY",
    ("core", "api_keys_json"): "LLM_SECURITY_API_KEYS_JSON",
    ("core", "database_url"): "LLM_SECURITY_DATABASE_URL",
    ("core", "database_path"): "LLM_SECURITY_DATABASE_PATH",
    ("core", "redis_url"): "LLM_SECURITY_REDIS_URL",
    ("core", "celery_eager"): "LLM_SECURITY_CELERY_EAGER",
    ("model", "ollama_base_url"): "OLLAMA_BASE_URL",
    ("model", "ollama_host"): "OLLAMA_BASE_URL",
    ("model", "ollama_model"): "OLLAMA_MODEL",
    ("model", "openai_compatible_base_url"): "LLM_SECURITY_MODEL_BASE_URL",
    ("model", "openai_compatible_api_key"): "LLM_SECURITY_MODEL_API_KEY",
    ("model", "openai_compatible_model"): "LLM_SECURITY_MODEL_NAME",
    ("model", "rag_integration_mode"): "LLM_SECURITY_RAG_MODE",
    ("model", "siliconflow_api_key"): "SILICONFLOW_API_KEY",
    ("model", "siliconflow_base_url"): "SILICONFLOW_BASE_URL",
    ("guardrails", "stale_run_timeout_seconds"): "LLM_SECURITY_STALE_RUN_TIMEOUT_SECONDS",
    ("guardrails", "pre_allocated_tokens"): "LLM_SECURITY_PRE_ALLOCATED_TOKENS",
}

def _parse_toml_file(path: Path) -> dict[str, str]:
    import tomllib
    resolved = {}
    if not path.is_file():
        return resolved
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return resolved

    # Flat keys
    for k, v in data.items():
        if isinstance(v, (str, int, float, bool)):
            name = str(k).upper()
            if name in KNOWN_ENV_VARS:
                resolved[name] = str(v)
            for env_name in KNOWN_ENV_VARS:
                if env_name.lower() == str(k).lower():
                    resolved[env_name] = str(v)

    # Section keys
    for section_name in ("core", "model", "guardrails"):
        section = data.get(section_name)
        if isinstance(section, dict):
            for k, v in section.items():
                mapping_key = (section_name, str(k).lower())
                env_name = TOML_MAPPINGS.get(mapping_key)
                if env_name:
                    resolved[env_name] = str(v)
                name = str(k).upper()
                if name in KNOWN_ENV_VARS:
                    resolved[name] = str(v)
    return resolved

def _parse_dotenv() -> dict[str, str]:
    import sys
    resolved = {}
    # Skip .env only when actually running tests. NB: "unittest" is imported
    # transitively by some libraries (sklearn/torch), so checking sys.modules
    # for it wrongly skips .env on normal CLI runs — detect the test *runner*
    # instead (pytest, or `python -m unittest`).
    running_unittest = "unittest" in (sys.argv[0] if sys.argv else "")
    if os.getenv("PYTEST_CURRENT_TEST") or "pytest" in sys.modules or running_unittest:
        return resolved
    base_dir = Path(__file__).resolve().parents[2]
    env_path = base_dir / ".env"
    if not env_path.is_file():
        env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.is_file():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    k, sep, v = line.partition("=")
                    if sep:
                        k = k.strip()
                        v = v.strip().partition("#")[0].strip().strip("'\"")
                        if k:
                            resolved[k] = v
        except Exception:
            pass
    return resolved

def _load_multi_tier_config():
    # Save original system env vars
    original_system_env = {k: v for k, v in os.environ.items()}
    
    # 1. Global TOML
    global_path = Path("~/.llm_security/config.toml").expanduser()
    global_toml = _parse_toml_file(global_path)
    
    # 2. Local TOML
    local_path = Path(".llm_security/config.toml")
    local_toml = _parse_toml_file(local_path)
    
    # 3. .env file
    dotenv_vals = _parse_dotenv()
    
    # Merge priorities: Global TOML -> Local TOML -> .env -> Original System Env
    merged = {}
    merged.update(global_toml)
    merged.update(local_toml)
    merged.update(dotenv_vals)
    merged.update(original_system_env)
    
    # Write back to os.environ
    for k, v in merged.items():
        os.environ[k] = v

_load_multi_tier_config()


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
import sys
is_testing = "pytest" in sys.modules or "unittest" in sys.modules
LLM_SECURITY_ENV = os.getenv("LLM_SECURITY_ENV", "development").strip().lower()
is_prod = (LLM_SECURITY_ENV == "production")
API_KEY = os.getenv("LLM_SECURITY_API_KEY")
if is_prod:
    if not API_KEY:
        raise ValueError(
            "CRITICAL SECURITY ERROR: LLM_SECURITY_API_KEY environment variable is required and must be configured in production."
        )
    if API_KEY == "dev-security-key":
        raise ValueError(
            "CRITICAL SECURITY ERROR: Default API key 'dev-security-key' cannot be used in production environments. "
            "Please configure a unique secure key in the LLM_SECURITY_API_KEY environment variable."
        )
else:
    if not API_KEY:
        API_KEY = "dev-security-key"
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
RAG_INTEGRATION_MODE = os.getenv("LLM_SECURITY_RAG_MODE", "fallback").lower()

SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")

# Google Gemini. Two auth modes:
#  - Vertex AI via ADC (no key): set GOOGLE_GENAI_USE_VERTEXAI=true + project.
#  - Developer API via AIza key: set GEMINI_API_KEY / GOOGLE_API_KEY.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
GEMINI_USE_VERTEX = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "false").lower() == "true"
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL", "gemini-2.5-flash" if GEMINI_USE_VERTEX else "gemini-2.0-flash"
)

STALE_RUN_TIMEOUT_SECONDS = int(os.getenv("LLM_SECURITY_STALE_RUN_TIMEOUT_SECONDS", "900"))
PRE_ALLOCATED_TOKENS = int(os.getenv("LLM_SECURITY_PRE_ALLOCATED_TOKENS", "4096"))
