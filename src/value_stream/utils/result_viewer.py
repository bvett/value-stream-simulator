import json
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from pandas import json_normalize
from ..simulation_result import SimulationResult


class ResultViewer:
    def __init__(self, results: list[SimulationResult]):

        self._json = bytearray(b'[') + \
            b','.join([r.to_json() for r in results]) + b']'

        self.df = json_normalize(json.loads(self._json), ['tasks'], meta=[
            ['model', 'team_size'], ['model', 'deployment_cadence']])

        self.df['history.dev_wait'] = self.df['history.dev_start_t'] - \
            self.df['creation_t']
        self.df['history.dev_t'] = self.df['history.dev_end_t'] - \
            self.df['history.dev_start_t']
        self.df['history.delivery_wait'] = self.df['history.delivery_start_t'] - \
            self.df['history.dev_end_t']
        self.df['history.delivery_t'] = self.df['history.delivery_end_t'] - \
            self.df['history.delivery_start_t']

    @property
    def json(self) -> str:
        return self._json.decode('utf-8')

    def loss_vs_cadence(self, team_samples: int | None = None):
        """shows the impact of deployment cadence on loss

        Args:
            team_samples (int|None):When the optional _team_samples_ parameter is provided, it limits the number of series to an even distribution of team sizes between the minimum and maximum, inclusive.
        """
        df = self.df.set_index('model.deployment_cadence')

        min_team_size: int = df['model.team_size'].min()
        max_team_size: int = df['model.team_size'].max()

        num = max_team_size - min_team_size + \
            1 if team_samples is None else min(max_team_size, team_samples)

        team_sample = np.linspace(
            min_team_size, max_team_size, min(max_team_size, num), dtype=int)

        df = df.loc[(df['model.team_size'].isin(team_sample))]

        df = df.groupby(["model.deployment_cadence", "model.team_size"]).mean(
            True)["loss"].unstack(-1)

        ax = df.plot(title="Loss vs Cadence", xlabel="Cadence",
                     ylabel="Loss", grid=True)

        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

        plt.legend(title="Team Size")
        plt.gca().invert_xaxis()
        ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1.0))
        plt.show()

    def time_alloc_vs_cadence(self, nrows=2, ncols=3):
        """Plots a grid of pie charts(defined by nrows and ncols) that provide a breakdown of how time was spent given a delivery cadence

        Args:
            nrows(int, optional):  # Rows. Defaults to 2.
            ncols(int, optional):  # Columns. Defaults to 3.
        """

        df = self.df.set_index('model.deployment_cadence')

        labels = ['waiting for dev', 'development',
                  'waiting for delivery', 'delivery']

        data = df.groupby(['model.deployment_cadence'])[
            ['history.dev_wait', 'history.dev_t',
             'history.delivery_wait', 'history.delivery_t']].mean()

        count = len(data)

        fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(10, 6))

        row_sample = np.linspace(
            0, count-1, min(count, nrows * ncols), dtype=int)

        for i, index in enumerate(row_sample):
            ax = axes[i // ncols, i % ncols]
            ax.pie(data.iloc[index], startangle=30, autopct='%1.0f%%')
            ax.set_title(data.index[index])

        for i in range(nrows * ncols, count, -1):
            row = (i-1) // ncols
            column = (i-1) % ncols
            axes[row, column].remove()

        fig.legend(labels)
        fig.suptitle("Time Allocation by Cadence")
        fig.subplots_adjust(wspace=.2)

        plt.show()

    def delivery_timeline(self, cadence: int, team_size: int):
        """Provides a task-centric view of delivery

        Use the cadence and team_size arguments to choose the the set of tasks from the simulation results.

        """
        df = self.df.set_index('task_id')

        labels = ['waiting for dev', 'development',
                  'waiting for delivery', 'delivery']

        data = df.loc[(df['model.deployment_cadence'] == cadence)
                      & (df['model.team_size'] == team_size)]

        data.sort_values(['history.delivery_end_t', 'history.dev_end_t', 'history.dev_start_t'],
                         inplace=True, ascending=[False, False, False])

        category_colors = ['lightgrey', 'orange', 'khaki', 'green']

        ax = data[['history.dev_wait', 'history.dev_t',
                   'history.delivery_wait', 'history.delivery_t']].plot(
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
            team_samples(int): en the optional _team_samples_ parameter is provided, it limits the number of series to an even distribution of team sizes between the minimum and maximum, inclusive.

        """

        df = self.df

        min_team_size: int = df['model.team_size'].min()
        max_team_size: int = df['model.team_size'].max()

        num = max_team_size - min_team_size + \
            1 if not team_samples else min(max_team_size, team_samples)

        team_size_sample = np.linspace(
            min_team_size, max_team_size, num, dtype=int)

        df = df.loc[(df['model.deployment_cadence'] == cadence) &
                    (df['model.team_size'].isin(team_size_sample))][['history.delivery_end_t', 'model.team_size', 'delivered_value']]

        df = df.groupby(
            ['model.team_size', 'history.delivery_end_t']).sum().unstack(0).cumsum().ffill()

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
            cadence(int):  number of samples from the cadences in the simulation, or all cadences if None. Defaults to None

        """
        df = self.df.set_index('model.team_size')

        min_cadence: int = df['model.deployment_cadence'].min()
        max_cadence: int = df['model.deployment_cadence'].max()

        num = max_cadence - \
            min_cadence + 1 if cadence_samples is None else min(
                max_cadence, cadence_samples)

        cadence_sample = np.linspace(
            min_cadence, max_cadence, num, dtype=int)

        df = df.loc[(df['model.deployment_cadence'].isin(cadence_sample))]

        data = df.groupby(['model.team_size', 'model.deployment_cadence']
                          ).sum(True)[['delivered_value']].unstack(-1)

        data.columns = data.columns.get_level_values(1)  # type: ignore

        data.plot(title="Delivered Value vs Team Size",
                  xlabel="Team Size", ylabel='Delivered Value', grid=True)
        plt.legend(title="Deployment Cadence")
        plt.show()
