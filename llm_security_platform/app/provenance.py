import hashlib
import json
import subprocess


DEFAULT_VERSIONS = {
    "dataset_version": "attackset_v2",
    "policy_version": "baseline_v1",
    "detector_version": "rules_v1",
    "judge_prompt_version": "not_enabled",
    "rag_index_version": "not_enabled",
    "embedding_model_version": "not_enabled",
    "system_prompt_version": "enterprise_assistant_v1",
}


def get_git_commit():
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def build_run_metadata(request, provider):
    versions = {**DEFAULT_VERSIONS, **request.versions}
    config = {
        "provider": provider.name,
        "model": provider.model,
        "defense_policy": request.defense_policy,
        "case_ids": sorted(request.case_ids),
        "versions": versions,
        "model_config": request.inference_config,
        "defense_config": request.defense_config,
    }
    serialized = json.dumps(config, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return {
        **config,
        "code_commit_hash": get_git_commit(),
        "run_config_hash": hashlib.sha256(serialized).hexdigest(),
    }
