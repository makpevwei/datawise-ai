class ParsingError(Exception):
    """Raised when a file or worksheet cannot be parsed into a usable table.

    Carries a human-readable message only -- callers turn this into a
    per-file UploadError rather than letting it propagate into a 500.
    """
