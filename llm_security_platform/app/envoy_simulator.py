import base64
import re
import unicodedata
from typing import Dict, Tuple

class EnvoyFilterSimulator:
    """
    Simulates a sidecar Envoy WebAssembly filter performing edge pre-filtering.
    It inspects request headers and raw payloads for:
    1. Authentication boundary: Missing or empty X-API-Key -> HTTP 401
    2. Input obfuscation bypass: Base64 payload decoding.
    3. Character homoglyph bypass: Unicode normalization (NFKC) and character replacement.
    4. Attack payloads: Rejects blocklisted patterns -> HTTP 403
    """
    def __init__(self, block_patterns: list = None):
        self.block_patterns = block_patterns or [
            "ignore previous instructions",
            "jailbreak_enabled",
            "injection_succeeded",
            "ssapyb_dedocne"
        ]

    def _normalize_homoglyphs(self, text: str) -> str:
        mapping = {
            'і': 'i', 'о': 'o', 'с': 'c', 'е': 'e', 'р': 'p', 'ѕ': 's', 'у': 'y', 'а': 'a', 'х': 'x',
            'ν': 'n', 'т': 't', 'ο': 'o', 'ј': 'j',
        }
        return "".join(mapping.get(char, char) for char in text)

    def process_request(self, headers: Dict[str, str], body: str) -> Tuple[int, str]:
        """
        Processes incoming request in the sidecar proxy.
        Returns: Tuple[status_code, body_string]
        """
        # 1. Header Validation: Auth Check
        api_key = headers.get("X-API-Key") or headers.get("x-api-key")
        if not api_key:
            return 401, "{\"success\":false,\"message\":\"Unauthorized: Missing X-API-Key header\"}"

        # 2. De-obfuscation: Detect base64 strings inside request and decode them
        cleaned_body = body
        # Simple regex to search for base64 patterns (>=8 characters)
        b64_matches = re.findall(r'[a-zA-Z0-9+/]{8,}={0,2}', body)
        for match in b64_matches:
            try:
                decoded = base64.b64decode(match.encode()).decode("utf-8")
                # If it contains readable ascii/utf-8, replace or append it for inspection
                if all(ord(char) < 128 for char in decoded) and len(decoded.strip()) > 3:
                    cleaned_body += f"\n[DECODED_B64] {decoded}"
            except Exception:
                pass

        # 3. Unicode normalization (NFKC) and homoglyph mapping
        normalized_body = unicodedata.normalize("NFKC", cleaned_body).lower()
        normalized_body = self._normalize_homoglyphs(normalized_body)

        # 4. Pattern inspection & edge blocking
        for pattern in self.block_patterns:
            if pattern.lower() in normalized_body:
                return 403, "{\"success\":false,\"message\":\"Request blocked by Envoy Security Filter due to high-risk input content.\"}"

        # Success - continue routing to main container
        return 200, body
