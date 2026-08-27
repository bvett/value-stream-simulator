from typing import Any
from matplotlib import ticker
import matplotlib.pyplot as plt
from pandas import json_normalize
from ..simulation_result import SimulationResultV2
from .viewer_v2 import ViewerV2


class ResultViewer(ViewerV2):
    def __init__(self, results: list[SimulationResultV2], colormap='plasma'):
        super().__init__(colormap)

        self._results_dict: list[Any] = []

        for r in results:
            self._results_dict.append(super()._to_dict(
                r.summary_result, ['toolchain_pool', 'qa_testers', 'developer_team', 'support_interval']))

        self.data = json_normalize(self._results_dict,
                                   meta=[['model', 'deployment_cadence'],
                                         ['model', 'team_size']],
                                   errors='ignore')

        self.data.set_index(['model.deployment_cadence',
                             'model.team_size'], inplace=True)

    def loss_vs_cadence(self):
        df = self.data

        df = df[['loss', 'total_delivered_value']].unstack(-1)[['loss']]

        df.columns = df.columns.get_level_values(1)  # type: ignore

        ax = df.plot(title="Loss vs Cadence", xlabel="Cadence",
                     ylabel="Loss", grid=True, colormap=self.colormap)

        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())

        plt.legend(title="Team Size")
        plt.gca().invert_xaxis()
        ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1.0))
        plt.show()

    def loss_vs_team_size(self):

        df = self.data

        df = df[['loss']].unstack(0)

        df.columns = df.columns.get_level_values(1)  # type: ignore

        ax = df.plot(title="Loss vs Team Size",
                     xlabel="Team Size", ylabel='Loss', grid=True,
                     colormap=self.colormap)
        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
        plt.legend(title="Deployment Cadence")
        ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1.0))
        plt.show()
