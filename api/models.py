"""ORM models: wells, deliverability tests, production history, SCADA feed."""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, \
    Integer, String, UniqueConstraint

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

    # Alert engine: per-well risk tolerance. The semaphore turns yellow
    # (at_risk) when the velocity margin falls below this % of q_crit.
    alert_margin_pct = Column(Float, nullable=False, default=20.0,
                              server_default="20.0")

    # Physics model choices
    vlp_model = Column(String(32), nullable=False, default="beggs_brill")
    load_method = Column(String(16), nullable=False, default="turner")

    # Field calibration of the Beggs-Brill friction gradient
    # (1.0 = virgin correlation; >1 rough/scaled tubing)
    friction_multiplier = Column(Float, nullable=False, default=1.0,
                                 server_default="1.0")

    # Oil-well extension (Fase I): "gas" | "oil"
    well_type = Column(String(8), nullable=False, default="gas",
                       server_default="gas")
    oil_api = Column(Float)          # API gravity when well_type=oil

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
    pwf_psia = Column(Float)  # optional measured BHFP - calibration input
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


class WellAlert(Base):
    """Persisted semaphore snapshot from the alert engine (Fase 1).

    One row per poll per well; /api/wells/alerts serves the latest row
    per owned well. `last_notified_severity` gates Slack fan-out so a
    well only pings once per severity level reached.
    """
    __tablename__ = "well_alerts"

    id = Column(Integer, primary_key=True)
    well_id = Column(Integer, ForeignKey("wells.id"), nullable=False,
                     index=True)
    computed_at = Column(DateTime, nullable=False, default=_utcnow,
                         index=True)
    source = Column(String(16), nullable=False, default="manual")
    severity = Column(String(8), nullable=False)   # green|yellow|orange|red
    status = Column(String(16), nullable=False)    # stable|at_risk|metastable|loaded
    message = Column(String(512), nullable=False)
    margin_pct = Column(Float)
    days_to_risk = Column(Integer)
    v_actual_ft_s = Column(Float)
    v_crit_ft_s = Column(Float)
    q_crit_mscfd = Column(Float)
    metastable_regime = Column(String(16))
    q_min_stable_mscfd = Column(Float)
    last_notified_severity = Column(String(8))


class TwinModel(Base):
    """Versioned digital-twin calibration row for one well (Fase 2.1).

    Every successful retrain of the residual forest inserts a new row;
    the previous ones keep their history and only `active` flips. The
    matrix lives in a joblib artifact (`ml_path`); Postgres is the source
    of truth for which version is current and why (metrics, data size).
    """
    __tablename__ = "twin_models"
    __table_args__ = (
        UniqueConstraint("well_id", "version", name="uq_twin_well_version"),
    )

    id = Column(Integer, primary_key=True)
    well_id = Column(Integer, ForeignKey("wells.id"), nullable=False,
                     index=True)
    version = Column(Integer, nullable=False)
    trained_at = Column(DateTime, nullable=False, default=_utcnow)
    active = Column(Boolean, nullable=False, default=True)
    source = Column(String(16), nullable=False, default="manual")
    # Data + fit quality (may be partial when a metric cannot be computed)
    n_points = Column(Integer, nullable=False)
    mae_psi = Column(Float)
    r2 = Column(Float)
    residual_mean_psi = Column(Float)
    residual_std_psi = Column(Float)
    features = Column(String(512), nullable=False, default="[]")
    ml_path = Column(String(512), nullable=False)

    @property
    def metrics(self) -> dict:
        return {
            "mae_psi": self.mae_psi,
            "r2": self.r2,
            "residual_mean_psi": self.residual_mean_psi,
            "residual_std_psi": self.residual_std_psi,
        }
