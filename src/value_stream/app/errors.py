"""Application errors shared by routes, storage, and the service gateway."""


class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, details=None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = (
            code,
            message,
            status,
            details,
        )

    def body(self):
        return {"code": self.code, "message": self.message, "details": self.details}
