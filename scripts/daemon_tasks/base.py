from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal, Protocol


TaskStatus = Literal["success", "error", "skipped"]


@dataclass(frozen=True)
class TaskResult:
    status: TaskStatus
    result: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    notes: str | None = None

    @classmethod
    def success(cls, result: dict[str, Any], notes: str | None = None) -> "TaskResult":
        return cls(status="success", result=result, notes=notes)

    @classmethod
    def error(cls, error_message: str, result: dict[str, Any] | None = None, notes: str | None = None) -> "TaskResult":
        return cls(status="error", result=result or {}, error_message=error_message, notes=notes)

    @classmethod
    def skipped(cls, notes: str, result: dict[str, Any] | None = None) -> "TaskResult":
        return cls(status="skipped", result=result or {}, notes=notes)


class ScheduledTask(Protocol):
    name: str
    interval: timedelta
    error_retry_interval: timedelta

    def run(self, tenant_id: int) -> TaskResult:
        ...
