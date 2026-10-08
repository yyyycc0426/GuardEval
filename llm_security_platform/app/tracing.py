import contextvars
import logging

# ContextVar to hold the trace ID for the active coroutine / thread execution
current_trace_id = contextvars.ContextVar("current_trace_id", default="")


class TraceIdFilter(logging.Filter):
    """
    Injects %(trace_id)s field dynamically into all logging statements.
    """
    def filter(self, record):
        trace_id = current_trace_id.get()
        record.trace_id = f" [TraceID: {trace_id}]" if trace_id else ""
        return True


import json
import os

class JSONFormatter(logging.Formatter):
    """
    Structured JSON Formatter for LLM Security Platform.
    Allows easy collection of JSON events by log shippers (ELK/Loki).
    """
    def format(self, record):
        trace_id = current_trace_id.get()
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if trace_id:
            log_obj["trace_id"] = trace_id
            
        # Capture optional trace metadata
        for field in ["tenant_id", "user_id"]:
            if hasattr(record, field):
                log_obj[field] = getattr(record, field)
                
        if isinstance(record.msg, dict):
            log_obj.update(record.msg)
            
        return json.dumps(log_obj, ensure_ascii=False)


def setup_tracing_logging():
    """
    Configures Python logging to display Trace IDs automatically in logs if present.
    """
    root = logging.getLogger()
    log_filter = TraceIdFilter()

    json_enabled = os.getenv("JSON_LOGGING_ENABLED", "false").lower() == "true"

    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s]%(trace_id)s: %(message)s"
        )
        
    for handler in root.handlers:
        handler.addFilter(log_filter)
        if json_enabled:
            handler.setFormatter(JSONFormatter())
        else:
            formatter = handler.formatter
            if formatter:
                fmt = formatter._fmt
                if "%(trace_id)s" not in fmt:
                    # Insert trace_id right after levelname
                    if "[%(levelname)s]" in fmt:
                        new_fmt = fmt.replace("[%(levelname)s]", "[%(levelname)s]%(trace_id)s")
                    elif "%(levelname)s:" in fmt:
                        new_fmt = fmt.replace("%(levelname)s:", "%(levelname)s%(trace_id)s:")
                    else:
                        new_fmt = fmt.replace("%(message)s", "%(trace_id)s %(message)s")
                    formatter._fmt = new_fmt
