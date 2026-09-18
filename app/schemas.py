"""Strict API contracts shared by every GridPilot pipeline stage."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
FiniteNonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Hour = Annotated[int, Field(ge=0, le=23)]


class StrictModel(BaseModel):
    """Base model that rejects undocumented input and non-finite numbers."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)


class HealthResponse(StrictModel):
    status: Literal["ok"]


class HourlyInput(StrictModel):
    hour: Hour
    demand_kwh: FiniteNonNegative
    solar_kwh: FiniteNonNegative
    tariff_bdt_per_kwh: FiniteNonNegative


class BatteryConfig(StrictModel):
    capacity_kwh: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    initial_energy_kwh: FiniteNonNegative
    minimum_energy_kwh: FiniteNonNegative
    max_charge_kwh: FiniteNonNegative = Field(
        validation_alias=AliasChoices("max_charge_kwh_per_hour", "max_charge_kwh"),
        serialization_alias="max_charge_kwh_per_hour",
    )
    max_discharge_kwh: FiniteNonNegative = Field(
        validation_alias=AliasChoices("max_discharge_kwh_per_hour", "max_discharge_kwh"),
        serialization_alias="max_discharge_kwh_per_hour",
    )

    @model_validator(mode="after")
    def validate_energy_bounds(self) -> BatteryConfig:
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh cannot exceed capacity_kwh")
        if not self.minimum_energy_kwh <= self.initial_energy_kwh <= self.capacity_kwh:
            raise ValueError(
                "initial_energy_kwh must be between minimum_energy_kwh and capacity_kwh"
            )
        return self


class OptimizeEnergyRequest(StrictModel):
    scenario_id: NonEmptyString
    operator_notes: Annotated[list[NonEmptyString], Field(min_length=1, max_length=3)]
    hourly_data: Annotated[
        list[HourlyInput],
        Field(
            min_length=24,
            max_length=24,
            validation_alias=AliasChoices("hours", "hourly_data"),
            serialization_alias="hours",
        ),
    ]
    battery: BatteryConfig

    @model_validator(mode="after")
    def validate_hourly_series(self) -> OptimizeEnergyRequest:
        hours = [entry.hour for entry in self.hourly_data]
        if hours != list(range(24)):
            raise ValueError("hourly_data must contain hours 0 through 23 exactly once, in order")
        return self


class DirectiveType(str, Enum):
    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


class HoursAdjustment(StrictModel):
    hours: Annotated[list[Hour], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_hours(self) -> HoursAdjustment:
        if self.hours != sorted(set(self.hours)):
            raise ValueError("hours must be unique and sorted")
        return self


class SolarReductionAdjustment(HoursAdjustment):
    factor: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class MinimumBatteryReserveAdjustment(HoursAdjustment):
    minimum_energy_kwh: FiniteNonNegative


class MaxGridAdjustment(HoursAdjustment):
    max_grid_kwh: FiniteNonNegative


StructuredAdjustment = (
    SolarReductionAdjustment
    | MinimumBatteryReserveAdjustment
    | MaxGridAdjustment
    | HoursAdjustment
)


class DirectiveInterpretation(StrictModel):
    note_index: Annotated[int, Field(ge=0)]
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: StructuredAdjustment | None
    explanation: NonEmptyString

    @model_validator(mode="after")
    def validate_directive_shape(self) -> DirectiveInterpretation:
        expected_types: dict[DirectiveType, type[StrictModel] | None] = {
            DirectiveType.SOLAR_REDUCTION: SolarReductionAdjustment,
            DirectiveType.MINIMUM_BATTERY_RESERVE: MinimumBatteryReserveAdjustment,
            DirectiveType.NO_CHARGE_WINDOW: HoursAdjustment,
            DirectiveType.NO_DISCHARGE_WINDOW: HoursAdjustment,
            DirectiveType.MAX_GRID_WINDOW: MaxGridAdjustment,
            DirectiveType.NO_OP: None,
        }
        expected = expected_types[self.directive_type]
        if self.directive_type is DirectiveType.NO_OP:
            if self.applies or self.structured_adjustment is not None:
                raise ValueError("no_op must have applies=false and structured_adjustment=null")
            return self
        if not self.applies:
            raise ValueError("only no_op may have applies=false")
        if expected is None or type(self.structured_adjustment) is not expected:
            raise ValueError(
                f"{self.directive_type.value} requires a {expected.__name__} adjustment"
            )
        return self


class BatteryAction(str, Enum):
    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"


class HourlyPlan(StrictModel):
    hour: Hour
    grid_kwh: FiniteNonNegative
    solar_used_kwh: FiniteNonNegative
    battery_action: BatteryAction
    battery_kwh: FiniteNonNegative
    battery_energy_after_kwh: FiniteNonNegative

    @model_validator(mode="after")
    def validate_idle_action(self) -> HourlyPlan:
        if self.battery_action is BatteryAction.IDLE and self.battery_kwh != 0:
            raise ValueError("idle battery_action requires battery_kwh=0")
        return self


class OptimizeEnergyResponse(StrictModel):
    scenario_id: NonEmptyString
    interpretations: Annotated[
        list[DirectiveInterpretation],
        Field(
            min_length=1,
            max_length=3,
            validation_alias=AliasChoices("directive_interpretation", "interpretations"),
            serialization_alias="directive_interpretation",
        ),
    ]
    hourly_plan: Annotated[list[HourlyPlan], Field(min_length=24, max_length=24)]
    total_grid_kwh: FiniteNonNegative
    total_cost_bdt: FiniteNonNegative
    peak_grid_kwh: FiniteNonNegative
    summary: NonEmptyString = Field(
        validation_alias=AliasChoices("plan_summary", "summary"),
        serialization_alias="plan_summary",
    )

    @model_validator(mode="after")
    def validate_ordering(self) -> OptimizeEnergyResponse:
        note_indices = [item.note_index for item in self.interpretations]
        if note_indices != list(range(len(self.interpretations))):
            raise ValueError("interpretations must be in contiguous note_index order")
        hours = [entry.hour for entry in self.hourly_plan]
        if hours != list(range(24)):
            raise ValueError("hourly_plan must contain hours 0 through 23 exactly once, in order")
        return self
