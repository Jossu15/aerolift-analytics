"""ORM models: wells, deliverability tests, production history, SCADA feed."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, \
    Integer, String

from api.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ApiKey(Base):
    """API credential - only the SHA-256 of the raw key is stored.

    The raw key is handed to the operator/historian once (mint_key script);
    every request must present it in the X-API-Key header.
    """
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    label = Column(String(128), nullable=False)
    field_name = Column(String(128))
    tier = Column(String(8), nullable=False, default="basic")  # basic | pro
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=_utcnow)


class Well(Base):
    __tablename__ = "wells"

    id = Column(Integer, primary_key=True)
    owner_key_id = Column(Integer, ForeignKey("api_keys.id"), index=True,
                          nullable=True)  # NULL = legacy/pre-auth row
    tag = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128))

    # Reservoir
    p_res = Column(Float, nullable=False)
    t_res_f = Column(Float, nullable=False)
    gamma_g = Column(Float, nullable=False)

    # Wellbore / operation defaults (SCADA can override rates live)
    p_wh = Column(Float, nullable=False)
    t_wh_f = Column(Float, nullable=False)
    tvd_ft = Column(Float, nullable=False)
    tubing_id_in = Column(Float, nullable=False)
    q_water_bpd = Column(Float, nullable=False, default=0.0)
    liquid_sg = Column(Float, nullable=False, default=1.0)
    q_gas_nominal_mscfd = Column(Float, nullable=False, default=0.0)

    # Physics model choices
    vlp_model = Column(String(32), nullable=False, default="beggs_brill")
    load_method = Column(String(16), nullable=False, default="turner")

    # Field calibration of the Beggs-Brill friction gradient
    # (1.0 = virgin correlation; >1 rough/scaled tubing)
    friction_multiplier = Column(Float, nullable=False, default=1.0,
                                 server_default="1.0")

    # Houpeurt coefficients (used when no deliverability test is stored)
    a_coef = Column(Float)
    b_coef = Column(Float)

    created_at = Column(DateTime, default=_utcnow)


class DeliverabilityTest(Base):
    """One row per well - the current 4-point (or n-point) test."""
    __tablename__ = "deliverability_tests"

    id = Column(Integer, primary_key=True)
    well_id = Column(Integer, ForeignKey("wells.id"), unique=True,
                     nullable=False, index=True)
    points = Column(JSON, nullable=False)  # [{"pwf_psia": .., "q_mscfd": ..}]
    created_at = Column(DateTime, default=_utcnow)


class ProductionRecord(Base):
    """Historical daily/monthly production row (CSV upload)."""
    __tablename__ = "production_records"

    id = Column(Integer, primary_key=True)
    well_id = Column(Integer, ForeignKey("wells.id"), nullable=False,
                     index=True)
    date = Column(String(10), nullable=False)  # ISO yyyy-mm-dd
    q_gas_mscfd = Column(Float, nullable=False)
    q_water_bpd = Column(Float)
    p_wh_psia = Column(Float)
    created_at = Column(DateTime, default=_utcnow)


class ScadaReading(Base):
    """Real-time telemetry pushed by the plant SCADA historian."""
    __tablename__ = "scada_readings"

    id = Column(Integer, primary_key=True)
    well_id = Column(Integer, ForeignKey("wells.id"), nullable=False,
                     index=True)
    ts = Column(DateTime, default=_utcnow, index=True)
    q_gas_mscfd = Column(Float, nullable=False)
    q_water_bpd = Column(Float)
    p_wh_psia = Column(Float)
    # Engine verdict snapshot at ingestion time:
    is_loading = Column(Boolean, nullable=False)
    margin_fraction = Column(Float)
    severity = Column(String(16))
