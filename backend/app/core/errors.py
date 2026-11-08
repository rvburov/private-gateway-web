class AppError(Exception):
    def __init__(self, status: int, code: str, *, retry_after: int | None = None) -> None:
        self.status = status
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)
