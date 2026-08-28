"""Pydantic request/response schemas (v2)."""

import datetime as _dt
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, \
    model_validator

VLP_MODELS = ("beggs_brill", "dry_rk2", "avg_tz")
LOAD_METHODS = ("turner", "coleman")
WELL_TYPES = ("gas", "oil")


# ------------------------------------------------------------------
# Wells
# ------------------------------------------------------------------
class WellBase(BaseModel):
    tag: str = Field(min_length=1, max_length=64)
    name: Optional[str] = None

    p_res: float = Field(gt=0, description="Reservoir pressure, psia")
    t_res_f: float = Field(description="Reservoir temperature, deg F")
    gamma_g: float = Field(gt=0.5, lt=1.6,
                           description="Gas specific gravity (air=1)")

    p_wh: float = Field(gt=0, description="Wellhead pressure, psia")
    t_wh_f: float = Field(description="Surface temperature, deg F")
    tvd_ft: float = Field(gt=0, description="True vertical depth, ft")
    tubing_id_in: float = Field(gt=0.5, lt=2.0, description="Tubing ID, in")

    q_water_bpd: float = Field(default=0.0, ge=0)
    liquid_sg: float = Field(default=1.0, gt=0)
    q_gas_nominal_mscfd: float = Field(default=0.0, ge=0)

    vlp_model: str = Field(default="beggs_brill")
    load_method: str = Field(default="turner")

    friction_multiplier: float = Field(
        default=1.0, gt=0.0, le=10.0,
        description="Beggs-Brill friction calibration (1.0 = virgin)")

    well_type: str = Field(default="gas",
                           description="'gas' or 'oil' (Fase I)")
    oil_api: Optional[float] = Field(
        default=None, gt=6.0, le=70.0,
        description="Oil API gravity (required when well_type=oil)")

    a_coef: Optional[float] = Field(
        default=None, description="Houpeurt a [psia^2/(Mscf/D)]")
    b_coef: Optional[float] = Field(
        default=None, description="Houpeurt b [psia^2/(Mscf/D)^2]")

    @field_validator("tag")
    @classmethod
    def _tag_strip(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("tag must not be blank")
        return v

    @field_validator("vlp_model")
    @classmethod
    def _vlp_valid(cls, v):
        if v not in VLP_MODELS:
            raise ValueError("vlp_model must be one of {}".format(VLP_MODELS))
        return v

    @field_validator("load_method")
    @classmethod
    def _method_valid(cls, v):
        if v not in LOAD_METHODS:
            raise ValueError(
                "load_method must be one of {}".format(LOAD_METHODS))
        return v

    @model_validator(mode="after")
    def _oil_api_required_for_oil(self):
        if self.well_type == "oil" and self.oil_api is None:
            raise ValueError("oil_api is required when well_type='oil'")
        return self


class WellCreate(WellBase):
    pass


class WellUpdate(BaseModel):
    """Partial update - all fields optional."""
    name: Optional[str] = None
    p_res: Optional[float] = Field(default=None, gt=0)
    t_res_f: Optional[float] = None
    gamma_g: Optional[float] = Field(default=None, gt=0.5, lt=1.6)
    p_wh: Optional[float] = Field(default=None, gt=0)
    t_wh_f: Optional[float] = None
    tvd_ft: Optional[float] = Field(default=None, gt=0)
    tubing_id_in: Optional[float] = Field(default=None, gt=0.5, lt=2.0)
    q_water_bpd: Optional[float] = Field(default=None, ge=0)
    liquid_sg: Optional[float] = Field(default=None, gt=0)
    q_gas_nominal_mscfd: Optional[float] = Field(default=None, ge=0)
    vlp_model: Optional[str] = None
    load_method: Optional[str] = None
    friction_multiplier: Optional[float] = Field(default=None, gt=0.0,
                                                 le=10.0)
    well_type: Optional[str] = None
    oil_api: Optional[float] = Field(default=None, gt=6.0, le=70.0)
    a_coef: Optional[float] = None
    b_coef: Optional[float] = None

    @field_validator("well_type")
    @classmethod
    def _wtype_valid(cls, v):
        if v is not None and v not in WELL_TYPES:
            raise ValueError("well_type must be one of {}".format(
                WELL_TYPES))
        return v


class WellOut(WellBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_key_id: Optional[int] = None
    created_at: Optional[_dt.datetime] = None


class AlertOut(BaseModel):
    """Dashboard semaphore alert for a single well portfolio."""
    well_id: int
    tag: str
    severity: str  # green | yellow | orange | red
    status: str    # stable | at_risk | metastable | loaded
    message: str
    margin_pct: Optional[float] = None
    days_to_risk: Optional[int] = None
    v_actual_ft_s: Optional[float] = None
    v_crit_ft_s: Optional[float] = None
    q_crit_mscfd: Optional[float] = None
    metastable_regime: Optional[str] = None
    q_min_stable_mscfd: Optional[float] = None


# ------------------------------------------------------------------
# Deliverability test
# ------------------------------------------------------------------
class DeliverabilityTestIn(BaseModel):
    pwf_psia: List[float] = Field(min_length=2)
    q_mscfd: List[float] = Field(min_length=2)


class DeliverabilityTestOut(DeliverabilityTestIn):
    fitted_C: Optional[float] = None
    fitted_n: Optional[float] = None
    fit_ok: bool = False


# ------------------------------------------------------------------
# Production history / CSV upload
# ------------------------------------------------------------------
class ProductionRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: str
    q_gas_mscfd: float
    q_water_bpd: Optional[float] = None
    p_wh_psia: Optional[float] = None
    pwf_psia: Optional[float] = None


class HistoryUploadResult(BaseModel):
    records_added: int
    records_skipped: int
    errors: List[str] = []


# ------------------------------------------------------------------
# SCADA telemetry
# ------------------------------------------------------------------
class TelemetryIn(BaseModel):
    well_tag: str = Field(min_length=1, max_length=64)
    q_gas_mscfd: float = Field(gt=0)
    q_water_bpd: Optional[float] = Field(default=None, ge=0)
    p_wh_psia: Optional[float] = Field(default=None, gt=0)
    ts: Optional[_dt.datetime] = None


class TelemetryOut(BaseModel):
    well_tag: str
    ts: _dt.datetime
    is_loading: bool
    margin_pct: float
    severity: str
    headline: str
    first_action: Optional[str] = None
    bhfp_psia: Optional[float] = None


class ScadaStatusOut(TelemetryOut):
    last_reading_ts: Optional[_dt.datetime] = None
