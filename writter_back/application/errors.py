class RetryableWorkflowError(RuntimeError):
    """A transient workflow failure that can resume from the latest checkpoint."""


class PlanningTemporarilyDisabledError(RuntimeError):
    """Schema 5 was disabled while a resumable workflow was in progress."""

    code = "planning_temporarily_disabled"


class QualityGateReviewRequired(RuntimeError):
    """直接重写无法安全自动通过质量门禁，需要调用方明确处理。"""


class WorkflowBusyError(RuntimeError):
    """小说已有互斥操作正在执行。"""


class StaleWorkflowDecisionError(RuntimeError):
    """用户提交的决定不属于当前等待审核的提案。"""

    code = "stale_workflow_decision"


class InvalidReviewDecisionError(ValueError):
    """用户提交的审核决定不符合公开协议。"""

    code = "invalid_workflow_decision"
