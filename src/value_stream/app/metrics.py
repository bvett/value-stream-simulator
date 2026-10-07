"""Explicit display measures for the existing simulation telemetry."""

from collections import defaultdict

from value_stream.service.schemas import ResultData

from .errors import AppError
from .schemas import PlotData, StageLoss, ResourceActivity, Backlog

STAGES = {
    "pending": "Waiting for development",
    "development": "Development",
    "dev_complete": "Waiting for QA",
    "qa_testing": "QA testing",
    "qa_complete": "Waiting for deployment",
    "deployment": "Deployment",
    "delivery": "Delivery",
    "support_pending": "Support waiting",
    "support_complete": "Support complete",
}
CATEGORIES = ("idle_t", "success_t", "failure_t", "interruption_t")


def loss_percent(initial, delivered):
    return 100 * (initial - delivered) / initial if initial else None


# thin out by chunking and returning start, end, min and max from each chunk
def reduce_points(points: list[tuple[float, int]], limit=5000):
    if len(points) <= limit:
        return points
    width = max(1, (len(points) + limit // 4 - 1) // (limit // 4))
    result = []
    for start in range(0, len(points), width):
        chunk = points[start : start + width]
        indices = {
            0,
            len(chunk) - 1,
            min(range(len(chunk)), key=lambda i: chunk[i][1]),
            max(range(len(chunk)), key=lambda i: chunk[i][1]),
        }
        result.extend(chunk[i] for i in sorted(indices))
    return result


def plot_data(result: ResultData, initial) -> PlotData:
    events: dict[str, list[float]] = defaultdict(list)
    durations: dict[str, dict[str, float]] = defaultdict(lambda: dict.fromkeys(CATEGORIES, 0.0))
    waiting: dict[str, dict[float, int]] = defaultdict(lambda: defaultdict(int))

    # summarize loss by event (workflow state)
    for event in result.metadata.event_metadata:
        if event.event_type == "end" and event.task_type == "development":
            events[event.event].append(-100 * event.loss)

    for record in result.metadata.resource_metadata:
        # track incremental increase/decrease in waiting resources by workflow state
        waiting[record.state][record.time] += record.waiting

        # summarize time spent by resource in each time category
        for key in CATEGORIES:
            durations[record.state][key] += getattr(record, key) or 0

    stages, activity, backlog = [], [], []
    for stage in dict.fromkeys([*STAGES, *events, *durations]):
        label = STAGES.get(stage, stage)
        if events[stage]:
            stages.append(
                StageLoss(
                    stage=stage,
                    label=label,
                    visits=len(events[stage]),
                    loss_percent=sum(events[stage]) / len(events[stage]),
                )
            )
        if stage in durations:
            total = sum(durations[stage].values())
            activity.append(
                ResourceActivity(
                    stage=stage,
                    label=label,
                    durations=durations[stage],
                    shares={
                        k: 100 * v / total if total else None for k, v in durations[stage].items()
                    },
                )
            )
        if stage in waiting:
            points, current = [(0.0, 0)], 0
            for time, delta in sorted(waiting[stage].items()):
                current += delta
                if current < 0:
                    raise AppError("INVALID_RESULT", "Resource backlog became negative", 502)
                points.append((time, current))
            points.append((result.summary_result.completion_time, current))
            reduced = reduce_points(points)
            backlog.append(
                Backlog(
                    stage=stage,
                    label=label,
                    time=[p[0] for p in reduced],
                    waiting=[p[1] for p in reduced],
                    reduced=len(points) != len(reduced),
                )
            )
    return PlotData(
        loss_percent=loss_percent(initial, result.summary_result.total_delivered_value),
        stages=stages,
        activity=activity,
        backlog=backlog,
    )
