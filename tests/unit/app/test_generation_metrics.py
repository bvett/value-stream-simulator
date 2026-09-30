import unittest
from value_stream.app.errors import AppError
from value_stream.app.generation import (
    materialize_tasks,
    materialize_team,
    expand_scenarios,
)
from value_stream.app.metrics import loss_percent, plot_data, reduce_points
from value_stream.app.schemas import (
    TaskSetSpec,
    ModelSettings,
    ScenarioDefinition,
    SweepRange,
)
from value_stream.app.settings import AppSettings
from value_stream.service.schemas import (
    ResultData,
    SummaryData,
    MetadataData,
    TaskEventData,
    ResourceMetadataData,
)


class TestGeneration(unittest.TestCase):
    def test_repeatable_tasks_and_teams(self):
        spec = TaskSetSpec(
            story_points={"kind": "uniform", "minimum": 0.5, "maximum": 2}
        )
        self.assertEqual(materialize_tasks(spec), materialize_tasks(spec))
        for distribution in ["normal", "linear"]:
            settings = ModelSettings(team_size=10, distribution=distribution)
            team = materialize_team(settings, 42)
            self.assertEqual(team, materialize_team(settings, 42))
            self.assertTrue(all(0.5 <= d.efficiency <= 1.5 for d in team))
        self.assertEqual(
            materialize_team(ModelSettings(team_size=1), 42)[0].efficiency, 1
        )
        short = materialize_team(ModelSettings(team_size=2, distribution="normal"), 42)
        self.assertEqual(
            short,
            materialize_team(ModelSettings(team_size=4, distribution="normal"), 42)[:2],
        )

    def test_sweep_order_identity_and_shared_teams(self):
        definition = ScenarioDefinition(
            sweeps={"team_size": [2, 4], "deployment_cadence": [1, 5]}
        )
        first = expand_scenarios([definition], AppSettings())
        definition.sweeps["team_size"] = [4, 2]
        second = expand_scenarios([definition], AppSettings())
        self.assertEqual({s.id: s for s in first}, {s.id: s for s in second})
        self.assertEqual(len(first), 4)
        self.assertEqual(first[0].model.developer_team, first[2].model.developer_team)
        definition.sweeps = {
            "deployment_duration": SweepRange(start=0.1, end=0.3, step=0.1)
        }
        self.assertEqual(
            [
                s.settings.deployment_duration
                for s in expand_scenarios([definition], AppSettings())
            ],
            [0.1, 0.2, 0.3],
        )

    def test_normal_extreme_finite_bounds_and_duplicate_values(self):
        settings = ModelSettings(
            efficiency_min=1e308, efficiency_max=1.5e308, distribution="normal"
        )
        team = materialize_team(settings, 42)
        self.assertTrue(all(1e308 <= d.efficiency <= 1.5e308 for d in team))
        scenarios = expand_scenarios(
            [ScenarioDefinition(sweeps={"team_size": [2, "2", 4]})], AppSettings()
        )
        self.assertEqual([s.settings.team_size for s in scenarios], [2, 4])

    def test_limits_before_materialization(self):
        definition = ScenarioDefinition(
            sweeps={
                "team_size": list(range(1, 30)),
                "deployment_cadence": list(range(30)),
            }
        )
        with self.assertRaisesRegex(AppError, "more than 500"):
            expand_scenarios([definition], AppSettings())
        definition.sweeps = {
            "deployment_duration": SweepRange(start=0, end=1e308, step=1e-308)
        }
        with self.assertRaisesRegex(AppError, "at most"):
            expand_scenarios([definition], AppSettings())
        definition.sweeps = {"team_size": [1.5]}
        with self.assertRaises(AppError):
            expand_scenarios([definition], AppSettings())


class TestMetrics(unittest.TestCase):
    def test_weighted_loss_stage_visits_and_request_backlog(self):
        self.assertEqual(loss_percent(4, 2), 50)
        self.assertIsNone(loss_percent(0, 0))
        model = expand_scenarios([ScenarioDefinition()], AppSettings())[0].model
        events = [
            TaskEventData(
                event="development",
                event_type="end",
                time=1,
                status=status,
                loss=loss,
                task_type="development",
                is_rework=False,
            )
            for status, loss in [("success", -0.1), ("failure", -0.3)]
        ]
        records = [
            ResourceMetadataData(
                time=0, state="development", waiting=1, allocated=1, active=0
            ),
            ResourceMetadataData(
                time=2,
                state="development",
                waiting=-1,
                allocated=0,
                active=0,
                idle_t=2,
                success_t=4,
                interruption_t=2,
            ),
        ]
        result = ResultData(
            model_index=0,
            model=model,
            summary_result=SummaryData(
                completion_time=4, total_delivered_value=2, loss=-0.5
            ),
            metadata=MetadataData(event_metadata=events, resource_metadata=records),
        )
        metrics = plot_data(result, 4)
        self.assertEqual(metrics.stages[0].loss_percent, 20)
        self.assertEqual(metrics.stages[0].visits, 2)
        self.assertEqual(metrics.activity[0].shares["success_t"], 50)
        self.assertEqual(metrics.backlog[0].waiting, [0, 1, 0, 0])

    def test_reduction_retains_extrema_and_ends(self):
        points = [(float(i), 100 if i == 5523 else i % 11) for i in range(20000)]
        reduced = reduce_points(points)
        self.assertLessEqual(len(reduced), 5000)
        self.assertIn((5523.0, 100), reduced)
        self.assertEqual(reduced[0], points[0])
        self.assertEqual(reduced[-1], points[-1])


class TestObservations(unittest.TestCase):
    def test_suggestions_have_evidence_and_zero_value_has_no_proposals(self):
        from value_stream.app.insights import observations
        from value_stream.app.schemas import (
            PlotData,
            StageLoss,
            Backlog,
            ResourceActivity,
        )

        metrics = PlotData(
            loss_percent=30,
            stages=[
                StageLoss(
                    stage="qa_complete",
                    label="Waiting for deployment",
                    loss_percent=20,
                    visits=8,
                )
            ],
            backlog=[
                Backlog(stage="qa_testing", label="QA", time=[0, 2], waiting=[0, 4])
            ],
            activity=[
                ResourceActivity(
                    stage="qa_testing",
                    label="QA",
                    durations={"failure_t": 3},
                    shares={},
                )
            ],
        )
        settings = ModelSettings(qa_failure_rate=0.4, qa_size=2, qa_failure_cost=0, 
                                 toolchain_size=1, deployment_failure_rate=0, support_interval=None,
                                 support_task_story_points=1)
        suggestions = observations(metrics, settings)
        self.assertEqual(
            [(s.property, s.value) for s in suggestions],
            [("deployment_cadence", 2), ("qa_size", 3), ("qa_failure_rate", 0.2)],
        )
        self.assertTrue(all(s.evidence for s in suggestions))
        metrics.loss_percent = None
        self.assertTrue(
            all(s.property is None for s in observations(metrics, settings))
        )
