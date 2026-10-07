"""Small evidence-backed observations; proposed interventions are untested."""
from .schemas import ModelSettings, Observation, PlotData


def observations(metrics: PlotData, settings: ModelSettings) -> list[Observation]:
    """Build evidence-backed observations from simulation metrics.

    Args:
        metrics (PlotData): Simulation metrics to summarize.
        settings (ModelSettings): Model settings used to suggest changes.

    Returns:
        list[Observation]: Findings derived from the supplied metrics.
    """
    if metrics.loss_percent is None:
        return [
            Observation(
                rule="zero_value",
                message="Value-loss comparisons are unavailable because initial value is zero.",
                evidence="Total initial value is zero.",
            )
        ]
    result: list[Observation] = []
    if metrics.stages:
        stage = max(metrics.stages, key=lambda item: item.loss_percent)
        if stage.loss_percent > 0:
            result.append(
                Observation(
                    rule="stage_loss",
                    message=f"{stage.label} has the largest observed mean stage-visit loss.",
                    evidence=f"{stage.loss_percent:.2f}% across {stage.visits} visits. These means are not an additive breakdown of total loss.",
                    property=(
                        "deployment_cadence"
                        if stage.stage == "qa_complete" and settings.deployment_cadence
                        else None
                    ),
                    value=max(0, settings.deployment_cadence // 2),
                )
            )
    if metrics.backlog:
        queue = max(metrics.backlog, key=lambda item: max(item.waiting, default=0))
        peak = max(queue.waiting, default=0)
        if peak > 0:
            field = {
                "qa_testing": "qa_size",
                "development": "team_size",
                "deployment": "toolchain_size",
            }.get(queue.stage)
            result.append(
                Observation(
                    rule="backlog",
                    message=f"{queue.label} has the largest observed resource-request backlog. Try additional capacity.",
                    evidence=f"Peak: {peak} waiting requests; a request may contain several tasks. Improvement is untested.",
                    property=field,
                    value=getattr(settings, field) + 1 if field else None,
                )
            )
    for item in metrics.activity:
        if item.durations["failure_t"] > 0:
            field = (
                "qa_failure_rate"
                if item.stage == "qa_testing"
                else "deployment_failure_rate" if item.stage == "deployment" else None
            )
            result.append(
                Observation(
                    rule="failed_work",
                    message=f"{item.label} records time spent on failed work. Test a lower failure rate.",
                    evidence=f"Recorded failed-work duration: {item.durations['failure_t']:.2f} time units. Improvement is untested.",
                    property=field,
                    value=getattr(settings, field) / 2 if field else None,
                )
            )
    return result
