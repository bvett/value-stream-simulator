from typing import Any
from enum import Enum
import colorsys
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib import ticker
import numpy as np
from pandas import json_normalize
from tqdm import tqdm
from ..event_status import EventStatus
from ..simulation_result import SimulationResult
from ..task import TaskType
from ..task_event import TaskEvent
from ..workflow_state_name import WorkflowStateName


class ResultViewer:
    """Handles rendering of simulation results"""

    def __init__(self, results: list[SimulationResult], pbar: tqdm | None = None, colormap='plasma'):

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
            results_dict.append(_to_dict(r))

            if pbar:
                pbar.update()

        self.df = json_normalize(results_dict, record_path=['events'],
                                 meta=[['model', 'deployment_cadence'],
                                       ['model', 'toolchain_pool'],
                                       ['model', 'team_size'],
                                       ['task', 'task_id'],
                                       ['task', 'loss'],
                                       ['task', 'delivered_value'],
                                       ['task', 'task_type']],
                                 errors='ignore')

        self.df.set_index(['model.deployment_cadence',
                           'model.team_size', 'task.task_id'], inplace=True)

        self.df.sort_index(inplace=True)

        self.df["event_duration"] = self.df.groupby(level=2)['time'].diff()
        self.df["cumulative_time"] = self.df.groupby(
            level=2)['event_duration'].cumsum()

        self.df_workflow_stages = \
            self.df.loc[(self.df['event_type'] == TaskEvent.EventType.END) &
                        (self.df['task.task_type'] == TaskType.DEVELOPMENT)]

        self.df_completed_tasks = \
            self.df.loc[(self.df['event_type'] == TaskEvent.EventType.TERMINAL) &
                        (self.df['status'] == EventStatus.SUCCESS) &
                        (self.df['task.task_type'] == TaskType.DEVELOPMENT)]

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
                     ylabel="Loss", grid=True, colormap=self.colormap)

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

        df = df[[('event_duration', k) for k in self.statecolor_map.keys()]]

        fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(10, 6))

        row_sample = np.linspace(
            0, count-1, min(count, nrows * ncols), dtype=int)

        colors = [c for c in self.statecolor_map.values()]

        for i, index in enumerate(row_sample):
            ax = axes[i // ncols, i % ncols]
            _, _, autotexts = ax.pie(df.iloc[index], startangle=30,
                                     autopct=lambda p: f"{p:1.0f}%" if p > 10 else '',
                                     colors=colors,
                                     pctdistance=.75)
            ax.set_title(df.index[index])

            for i, autotext in enumerate(autotexts):
                autotext.set_color(self._textcolor(colors[i]))

        for i in range(nrows * ncols, count, -1):
            row = (i-1) // ncols
            column = (i-1) % ncols
            axes[row, column].remove()

        fig.legend(labels=[self.label_map[k]
                   for k in self.statecolor_map.keys()])
        fig.suptitle("Time Allocation by Cadence")
        fig.subplots_adjust(wspace=.2)

        plt.show()

    def delivery_timeline(self, cadence: int, team_size: int):
        """Provides a task-centric view of delivery

        Use the cadence and team_size arguments to choose the
        set of tasks from the simulation results.

        """

        df = self.df_workflow_stages

        labels = ['waiting for dev', 'development', 'waiting for qa', 'qa',
                  'waiting for delivery', 'delivery']

        df = df.loc[(df.index.get_level_values('model.deployment_cadence') == cadence)
                    & (df.index.get_level_values('model.team_size') == team_size)]

        df['start_time'] = df['time'] - df['event_duration']

        df = df.groupby(['task.task_id', 'event'])[[
            'time', 'start_time', 'event_duration', 'status']].agg(list)

        df['timeline'] = [list(zip(t, d))  # type:ignore
                          for t, d in zip(df['start_time'], df['event_duration'])]

        df = df.unstack(-1)

        df.sort_values(
            by=('time', 'deployment'),
            key=lambda x: x.apply(max), ascending=False, inplace=True)  # type:ignore

        y = 1
        for _, row in df.iterrows():

            for state, facecolor in self.statecolor_map.items():
                edgecolors = [self.edgecolor_map[s]
                              for s in row[('status', state)]]

                plt.broken_barh(xranges=row[('timeline', state)], yrange=(
                    y, 1), facecolor=facecolor, edgecolors=edgecolors)

            y += 1

        custom_lines = []

        for color in self.statecolor_map.values():
            custom_lines.append(Rectangle(xy=(0, 0), width=0, height=0,
                                          facecolor=color))

        custom_lines.append(Rectangle(xy=(0, 0), width=0, height=0,
                            facecolor='none', edgecolor='red'))

        plt.yticks([])
        plt.title(
            f"Delivery Timeline for Cadence={cadence}, Team Size={team_size}")
        plt.ylabel('Task')
        plt.xlabel('Time')
        labels = [self.label_map[k] for k in self.statecolor_map.keys()]

        plt.legend(custom_lines, labels + ['failed event'])
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
                     xlabel='Time', ylabel='Delivered Value', grid=True,
                     colormap=self.colormap)

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
                xlabel="Team Size", ylabel='Delivered Value', grid=True,
                colormap=self.colormap)
        plt.legend(title="Deployment Cadence")
        plt.show()

    def _textcolor(self, color):
        color_hls = colorsys.rgb_to_hls(color[0], color[1], color[2])

        return 'white' if color_hls[1] < 0.5 else 'black'


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
