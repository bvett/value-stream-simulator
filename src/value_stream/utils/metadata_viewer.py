from typing import Any, Optional
from enum import Enum
import matplotlib.pyplot as plt
from matplotlib import ticker
import numpy as np
from pandas import json_normalize, Categorical
from tqdm import tqdm
from ..simulation_metadata import SimulationMetadata
from ..workflow_state_name import WorkflowStateName


class MetadataViewer:
    def __init__(self, metadata: list[SimulationMetadata], pbar: Optional[tqdm] = None):

        self._metadata_dict: list[Any] = []

        for m in metadata:
            self._metadata_dict.append(self._to_dict(
                m, ['toolchain_pool', 'qa_testers', 'developer_team', 'support_interval']))

            if pbar:
                pbar.update()

    def mean_stage_loss(self):
        df_all = json_normalize(self._metadata_dict, record_path=['event_metadata'],
                                meta=[['model', 'deployment_cadence'],
                                      ['model', 'team_size']],
                                errors='ignore')

        df_all.set_index(['model.deployment_cadence',
                          'model.team_size'], inplace=True)

        df_all.sort_index(inplace=True)

        df_all = df_all[(df_all['event_type'] == 'end')
                        ][['event', 'loss', 'status']]

        df_all['event'] = Categorical(df_all['event'], categories=[
            e.value for e in WorkflowStateName], ordered=True)

        team_samples = df_all.groupby(['model.team_size'])

        fig, axs = plt.subplots(len(team_samples), sharex=True, sharey=True)

        axs_i = 0

        for name, team_sample in team_samples:
            ax = axs[axs_i] if isinstance(axs, np.ndarray) else axs
            axs_i += 1

            df = team_sample.groupby(
                ['event', 'model.deployment_cadence']).mean(numeric_only=True)['loss'].unstack(level=['model.deployment_cadence'])

            df.plot.bar(ax=ax,
                        xlabel='SDLC Workflow Stage', ylabel='Mean Loss', legend=None)

            ax.set_title(label=f"Team Size={name[0]}", fontsize=8)
            ax.yaxis.set_inverted(True)
            ax.yaxis.set_major_formatter(
                ticker.PercentFormatter(xmax=1.0, decimals=1))

            if axs_i == 1:
                fig.legend(title='Deployment Cadence')

        fig.suptitle("Mean Stage Loss")

        plt.xticks(rotation=45)
        plt.show()

    def resource_utilization(self):

        df_all = json_normalize(self._metadata_dict, record_path=['resource_metadata'],
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

        fig, axs = plt.subplots(len(dataframes.items()),
                                sharex=True, sharey=True)

        labels = ['Over Capacity', 'Idle',
                  'Productive', 'Failure', 'Unplanned Work']
        axs_i = 0

        for key, group in dataframes.items():

            group = group.groupby(['state']).sum()[
                ['waiting_t', 'idle_t', 'success_t', 'failure_t', 'interruption_t']]

            df = group.divide(group.sum(axis=1), axis=0)

            ax = axs[axs_i] if isinstance(axs, np.ndarray) else axs
            axs_i += 1
            df.plot(ax=ax, kind='bar', stacked=True,
                    xlabel='SDLC Workflow Stage', legend=False)
            ax.set_title(
                label=f"Cadence={key[0]},Team Size={key[1]}", fontsize=8)

            ax.yaxis.set_major_formatter(
                ticker.PercentFormatter(xmax=1.0, decimals=1))

            if axs_i == 1:
                fig.legend(title='Utilization Category', labels=labels)

        fig.suptitle("Resource Utilization")

        plt.xticks(rotation=45)
        plt.show()

    @classmethod
    def _to_dict(cls, obj: Any, exclusions: list[str] = []):

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
