from typing import Any
import matplotlib.pyplot as plt
from matplotlib import ticker
import numpy as np
from pandas import json_normalize, Categorical

from value_stream.simulation import SimulationResult
from value_stream.core import WorkflowStateName
from .viewer import Viewer


class MetadataViewer(Viewer):
    def __init__(self, results: list[SimulationResult], colormap: str = 'plasma'):
        super().__init__(colormap)
        self._results_dict: list[Any] = []

        for result in results:
            self._results_dict.append(super()._to_dict(
                result.metadata, ['toolchain_pool', 'qa_testers', 'developer_team', 'support_interval']))

    def mean_stage_loss(self):
        df = json_normalize(self._results_dict, record_path=['event_metadata'],
                            meta=[['model', 'deployment_cadence'],
                                  ['model', 'team_size']],
                            errors='ignore')

        df.set_index(['model.deployment_cadence',
                      'model.team_size'], inplace=True)

        df.sort_index(inplace=True)

        df = df[(df['event_type'] == 'end')][['event', 'loss', 'status']]

        df['event'] = Categorical(df['event'], categories=[
            e.value for e in WorkflowStateName], ordered=True)

        team_samples = df.groupby(['model.team_size'])

        fig, axs = plt.subplots(
            ncols=len(team_samples), nrows=1, sharex=True, sharey=True, squeeze=True)

        axs_i = 0

        for name, team_sample in team_samples:
            ax = axs[axs_i]
            axs_i += 1

            df = team_sample.groupby(
                ['event', 'model.deployment_cadence']).mean(numeric_only=True)['loss'].unstack(level=['model.deployment_cadence'])

            df.plot.bar(ax=ax,
                        xlabel='', ylabel='', legend=None, colormap=self.colormap)

            ax.set_title(label=f"Team Size={name[0]}", fontsize=8)

            ax.yaxis.set_inverted(True)
            ax.yaxis.set_major_formatter(
                ticker.PercentFormatter(xmax=1.0, decimals=1))

            if axs_i == 1:
                ax.legend(title='Deployment Cadence')

        fig.supxlabel('SDLC Workflow Stage')
        fig.supylabel('Mean Loss')
        fig.suptitle("Mean Stage Loss")

        plt.tight_layout()
        plt.show()

    def resource_utilization(self):

        df_all = json_normalize(self._results_dict, record_path=['resource_metadata'],
                                meta=[['model', 'deployment_cadence'],
                                      ['model', 'team_size']],
                                errors='ignore')

        df_all['state'] = Categorical(df_all['state'], categories=[
            e.value for e in WorkflowStateName], ordered=True)

        df_all.set_index(['model.deployment_cadence',
                          'model.team_size', 'state', 'time'], inplace=True)

        df_all.sort_index(inplace=True)

        df_all = df_all.groupby(
            ['model.deployment_cadence', 'model.team_size', 'state', 'time']).sum()

        cadence_x_team_size_samples = df_all.groupby(
            ['model.deployment_cadence', 'model.team_size'])

        dataframes = {key: group for key, group in cadence_x_team_size_samples}

        # detemrine the size of the subplot grid based on number of unique keys in each dimension

        all_keys = np.array(list(dataframes.keys()))
        cadences, team_sizes = list(all_keys[:, 0]), list(all_keys[:, 1])

        # deduplicate
        cadences = list(dict.fromkeys(cadences))
        team_sizes = list(dict.fromkeys(team_sizes))

        fig, axs = plt.subplots(nrows=len(cadences), ncols=len(team_sizes),
                                sharex=True, sharey=True, layout='constrained', squeeze=False)

        labels = ['Scarce', 'Idle',
                  'Productive', 'Failure', 'Unplanned Work']

        for team_i, team_size in enumerate(team_sizes):
            for cadence_i, cadence in enumerate(cadences):
                group = dataframes[(cadence, team_size)]

                group = group.groupby(['state']).sum()[
                    ['waiting_t', 'idle_t', 'success_t', 'failure_t', 'interruption_t']]

                df = group.divide(group.sum(axis=1), axis=0)

                ax = axs[cadence_i, team_i]
                df.plot(ax=ax, kind='bar', stacked=True,
                        legend=False, xlabel='', ylabel='', colormap=self.colormap)
                ax.set_title(
                    label=f"Cadence={cadence},Team Size={team_size}", fontsize=8)

                ax.yaxis.set_major_formatter(
                    ticker.PercentFormatter(xmax=1.0, decimals=1))

                plt.sca(ax)
                plt.xticks(rotation=45)

        fig.legend(title='Utilization Category', labels=labels)
        fig.supylabel('Utilization')
        fig.supxlabel('SDLC Workflow Stage')
        fig.suptitle("Resource Utilization")
        plt.show()
