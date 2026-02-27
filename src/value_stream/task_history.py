class TaskHistory():
    """Tracks task progress through a simulated workflow"""

    def __init__(self) -> None:
        self.dev_start_t: float | None = None
        self.dev_end_t: float | None = None
        self.delivery_start_t: float | None = None
        self.delivery_end_t: float | None = None
