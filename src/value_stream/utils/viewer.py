from enum import Enum
import matplotlib
import numpy as np

from pandas import json_normalize
from tqdm import tqdm
from typing import Any, Optional

from ..event_status import EventStatus
from ..simulation_result import SimulationResult
from ..workflow_state_name import WorkflowStateName


class Viewer:

    def __init__(self, results: list[SimulationResult], pbar: Optional[tqdm] = None, colormap='plasma'):

        self.colormap = matplotlib.colormaps[colormap]
        results_dict: list[dict[str, Any]] = []

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
            results_dict.append(_to_dict(r, ['toolchain_pool']))

            if pbar:
                pbar.update()

        self.df = json_normalize(results_dict, record_path=['events'],
                                 meta=[['model', 'deployment_cadence'],
                                       ['model', 'team_size'],
                                       ['task', 'task_name'],
                                       ['task', 'loss'],
                                       ['task', 'delivered_loss'],
                                       ['task', 'delivered_value'],
                                       ['task', 'task_type']],
                                 errors='ignore')

        self.df.set_index(['model.deployment_cadence',
                           'model.team_size', 'task.task_name'], inplace=True)

        self.df.sort_index(inplace=True)

        self.df["event_duration"] = self.df.groupby(level=2)['time'].diff()
        self.df["cumulative_time"] = self.df.groupby(
            level=2)['event_duration'].cumsum()


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
