from typing import Any
from matplotlib import ticker
import matplotlib.pyplot as plt
from pandas import json_normalize
from value_stream.simulation import SimulationResult
from .viewer import Viewer


class ResultViewer(Viewer):
    def __init__(self, results: list[SimulationResult], colormap='plasma'):
        super().__init__(colormap)
        self._results_dict: list[Any] = []
      
        for result in results:
            self._results_dict.append(result.model_dump())

        self.data = json_normalize(self._results_dict, 
                                   meta=[['summary_result', 'model', 'deployment_cadence'],
                                         ['summary_result', 'model', 'team_size']],
                                   errors='ignore',
                                   record_prefix='')

        self.data.set_index(['summary_result.model.deployment_cadence',
                             'summary_result.model.team_size'], inplace=True)

    def loss_vs_cadence(self):
        df = self.data

        df = df[['summary_result.loss', 'summary_result.total_delivered_value']].unstack(-1)[['summary_result.loss']]

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

        df = df[['summary_result.loss']].unstack(0)

        df.columns = df.columns.get_level_values(1)  # type: ignore

        ax = df.plot(title="Loss vs Team Size",
                     xlabel="Team Size", ylabel='Loss', grid=True,
                     colormap=self.colormap)
        ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
        plt.legend(title="Deployment Cadence")
        ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1.0))
        plt.show()
