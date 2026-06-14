from llm_security_platform.app.production_store import set_task_id


def dispatch_run(run_id):
    from llm_security_platform.app.tasks import execute_evaluation_run

    result = execute_evaluation_run.delay(run_id)
    set_task_id(run_id, result.id)
    return result.id
