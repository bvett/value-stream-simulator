from typing import Optional
import colorsys
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib import ticker
import numpy as np
from tqdm import tqdm
from ..event_status import EventStatus
from ..simulation_result import SimulationResult
from ..task import TaskType
from ..task_event import TaskEvent

from .viewer import Viewer


class ResultViewer(Viewer):
    """Handles rendering of simulation results"""

    def __init__(self, results: list[SimulationResult], pbar: Optional[tqdm] = None, colormap='plasma'):
        super().__init__(results=results, pbar=pbar, colormap=colormap)

        self.df_workflow_stages = \
            self.df.loc[(self.df['event_type'] == TaskEvent.EventType.END) &
                        (self.df['task.task_type'] == TaskType.DEVELOPMENT)]

        self.df_completed_tasks = \
            self.df.loc[(self.df['event_type'] == TaskEvent.EventType.TERMINAL) &
                        (self.df['status'] == EventStatus.SUCCESS) &
                        (self.df['task.task_type'] == TaskType.DEVELOPMENT)]

    def loss_vs_cadence(self, team_samples: Optional[int] = None):
        """shows the impact of deployment cadence on loss

        Args:
            team_samples (Optional[int]): When the optional _team_samples_ parameter is provided,
            it limits the number of series to an even distribution of team sizes
            between the minimum and maximum, inclusive.
        """

        df = self.df_completed_tasks

        min_team_size: int = df.index.get_level_values('model.team_size').min()
        max_team_size: int = df.index.get_level_values('model.team_size').max()

        num = max_team_size - min_team_size + \
            1 if team_samples is None else min(max_team_size, team_samples)

        team_sample = np.linspace(
            min_team_size, max_team_size, min(max_team_size, num), dtype=int)

        df = df.loc[(df.index.get_level_values(
            'model.team_size').isin(team_sample))]

        df = df[['task.loss', 'task.delivered_value']].groupby(
            ['model.deployment_cadence', 'model.team_size']).mean().unstack(-1)[['task.loss']]

        df.columns = df.columns.get_level_values(1)  # type: ignore

        ax = df.plot(title="Loss vs Cadence", xlabel="Cadence",
                     ylabel="Loss", grid=True, colormap=self.colormap)

        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

        plt.legend(title="Team Size")
        plt.gca().invert_xaxis()
        ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1.0))
        plt.show()

    def delivered_value_vs_time(self, cadence: int, team_samples: Optional[int] = None):
        """Plots delivered value over time, grouped by team size

        Args:
            cadence(int): filters to plot results from the specified cadence
            team_samples(int): en the optional _team_samples_ parameter is provided, 
            it limits the number of series to an even distribution of team sizes 
            between the minimum and maximum, inclusive.

        """

        df = self.df_completed_tasks

        min_team_size: int = df.index.get_level_values('model.team_size').min()
        max_team_size: int = df.index.get_level_values('model.team_size').max()

        num = max_team_size - min_team_size + \
            1 if not team_samples else min(max_team_size, team_samples)

        team_size_sample = np.linspace(
            min_team_size, max_team_size, num, dtype=int)

        df = df.loc[(df.index.get_level_values('model.deployment_cadence') == cadence) &
                    (df.index.get_level_values('model.team_size').isin(team_size_sample))]

        df = df[['time', 'task.delivered_value']].groupby(
            ['model.team_size', 'time']).sum().unstack(0).cumsum().ffill()

        df.columns = df.columns.get_level_values(1)  # type: ignore

        ax = df.plot(drawstyle='steps-post', title='Delivered Value vs Time',
                     xlabel='Time', ylabel='Delivered Value', grid=True,
                     colormap=self.colormap)

        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
        ax.xaxis.set_minor_locator(ticker.AutoMinorLocator())
        ax.grid(visible=True, which='major', axis='y')

        plt.legend(title="Team Size")

        plt.show()

    def delivered_value_vs_team_size(self, cadence_samples: Optional[int] = None):
        """Plots delivered value over team size, grouped by cadence
        Args:
            cadence(int):  number of samples from the cadences in the simulation, 
            or all cadences if None. Defaults to None

        """
        df = self.df_completed_tasks

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

        df = df[['task.delivered_value']].groupby(
            ['model.team_size', 'model.deployment_cadence']).sum().unstack(-1)

        df.columns = df.columns.get_level_values(1)  # type: ignore

        df.plot(title="Delivered Value vs Team Size",
                xlabel="Team Size", ylabel='Delivered Value', grid=True,
                colormap=self.colormap)
        plt.legend(title="Deployment Cadence")
        plt.show()
