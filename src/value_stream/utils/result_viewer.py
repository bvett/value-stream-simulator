from typing import Any
from enum import Enum
import matplotlib.pyplot as plt
from matplotlib import ticker
import numpy as np
from pandas import json_normalize
from tqdm import tqdm
from ..simulation_result import SimulationResult
from ..task_event import TaskEvent
from ..workflow_state_name import WorkflowStateName


class ResultViewer:
    """Handles rendering of simulation results"""

    def __init__(self, results: list[SimulationResult], pbar: tqdm | None = None):

        results_dict: list[dict[str, Any]] = []

        for r in results:
            results_dict.append(_to_dict(r))

            if pbar:
                pbar.update()

        self.df = json_normalize(results_dict, record_path=['events'],
                                 meta=[['model', 'deployment_cadence'],
                                       ['model', 'toolchain_concurrency'],
                                       ['model', 'team_size'],
                                       ['task', 'task_id'],
                                       ['task', 'loss'],
                                       ['task', 'delivered_value']],
                                 errors='ignore')

        self.df.set_index(['model.deployment_cadence',
                           'model.team_size', 'task.task_id'], inplace=True)

        self.df.sort_index(inplace=True)

        self.df["event_duration"] = self.df.groupby(level=2)['time'].diff()
        self.df["cumulative_time"] = self.df.groupby(
            level=2)['event_duration'].cumsum()

        self.df_workflow_stages = \
            self.df.loc[(self.df['event_type'] == TaskEvent.EventType.END) &
                        (self.df['status'] == TaskEvent.EventStatus.SUCCESS)]

        self.df_completed_tasks = \
            self.df.loc[(self.df['event_type'] == TaskEvent.EventType.TERMINAL) &
                        (self.df['status'] == TaskEvent.EventStatus.SUCCESS)]

    def loss_vs_cadence(self, team_samples: int | None = None):
        """shows the impact of deployment cadence on loss

        Args:
            team_samples (int|None):When the optional _team_samples_ parameter is provided, 
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
                     ylabel="Loss", grid=True)

        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

        plt.legend(title="Team Size")
        plt.gca().invert_xaxis()
        ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1.0))
        plt.show()

    def time_alloc_vs_cadence(self, nrows=2, ncols=3):
        """Plots a grid of pie charts(defined by nrows and ncols) that 
        provides a breakdown of how time was spent given a delivery cadence

        Args:
            nrows(int, optional):  # Rows. Defaults to 2.
            ncols(int, optional):  # Columns. Defaults to 3.
        """
        df = self.df_workflow_stages[['event', 'event_duration']].groupby(
            ['model.deployment_cadence', 'event']).mean().unstack(-1)

        count = len(df)

        fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(10, 6))

        row_sample = np.linspace(
            0, count-1, min(count, nrows * ncols), dtype=int)

        for i, index in enumerate(row_sample):
            ax = axes[i // ncols, i % ncols]
            ax.pie(df.iloc[index], startangle=30, autopct='%1.0f%%')
            ax.set_title(df.index[index])

        for i in range(nrows * ncols, count, -1):
            row = (i-1) // ncols
            column = (i-1) % ncols
            axes[row, column].remove()

        fig.legend(df.columns.get_level_values(1))
        fig.suptitle("Time Allocation by Cadence")
        fig.subplots_adjust(wspace=.2)

        plt.show()

    def delivery_timeline(self, cadence: int, team_size: int):
        """Provides a task-centric view of delivery

        Use the cadence and team_size arguments to choose the 
        set of tasks from the simulation results.

        """

        df = self.df_workflow_stages

        labels = ['waiting for dev', 'development',
                  'waiting for delivery', 'delivery']

        df = df.loc[(df.index.get_level_values('model.deployment_cadence') == cadence)
                    & (df.index.get_level_values('model.team_size') == team_size)]

        df = df[['event', 'event_duration', 'time']]\
            .groupby(['task.task_id', 'event'])\
            .mean()\
            .unstack(-1)

        df = df.sort_values(
            by=[('time', WorkflowStateName.DEPLOYMENT),
                ('time', WorkflowStateName.DEV_COMPLETE),
                ('time', WorkflowStateName.DEVELOPMENT)],  # type:ignore
            ascending=[False, False, False])  # type:ignore

        df = df[['event_duration']]
        df.columns = df.columns.get_level_values(1)  # type: ignore

        category_colors = ['lightgrey', 'orange', 'khaki', 'green']

        ax = df[[WorkflowStateName.PENDING, WorkflowStateName.DEVELOPMENT,
                 WorkflowStateName.DEV_COMPLETE, WorkflowStateName.DEPLOYMENT]].plot(
            kind='barh', stacked=True, title='Delivery Timeline', color=category_colors)
        ax.yaxis.set_ticks([])
        ax.yaxis.set_visible(True)
        ax.set_ylabel("Task")
        ax.set_xlabel("Time")
        ax.legend(labels)
        plt.show()

    def delivered_value_vs_time(self, cadence: int, team_samples: int | None = None):
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
                     xlabel='Time', ylabel='Delivered Value', grid=True)

        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
        ax.xaxis.set_minor_locator(ticker.AutoMinorLocator())
        ax.grid(visible=True, which='major', axis='y')

        plt.legend(title="Team Size")

        plt.show()

    def delivered_value_vs_team_size(self, cadence_samples: int | None = None):
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
                xlabel="Team Size", ylabel='Delivered Value', grid=True)
        plt.legend(title="Deployment Cadence")
        plt.show()


def _to_dict(obj: Any):

    if isinstance(obj, list):
        return [_to_dict(o) for o in obj]

    if isinstance(obj, Enum):
        return str(obj)

    if hasattr(obj, '__dict__'):
        result: dict[str, Any] = {}

        for _, (k, v) in enumerate(obj.__dict__.items()):

            result[k] = _to_dict(v)

        return result
    return obj
