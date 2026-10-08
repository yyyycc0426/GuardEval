from llm_security_platform.app.production_store import set_task_id


def dispatch_run(run_id, tenant_id="default", trace_id=None):
    from llm_security_platform.app.task_queue import task_queue
    return task_queue.enqueue(run_id, tenant_id=tenant_id, trace_id=trace_id)

