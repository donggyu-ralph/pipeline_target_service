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
    
    def __init__(self, message, analysis_step=None):
        super().__init__(message)
        self.analysis_step = analysis_step

    def __str__(self):
        if self.analysis_step:
            return f"{self.args[0]} (Step: {self.analysis_step})"
        return self.args[0]


class StorageError(PipelineError):
    """Raised when result storage fails."""
    pass