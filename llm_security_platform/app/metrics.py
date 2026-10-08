import threading
from collections import defaultdict
from sqlalchemy import select
from llm_security_platform.app.production_models import AsyncRun
from llm_security_platform.app.production_store import session_scope, build_async_report


class MetricsStore:
    def __init__(self):
        self.lock = threading.Lock()
        # key: (method, path, status_code) -> count
        self.http_requests = defaultdict(int)
        # key: (method, path, status_code) -> sum of duration_seconds
        self.http_latency_sum = defaultdict(float)
        # key: (tenant_id, provider, model, token_type) -> count
        self.tenant_token_usage = defaultdict(int)
        
    def record_request(self, method: str, path: str, status_code: int, duration: float):
        with self.lock:
            key = (method, path, status_code)
            self.http_requests[key] += 1
            self.http_latency_sum[key] += duration

    def record_tenant_tokens(self, tenant_id: str, provider: str, model: str, token_type: str, count: int):
        with self.lock:
            key = (tenant_id, provider, model, token_type)
            self.tenant_token_usage[key] += count


GLOBAL_METRICS = MetricsStore()


def get_latest_completed_run_report():
    try:
        with session_scope() as session:
            run = session.scalars(
                select(AsyncRun)
                .where(AsyncRun.status == "COMPLETED")
                .order_by(AsyncRun.completed_at.desc())
                .limit(1)
            ).first()
            if run:
                return build_async_report(run.id)
    except Exception:
        pass
    return None


def generate_prometheus_exposition():
    lines = []
    
    # 1. HTTP request metrics
    lines.append("# HELP http_requests_total Total number of HTTP requests.")
    lines.append("# TYPE http_requests_total counter")
    with GLOBAL_METRICS.lock:
        for (method, path, status), count in GLOBAL_METRICS.http_requests.items():
            lines.append(f'http_requests_total{{method="{method}",path="{path}",status="{status}"}} {count}')
            
    lines.append("# HELP http_request_duration_seconds_sum Total duration of HTTP requests in seconds.")
    lines.append("# TYPE http_request_duration_seconds_sum counter")
    with GLOBAL_METRICS.lock:
        for (method, path, status), lat_sum in GLOBAL_METRICS.http_latency_sum.items():
            lines.append(f'http_request_duration_seconds_sum{{method="{method}",path="{path}",status="{status}"}} {lat_sum:.6f}')
            
    # 2. Security Evaluation metrics (from latest completed run)
    report = get_latest_completed_run_report()
    
    lines.append("# HELP raw_model_compromise_rate The raw model compromise rate of the latest completed evaluation run.")
    lines.append("# TYPE raw_model_compromise_rate gauge")
    val = report.get("raw_model_compromise_rate", 0.0) if report else 0.0
    lines.append(f"raw_model_compromise_rate {val}")
    
    lines.append("# HELP delivered_attack_success_rate The delivered attack success rate of the latest completed evaluation run.")
    lines.append("# TYPE delivered_attack_success_rate gauge")
    val = report.get("delivered_attack_success_rate", 0.0) if report else 0.0
    lines.append(f"delivered_attack_success_rate {val}")
    
    lines.append("# HELP false_positive_rate The false positive rate (benign block rate) of the latest completed evaluation run.")
    lines.append("# TYPE false_positive_rate gauge")
    val = report.get("false_positive_rate", 0.0) if report else 0.0
    lines.append(f"false_positive_rate {val}")
    
    # 3. Human review metrics
    from llm_security_platform.app import db
    try:
        rev = db.human_review_metrics(tenant_id="default")
    except Exception:
        rev = {}
    
    lines.append("# HELP completed_reviews_total Total number of completed human reviews.")
    lines.append("# TYPE completed_reviews_total counter")
    lines.append(f"completed_reviews_total {rev.get('completed_reviews', 0)}")
    
    lines.append("# HELP judge_human_asr_agreement Judge and human agreement on attack success.")
    lines.append("# TYPE judge_human_asr_agreement gauge")
    lines.append(f"judge_human_asr_agreement {rev.get('judge_human_attack_success_agreement', 0.0)}")
    
    lines.append("# HELP judge_human_outcome_agreement Judge and human agreement on outcome labels.")
    lines.append("# TYPE judge_human_outcome_agreement gauge")
    lines.append(f"judge_human_outcome_agreement {rev.get('judge_human_outcome_agreement', 0.0)}")
    
    lines.append("# HELP judge_human_asr_conflicts_total Number of conflicts between judge and human on attack success.")
    lines.append("# TYPE judge_human_asr_conflicts_total counter")
    lines.append(f"judge_human_asr_conflicts_total {rev.get('attack_success_conflicts', 0)}")
    
    lines.append("# HELP judge_human_outcome_conflicts_total Number of conflicts between judge and human on outcome labels.")
    lines.append("# TYPE judge_human_outcome_conflicts_total counter")
    lines.append(f"judge_human_outcome_conflicts_total {rev.get('outcome_conflicts', 0)}")
    
    # 4. SaaS Tenant Token Usage Metrics
    lines.append("# HELP tenant_token_usage_total Total model tokens consumed by SaaS tenant.")
    lines.append("# TYPE tenant_token_usage_total counter")
    with GLOBAL_METRICS.lock:
        for (tenant, prov, mdl, ttype), count in GLOBAL_METRICS.tenant_token_usage.items():
            lines.append(f'tenant_token_usage_total{{tenant_id="{tenant}",provider="{prov}",model="{mdl}",token_type="{ttype}"}} {count}')
            
    return "\n".join(lines) + "\n"
