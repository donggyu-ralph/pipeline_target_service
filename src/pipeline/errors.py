"""Pipeline custom exceptions."""


class PipelineError(Exception):
    """Base exception for pipeline errors."""
    pass


class FileTooLargeError(PipelineError):
    """Raised when uploaded file exceeds size limit."""
    pass


class UnsupportedFormatError(PipelineError):
    """Raised when file format is not supported."""
    pass


class PreprocessingError(PipelineError):
    """Raised when file preprocessing fails."""
    pass


class AnalysisError(PipelineError):
    """Raised when Qwen analysis fails."""
    pass


class StorageError(PipelineError):
    """Raised when result storage fails."""
    pass
