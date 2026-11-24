from daemon_tasks.base import ScheduledTask
from daemon_tasks.contact_identity_refresh import ContactIdentityRefreshTask
from daemon_tasks.exact_contact_drift import ExactContactDriftTask


def get_task_registry() -> dict[str, ScheduledTask]:
    tasks = [ContactIdentityRefreshTask(), ExactContactDriftTask()]
    return {task.name: task for task in tasks}
