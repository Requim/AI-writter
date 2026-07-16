class RetryableWorkflowError(RuntimeError):
    """A transient workflow failure that can resume from the latest checkpoint."""
