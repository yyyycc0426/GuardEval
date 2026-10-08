import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from llm_security_platform.app import config


class ConfigMergingTests(unittest.TestCase):
    def setUp(self):
        # Save a backup of the environment to avoid polluting other tests
        self._env_backup = dict(os.environ)
        # Clear out our known environment variables for isolated testing
        for k in config.KNOWN_ENV_VARS:
            os.environ.pop(k, None)

    def tearDown(self):
        # Restore the environment backup
        os.environ.clear()
        os.environ.update(self._env_backup)

    def test_parse_toml_file_flat_and_nested(self):
        # Create a temporary TOML file
        with tempfile.TemporaryDirectory() as tmpdir:
            toml_path = Path(tmpdir) / "config.toml"
            toml_content = """
            LLM_SECURITY_ENV = "staging"
            
            [core]
            api_key = "global-api-key-toml"
            database_url = "sqlite:///global_test.db"
            
            [model]
            ollama_model = "llama3"
            
            [guardrails]
            pre_allocated_tokens = 2048
            """
            toml_path.write_text(toml_content, encoding="utf-8")
            
            parsed = config._parse_toml_file(toml_path)
            
            self.assertEqual(parsed.get("LLM_SECURITY_ENV"), "staging")
            self.assertEqual(parsed.get("LLM_SECURITY_API_KEY"), "global-api-key-toml")
            self.assertEqual(parsed.get("LLM_SECURITY_DATABASE_URL"), "sqlite:///global_test.db")
            self.assertEqual(parsed.get("OLLAMA_MODEL"), "llama3")
            self.assertEqual(parsed.get("LLM_SECURITY_PRE_ALLOCATED_TOKENS"), "2048")

    def test_load_multi_tier_config_priority(self):
        # We will mock the parser functions to return specific dicts
        # Priority order (lowest to highest): Global TOML -> Local TOML -> .env -> Original System Env
        
        global_mock = {
            "LLM_SECURITY_ENV": "global-env",
            "LLM_SECURITY_API_KEY": "global-key",
            "OLLAMA_MODEL": "global-model"
        }
        local_mock = {
            "LLM_SECURITY_ENV": "local-env",
            "LLM_SECURITY_API_KEY": "local-key"
        }
        dotenv_mock = {
            "LLM_SECURITY_ENV": "dotenv-env"
        }
        
        # System env variables (highest priority)
        os.environ["LLM_SECURITY_ENV"] = "system-env"
        
        with patch("llm_security_platform.app.config._parse_toml_file") as mock_parse_toml, \
             patch("llm_security_platform.app.config._parse_dotenv") as mock_parse_dotenv:
            
            # Setup mock returns based on file path checks
            def side_effect_toml(path):
                if "local" in str(path) or ".llm_security" in str(path) and not path.is_absolute():
                    return local_mock
                return global_mock
            
            mock_parse_toml.side_effect = side_effect_toml
            mock_parse_dotenv.return_value = dotenv_mock
            
            # Execute configuration merge
            config._load_multi_tier_config()
            
            # Asserts:
            # 1. System environment variable should override everything
            self.assertEqual(os.getenv("LLM_SECURITY_ENV"), "system-env")
            # 2. Dotenv overrides local and global TOML
            # Note: since LLM_SECURITY_ENV was already set in system env, we check the priority logic
            # by looking at OLLAMA_MODEL (only in global) and LLM_SECURITY_API_KEY (in local & global, local overrides)
            self.assertEqual(os.getenv("LLM_SECURITY_API_KEY"), "local-key")
            self.assertEqual(os.getenv("OLLAMA_MODEL"), "global-model")


if __name__ == "__main__":
    unittest.main()
