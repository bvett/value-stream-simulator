# demo.py: quick demonstration that runs a simulation and plots results in a variety of formats
# A more thorough walkthrough is available in the tutorial.ipynb notebook

import logging
import math

from tqdm import tqdm

from value_stream import Simulation, SimulationResult
from value_stream.utils import DeveloperFactory, ModelFactory, ResultViewer, TaskFactory

logger = logging.getLogger(__name__)

if __name__ == "__main__":

    logging.basicConfig(
        force=True, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO)

    # Arguments for the simulation.  Experiment by changing these and running the script.

    NUM_TASKS = 500
    # Task value decreases 2% for every unit of time from creation to delivery
    DEPRECIATION_RATE = 0.02

    # Simulations will have development team sizes between 1 and MAX_DEVELOPERS
    MAX_DEVELOPERS = 25

    NUM_QA_RESOURCES = 5

    # Simulate deployment schedules from every MAX_CADENCE units of time to 0 (continuous)
    MAX_CADENCE = 10

    # Number of deployments that can happen concurrently
    TOOLCHAIN_CONCURRENCY = 20

    # Duration of a deployment
    DEPLOYMENT_DURATION = .25

    # Create tasks with complexities between 0.5 and 2.0
    tasks = TaskFactory('sd', (.5, 2)).create(NUM_TASKS)

    # Create development teams with developers having efficiencies between 0.5 and 1.5
    developer_factory = DeveloperFactory('sd', (.5, 1.5))

    # Model includes the developer_teams and range of cadences
    models = ModelFactory(toolchain_concurrency=TOOLCHAIN_CONCURRENCY,
                          deployment_duration=DEPLOYMENT_DURATION,
                          developer_factory=developer_factory).create(
        teams=range(1, MAX_DEVELOPERS+1),
        deployment_cadences=range(MAX_CADENCE, -1, -1),
        num_qa_resources=NUM_QA_RESOURCES)

    # Run the simulation with a progress bar and collect the results
    results: list[SimulationResult] = []

    with tqdm(desc='Running Simulation', total=len(models)) as pbar:
        results.extend(Simulation().execute(tasks, models, pbar=pbar))

    # Showcase the results using different plots

    with tqdm(desc='Processing Results', total=len(results), mininterval=1.0, miniters=0) as pbar:
        viewer = ResultViewer(results, pbar=pbar)

    viewer.loss_vs_cadence(team_samples=5)
    viewer.time_alloc_vs_cadence()
    viewer.delivery_timeline(cadence=3, team_size=3)
    viewer.delivered_value_vs_time(
        cadence=1, team_samples=math.ceil(MAX_DEVELOPERS/4))
    viewer.delivered_value_vs_team_size(cadence_samples=5)
