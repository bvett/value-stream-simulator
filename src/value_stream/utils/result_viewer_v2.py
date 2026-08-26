from enum import Enum
from matplotlib import colormaps, ticker
import matplotlib.pyplot as plt
import numpy as np
from typing import Any, Optional

from pandas import json_normalize

from ..event_status import EventStatus
from ..simulation_result import SimulationResultV2
from ..workflow_state_name import WorkflowStateName


class ResultViewerV2:
    def __init__(self, results: list[SimulationResultV2], colormap='plasma'):

        self.colormap = colormaps[colormap]
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
            self.results_dict.append(self._to_dict(
                r, ['toolchain_pool', 'qa_testers', 'developer_team', 'support_interval']))  # type: ignore

        self.data = json_normalize(self.results_dict,
                                   meta=[['model', 'deployment_cadence'],
                                         ['model', 'team_size']],
                                   errors='ignore')

        self.data.set_index(['model.deployment_cadence',
                             'model.team_size'], inplace=True)

    def loss_vs_cadence(self, team_samples: Optional[int] = None):
        df = self.data

        min_team_size: int = df.index.get_level_values('model.team_size').min()
        max_team_size: int = df.index.get_level_values('model.team_size').max()

        num = max_team_size - min_team_size + \
            1 if team_samples is None else min(max_team_size, team_samples)

        team_sample = np.linspace(
            min_team_size, max_team_size, min(max_team_size, num), dtype=int)

        df = df.loc[(df.index.get_level_values(
            'model.team_size').isin(team_sample))]

        df = df[['loss', 'total_delivered_value']].unstack(-1)[['loss']]

        df.columns = df.columns.get_level_values(1)  # type: ignore

        ax = df.plot(title="Loss vs Cadence", xlabel="Cadence",
                     ylabel="Loss", grid=True, colormap=self.colormap)

        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

        plt.legend(title="Team Size")
        plt.gca().invert_xaxis()
        ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1.0))
        plt.show()

    def delivered_value_vs_time(self, cadence: int, team_samples: Optional[int] = None):
        df = self.data

        min_team_size: int = df.index.get_level_values('model.team_size').min()
        max_team_size: int = df.index.get_level_values('model.team_size').max()

        num = max_team_size - min_team_size + \
            1 if not team_samples else min(max_team_size, team_samples)

        team_size_sample = np.linspace(
            min_team_size, max_team_size, num, dtype=int)

        df = df.loc[(df.index.get_level_values('model.deployment_cadence') == cadence) &
                    (df.index.get_level_values('model.team_size').isin(team_size_sample)) &
                    (df['workflow_state'] == WorkflowStateName.DELIVERY)]

        df = df.groupby(['model.team_size', 'time']).sum().unstack(0)[
            'value'].cumsum().ffill()

        ax = df.plot(drawstyle='steps-post', title='Delivered Value vs Time',
                     xlabel='Time', ylabel='Delivered Value', grid=True,
                     colormap=self.colormap)

        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
        ax.xaxis.set_minor_locator(ticker.AutoMinorLocator())
        ax.grid(visible=True, which='major', axis='y')

        plt.legend(title="Team Size")

        plt.show()

    def loss_vs_team_size(self, cadence_samples: Optional[int] = None):

        df = self.data

        min_cadence: int = df.index.get_level_values(
            'model.deployment_cadence').min()
        max_cadence: int = df.index.get_level_values(
            'model.deployment_cadence').max()

        num = max_cadence - \
            min_cadence + 1 if cadence_samples is None else min(
                max_cadence, cadence_samples)

        cadence_sample = np.linspace(
            min_cadence, max_cadence, num, dtype=int)

        df = df.loc[(df.index.get_level_values(
            'model.deployment_cadence').isin(cadence_sample))]

        df = df[['loss']].unstack(0)

        df.columns = df.columns.get_level_values(1)  # type: ignore

        ax = df.plot(title="Loss vs Team Size",
                     xlabel="Team Size", ylabel='Loss', grid=True,
                     colormap=self.colormap)
        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
        plt.legend(title="Deployment Cadence")
        ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1.0))
        plt.show()

    @classmethod
    def _to_dict(cls, obj: Any, exclusions: list[str] | None = None):

        if exclusions is None:
            exclusions = []

        if isinstance(obj, list):
            return [cls._to_dict(o) for o in obj]

        if isinstance(obj, Enum):
            return str(obj)

        if hasattr(obj, '__dict__'):
            result: dict[str, Any] = {}

            for _, (k, v) in enumerate(obj.__dict__.items()):
                if k not in exclusions:
                    result[k] = cls._to_dict(v, exclusions)

            return result
        return obj
