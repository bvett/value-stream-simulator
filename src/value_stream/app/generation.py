"""Pure, bounded materialization independent of batch ordering."""

import hashlib
import itertools
import json
import math
import random
from decimal import Decimal
from uuid import UUID, uuid5
from pydantic import ValidationError
from value_stream.service.schemas import (
    DeveloperInput,
    ModelInput,
    QAPoolInput,
    ToolchainPoolInput,
    TaskInput,
)
from .errors import AppError
from .schemas import (
    ConstantValue,
    TaskSetSpec,
    ModelSettings,
    ScenarioDefinition,
    SweepRange,
    ConcreteScenario,
    GENERATOR_VERSION,
)
from .settings import AppSettings


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str
    )


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def derive_seed(domain, *values):
    # JSON numbers remain exactly representable in the browser.
    return int(fingerprint([GENERATOR_VERSION, domain, *values])[:13], 16)


def materialize_tasks(spec: TaskSetSpec):
    rng = random.Random(derive_seed("tasks", spec.seed))

    def sample(value):
        return (
            value.value
            if isinstance(value, ConstantValue)
            else rng.uniform(value.minimum, value.maximum)
        )

    return [
        TaskInput(
            task_name=str(i + 1),
            initial_value=sample(spec.initial_value),
            story_points=sample(spec.story_points),
            depreciation_rate=spec.depreciation_rate,
        )
        for i in range(spec.count)
    ]


def materialize_team(settings: ModelSettings, seed: int):
    low, high, n = settings.efficiency_min, settings.efficiency_max, settings.team_size
    rng = random.Random(derive_seed("team", seed, low, high, settings.distribution))
    values = []
    for i in range(n):
        if low == high:
            value = low
        elif settings.distribution == "linear":
            value = (
                low + (high - low) / 2 if n == 1 else low + (high - low) * (i / (n - 1))
            )
        else:
            while True:
                value = rng.gauss(low + (high - low) / 2, (high - low) / 6)
                if low <= value <= high:
                    break
        values.append(DeveloperInput(name=f"Developer {i + 1}", efficiency=value))
    return values


def concrete_model(settings: ModelSettings, seed: int):
    return ModelInput(
        developer_team=materialize_team(settings, seed),
        deployment_cadence=settings.deployment_cadence,
        qa_testers=QAPoolInput(
            limit=settings.qa_size,
            time_cost=settings.qa_time_cost,
            failure_rate=settings.qa_failure_rate,
            failure_cost=settings.qa_failure_cost,
        ),
        toolchain_pool=ToolchainPoolInput(
            limit=settings.toolchain_size,
            deployment_duration=settings.deployment_duration,
            failure_rate=settings.deployment_failure_rate,
        ),
        support_interval=settings.support_interval,
        support_task_story_points=settings.support_task_story_points,
    )


def axis_values(axis, limit):
    if isinstance(axis, SweepRange):
        start, end, step = (Decimal(str(v)) for v in (axis.start, axis.end, axis.step))
        if start > end:
            raise AppError("INVALID_INPUT", "Sweep start must not exceed end")
        span = (end - start) / step
        if span >= limit:
            raise AppError(
                "LIMIT_EXCEEDED", f"Each sweep can contain at most {limit} values"
            )
        count = int(span) + 1
        values = [float(start + step * i) for i in range(count)]
    else:
        if len(axis) > limit:
            raise AppError(
                "LIMIT_EXCEEDED", f"Each sweep can contain at most {limit} values"
            )
        values = list(dict.fromkeys(axis))
    if not values:
        raise AppError("INVALID_INPUT", "A sweep needs at least one value")
    return values


def validate_model_limits(settings, limits):
    if (
        max(settings.team_size, settings.qa_size, settings.toolchain_size)
        > limits.max_resources
    ):
        raise AppError(
            "LIMIT_EXCEEDED", f"Resource counts must not exceed {limits.max_resources}"
        )


def expand_scenarios(definitions: list[ScenarioDefinition], limits: AppSettings):
    axes = []
    count = 0
    if len(definitions) > limits.max_definitions:
        raise AppError("LIMIT_EXCEEDED", "Too many definitions")
    for definition in definitions:
        unknown = set(definition.sweeps) - ModelSettings.model_fields.keys()
        if unknown:
            raise AppError(
                "INVALID_INPUT",
                f"Unknown sweep properties: {', '.join(sorted(unknown))}",
            )
        values = {
            k: axis_values(v, limits.max_axis_values)
            for k, v in sorted(definition.sweeps.items())
        }
        count += math.prod(len(v) for v in values.values())
        if count > limits.max_models:
            raise AppError(
                "LIMIT_EXCEEDED",
                f"Sweep produces more than {limits.max_models} models. Reduce the sweep or configure a higher limit.",
            )
        axes.append(values)
    scenarios = []
    seen = set()
    for definition, values in zip(definitions, axes):
        for combination in itertools.product(*values.values()):
            changed = dict(zip(values, combination))
            try:
                settings = ModelSettings.model_validate(
                    {**definition.settings.model_dump(), **changed}
                )
            except ValidationError as exc:
                raise AppError(
                    "INVALID_INPUT",
                    "Invalid sweep combination",
                    details={
                        "definition": definition.name,
                        "values": changed,
                        "issues": str(exc),
                    },
                ) from exc
            validate_model_limits(settings, limits)
            identity = canonical(settings.model_dump())
            scenario_id = uuid5(definition.id, identity)
            if scenario_id in seen:
                continue
            seen.add(scenario_id)
            label = ", ".join(
                f"{k.replace('_', ' ')}={getattr(settings, k)}" for k in changed
            )
            scenarios.append(
                ConcreteScenario(
                    id=scenario_id,
                    definition_id=definition.id,
                    revision=definition.revision,
                    name=f"{definition.name} · {label}" if label else definition.name,
                    settings=settings,
                    team_seed=definition.team_seed,
                    execution_seed=derive_seed(
                        "simulation", definition.execution_seed, str(scenario_id)
                    ),
                    model=concrete_model(settings, definition.team_seed),
                )
            )
    return scenarios
