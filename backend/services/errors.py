"""Expected failures that the API translates into response statuses."""


class InvalidCredentials(ValueError):
    pass


class AccessDenied(ValueError):
    pass


class UploadSizeError(ValueError):
    pass


class ConflictError(ValueError):
    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details
