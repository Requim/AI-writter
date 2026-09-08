class RetryableWorkflowError(RuntimeError):
    """A transient workflow failure that can resume from the latest checkpoint."""


class WorkflowNodeTimeoutError(RetryableWorkflowError):
    """单个工作流节点超过截止时间，可从 checkpoint 重试。"""

    code = "workflow_node_timeout"

    def __init__(self, node: str, timeout_seconds: float) -> None:
        self.node = node
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"工作流节点 {node} 超过 {timeout_seconds:g} 秒未完成，请重试当前步骤"
        )


class StructuredOutputInvalidError(RetryableWorkflowError):
    """The model returned data that could not satisfy a structured contract."""


class WorkflowCheckpointUnavailableError(RuntimeError):
    """A retry was requested after the workflow no longer had a retry checkpoint."""


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
