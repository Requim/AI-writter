class RetryableWorkflowError(RuntimeError):
    """A transient workflow failure that can resume from the latest checkpoint."""


class WorkflowBusyError(RuntimeError):
    """小说已有互斥操作正在执行。"""
