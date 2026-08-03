class RetryableWorkflowError(RuntimeError):
    """A transient workflow failure that can resume from the latest checkpoint."""


class QualityGateReviewRequired(RuntimeError):
    """直接重写无法安全自动通过质量门禁，需要调用方明确处理。"""


class WorkflowBusyError(RuntimeError):
    """小说已有互斥操作正在执行。"""
