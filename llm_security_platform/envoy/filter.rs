use log::info;
use proxy_wasm::traits::*;
use proxy_wasm::types::*;
use std::collections::HashMap;

// Envoy WebAssembly HTTP filter performing real-time request pre-filtering.
// Compiles to wasm32-unknown-unknown target for sidecar proxy deployment.

#[no_mangle]
pub fn _start() {
    proxy_wasm::set_log_level(LogLevel::Info);
    proxy_wasm::set_http_context(|context_id, _| -> Box<dyn HttpContext> {
        Box::new(SecurityFilterContext {
            context_id,
            headers: HashMap::new(),
        })
    });
}

struct SecurityFilterContext {
    context_id: u32,
    headers: HashMap<String, String>,
}

impl Context for SecurityFilterContext {}

impl HttpContext for SecurityFilterContext {
    fn on_http_request_headers(&mut self, _num_headers: usize, _end_of_stream: bool) -> Action {
        info!("#{} processing HTTP request headers", self.context_id);

        // 1. Retrieve API authorization header
        if let Some(auth_header) = self.get_http_request_header("X-API-Key") {
            self.headers.insert("auth".to_string(), auth_header.clone());
        } else {
            // Reject unauthenticated requests immediately at the edge
            self.send_http_response(
                401,
                vec![("Content-Type", "application/json")],
                Some(b"{\"success\":false,\"message\":\"Unauthorized: Missing X-API-Key header\"}"),
            );
            return Action::Pause;
        }

        Action::Continue
    }

    fn on_http_request_body(&mut self, body_size: usize, _end_of_stream: bool) -> Action {
        if body_size == 0 {
            return Action::Continue;
        }

        // 2. Read request body bytes
        if let Some(body_bytes) = self.get_http_request_body(0, body_size) {
            let body_str = match std::str::from_utf8(&body_bytes) {
                Ok(s) => s,
                Err(_) => {
                    self.send_http_response(
                        400,
                        vec![("Content-Type", "application/json")],
                        Some(b"{\"success\":false,\"message\":\"Bad Request: Invalid UTF-8\"}"),
                    );
                    return Action::Pause;
                }
            };

            // 3. Scan for malicious injection payloads or base64 bypass patterns
            // Simulate Unicode normalization check and simple input sanitization
            let lower_body = body_str.to_lowercase();
            if lower_body.contains("ignore previous instructions")
                || lower_body.contains("ssapyb_dedocne")
                || lower_body.contains("injection_succeeded")
            {
                info!("Block malicious payload at edge proxy. context: {}", self.context_id);
                self.send_http_response(
                    403,
                    vec![("Content-Type", "application/json")],
                    Some(b"{\"success\":false,\"message\":\"Request blocked by Envoy Security Filter due to high-risk input content.\"}"),
                );
                return Action::Pause;
            }
        }

        Action::Continue
    }
}
