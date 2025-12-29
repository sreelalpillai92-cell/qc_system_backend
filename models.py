from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from database import Base
from datetime import datetime

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    project_code = Column(String, nullable=False, default="UNKNOWN")
    qa_qc_engineer = Column(String, nullable=False)
    production_engineer = Column(String, nullable=False)
    foreman = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class ProductionLog(Base):
    __tablename__ = "production_logs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    panel_id = Column(String, nullable=False)
    activity = Column(String, nullable=False)
    quantity = Column(Integer, default=1)
    remarks = Column(String)
    log_date = Column(DateTime, default=datetime.utcnow)

class QCLog(Base):
    __tablename__ = "qc_logs"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    production_log_id = Column(Integer, ForeignKey("production_logs.id"))
    panel_id = Column(String, nullable=False)
    activity = Column(String, nullable=False)
    inspection_status = Column(String, default="Draft")
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    remarks = Column(String, nullable=True)

class ChecklistTemplate(Base):
    __tablename__ = "checklist_templates"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    checklist_type = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

class PanelChecklist(Base):
    __tablename__ = "panel_checklists"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    qc_log_id = Column(Integer, ForeignKey("qc_logs.id"))
    panel_id = Column(String, nullable=False)
    checklist_type = Column(String, nullable=False)
    generated_file_path = Column(String, nullable=False)
    status = Column(String, default="Draft")
    created_at = Column(DateTime, default=datetime.utcnow)

class MIRMaster(Base):
    __tablename__ = "mir_master"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    mir_number = Column(String, unique=True, nullable=False)
    status = Column(String, default="Draft")
    created_at = Column(DateTime, default=datetime.utcnow)

class MIRPanel(Base):
    __tablename__ = "mir_panels"

    id = Column(Integer, primary_key=True)
    mir_id = Column(Integer, ForeignKey("mir_master.id"))
    panel_id = Column(String, nullable=False)
