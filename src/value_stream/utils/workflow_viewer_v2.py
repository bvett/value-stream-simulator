import colorsys
from enum import Enum
import matplotlib
from typing import Optional

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
from tqdm import tqdm
from typing import Any

from ..event_status import EventStatus
from ..task import TaskType
from ..simulation_result import SimulationResultV2
from ..task_event import TaskEvent
from ..workflow_state_name import WorkflowStateName


class WorkflowViewerV2:
    def __init__(self, results: list[SimulationResultV2], pbar: Optional[tqdm] = None, colormap='plasma'):

        self.colormap = matplotlib.colormaps[colormap]
        self.results_dict: list[dict[str, Any]] = []

        colors = iter(self.colormap(
            np.linspace(0.1, 0.9, len(WorkflowStateName))))

        self.statecolor_map = {
            WorkflowStateName.PENDING: next(colors),
            WorkflowStateName.DEVELOPMENT: next(colors),
            WorkflowStateName.DEV_COMPLETE: next(colors),
            WorkflowStateName.QA_TESTING: next(colors),
            WorkflowStateName.QA_COMPLETE: next(colors),
            WorkflowStateName.DEPLOYMENT: next(colors)
        }

        self.label_map = {
            WorkflowStateName.PENDING: 'waiting for dev',
            WorkflowStateName.DEVELOPMENT: 'development',
            WorkflowStateName.DEV_COMPLETE: 'waiting for qa',
            WorkflowStateName.QA_TESTING: 'qa',
            WorkflowStateName.QA_COMPLETE: 'waiting for delivery',
            WorkflowStateName.DEPLOYMENT: 'delivery'
        }

        self.edgecolor_map = {
            EventStatus.SUCCESS: 'none',
            EventStatus.FAILURE: 'red'
        }

        for r in results:
            for d in r.detailed_result:
                self.results_dict.append(
                    _to_dict(d, ['toolchain_pool', 'qa_testers', 'developer_team', 'support_interval']))

            if pbar:
                pbar.update()


def _to_dict(obj: Any, exclusions: list[str] | None = None):

    if exclusions is None:
        exclusions = []

    if isinstance(obj, list):
        return [_to_dict(o) for o in obj]

    if isinstance(obj, Enum):
        return str(obj)

    if hasattr(obj, '__dict__'):
        result: dict[str, Any] = {}

        for _, (k, v) in enumerate(obj.__dict__.items()):
            if k not in exclusions:
                result[k] = _to_dict(v, exclusions)

        return result
    return obj
