"""Database CRUD helpers."""

from typing import List, Optional

from sqlalchemy.orm import Session

from api import models, schemas


# ---------------- Wells ----------------
def get_well(db: Session, well_id: int) -> Optional[models.Well]:
    return db.get(models.Well, well_id)


def get_well_by_tag(db: Session, tag: str) -> Optional[models.Well]:
    return db.query(models.Well).filter(
        models.Well.tag == tag).one_or_none()


def list_wells(db: Session, limit: int = 200,
               offset: int = 0,
               owner_key_id: Optional[int] = None) -> List[models.Well]:
    query = db.query(models.Well).order_by(models.Well.id)
    if owner_key_id is not None:
        query = query.filter(models.Well.owner_key_id == owner_key_id)
    return query.offset(offset).limit(limit).all()


def create_well(db: Session, data: schemas.WellCreate,
                owner_key_id: Optional[int] = None) -> models.Well:
    well = models.Well(**data.model_dump(), owner_key_id=owner_key_id)
    db.add(well)
    db.commit()
    db.refresh(well)
    return well


def update_well(db: Session, well: models.Well,
                data: schemas.WellUpdate) -> models.Well:
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(well, key, value)
    db.commit()
    db.refresh(well)
    return well


def delete_well(db: Session, well: models.Well) -> None:
    db.query(models.ProductionRecord).filter(
        models.ProductionRecord.well_id == well.id).delete()
    db.query(models.ScadaReading).filter(
        models.ScadaReading.well_id == well.id).delete()
    db.query(models.DeliverabilityTest).filter(
        models.DeliverabilityTest.well_id == well.id).delete()
    db.delete(well)
    db.commit()


# ---------------- Deliverability test ----------------
def get_test(db: Session, well_id: int) -> Optional[models.DeliverabilityTest]:
    return db.query(models.DeliverabilityTest).filter(
        models.DeliverabilityTest.well_id == well_id).one_or_none()


def replace_test(db: Session, well: models.Well,
                 points: List[dict]) -> models.DeliverabilityTest:
    row = get_test(db, well.id)
    if row is None:
        row = models.DeliverabilityTest(well_id=well.id)
        db.add(row)
    row.points = points
    db.commit()
    db.refresh(row)
    return row


# ---------------- Production history ----------------
def add_production_records(db: Session, well_id: int,
                           rows: List[dict]) -> int:
    for r in rows:
        db.add(models.ProductionRecord(well_id=well_id, **r))
    db.commit()
    return len(rows)


def list_production(db: Session, well_id: int,
                    limit: int = 5000) -> List[models.ProductionRecord]:
    return db.query(models.ProductionRecord).filter(
        models.ProductionRecord.well_id == well_id) \
        .order_by(models.ProductionRecord.date).limit(limit).all()


# ---------------- SCADA readings ----------------
def add_scada_reading(db: Session, reading: models.ScadaReading
                      ) -> models.ScadaReading:
    db.add(reading)
    db.commit()
    db.refresh(reading)
    return reading


def last_scada_reading(db: Session,
                       well_id: int) -> Optional[models.ScadaReading]:
    return db.query(models.ScadaReading).filter(
        models.ScadaReading.well_id == well_id) \
        .order_by(models.ScadaReading.ts.desc()).first()
