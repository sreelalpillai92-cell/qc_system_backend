from fastapi import FastAPI, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from datetime import datetime
import os
import shutil
from pypdf import PdfWriter
from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

# Database setup (SQLite for Render)
DATABASE_URL = "sqlite:///./database.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Database models
class Project(Base):
    __tablename__ = "project"
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String, nullable=False)
    project_code = Column(String, unique=True, nullable=False)
    location = Column(String)
    production_logs = relationship("ProductionLog", back_populates="project")
    qc_logs = relationship("QCLog", back_populates="project")


class ProductionLog(Base):
    __tablename__ = "production_log"
    id = Column(Integer, primary_key=True, index=True)
    panel_id = Column(String, unique=True, nullable=False)
    product_type = Column(String)
    quantity = Column(Integer)
    project_id = Column(Integer, ForeignKey("project.id"))
    project = relationship("Project", back_populates="production_logs")
    qc_logs = relationship("QCLog", back_populates="production_log")


class QCLog(Base):
    __tablename__ = "qc_log"
    id = Column(Integer, primary_key=True, index=True)
    panel_id = Column(String, nullable=False)
    inspection_date = Column(DateTime, default=datetime.utcnow)
    inspector_name = Column(String)
    status = Column(String, default="Pending")
    remarks = Column(Text)
    project_id = Column(Integer, ForeignKey("project.id"))
    production_log_id = Column(Integer, ForeignKey("production_log.id"))
    project = relationship("Project", back_populates="qc_logs")
    production_log = relationship("ProductionLog", back_populates="qc_logs")


class ChecklistTemplate(Base):
    __tablename__ = "checklist_template"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("project.id"))
    template_name = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)


class MIRMaster(Base):
    __tablename__ = "mir_master"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("project.id"))
    mir_number = Column(String, unique=True, nullable=False)
    status = Column(String, default="Draft")
    created_at = Column(DateTime, default=datetime.utcnow)


class MIRPanel(Base):
    __tablename__ = "mir_panel"
    id = Column(Integer, primary_key=True, index=True)
    mir_id = Column(Integer, ForeignKey("mir_master.id"))
    panel_id = Column(String, nullable=False)

class MIRTemplate(Base):
    __tablename__ = "mir_template"
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("project.id"))
    template_name = Column(String, nullable=False)
    template_type = Column(String, default="cover_page")  # cover_page, panel_list, custom
    file_path = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)


# Create tables
Base.metadata.create_all(bind=engine)

# FastAPI app
app = FastAPI(title="QAQC System", version="0.1.0")


# Pydantic models
class ProjectCreate(BaseModel):
    project_name: str
    project_code: str
    location: str | None = None


class ProductionLogCreate(BaseModel):
    panel_id: str
    product_type: str
    quantity: int
    project_id: int


class QCLogCreate(BaseModel):
    panel_id: str
    inspector_name: str
    remarks: str | None = None
    project_id: int
    production_log_id: int


# Database session dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Helper functions
def generate_mir_number(project_code: str, db_session) -> str:
    """Generate sequential MIR number for a project"""
    last_mir = (
        db_session.query(MIRMaster)
        .filter(MIRMaster.mir_number.like(f"{project_code}-MIR-%"))
        .order_by(MIRMaster.id.desc())
        .first()
    )

    if last_mir:
        last_num = int(last_mir.mir_number.split("-")[-1])
        new_num = last_num + 1
    else:
        new_num = 1

    return f"MIR-{new_num:04d}"


def create_mir_folder(project_id: int, mir_number: str, panel_ids: list[str], db_session):
    """Create folder structure for MIR with subfolders and index"""
    project = db_session.query(Project).filter(Project.id == project_id).first()
    if not project:
        return

    mir_folder = f"storage/project_{project_id}/MIR/{project.project_code}-{mir_number}"
    os.makedirs(mir_folder, exist_ok=True)

    subfolders = ["source_files", "merged_pdf", "final_mir"]
    for subfolder in subfolders:
        os.makedirs(f"{mir_folder}/{subfolder}", exist_ok=True)

    index_file = f"{mir_folder}/index.txt"
    with open(index_file, "w") as f:
        f.write(f"MIR Number: {project.project_code}-{mir_number}\n")
        f.write(f"Project: {project.project_name}\n")
        f.write(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("\nPanel IDs:\n")
        for panel_id in panel_ids:
            f.write(f"  - {panel_id}\n")


def attach_documents_to_mir(project_id: int, mir_number: str, panel_ids: list[str]):
    """Copy all documents from production logs to MIR source_files folder"""
    mir_folder = f"storage/project_{project_id}/MIR/{project_id}-{mir_number}"
    source_files_folder = f"{mir_folder}/source_files"
    os.makedirs(source_files_folder, exist_ok=True)

    for panel_id in panel_ids:
        panel_folder = f"storage/project_{project_id}/production_logs/{panel_id}"
        if not os.path.exists(panel_folder):
            continue

        for subfolder in ["checklists", "drawings", "photos"]:
            source_path = f"{panel_folder}/{subfolder}"

            if os.path.exists(source_path) and os.path.isdir(source_path):
                for filename in os.listdir(source_path):
                    file_path = os.path.join(source_path, filename)
                    if os.path.isfile(file_path):
                        dest_filename = f"{panel_id}_{subfolder}_{filename}"
                        dest_path = os.path.join(source_files_folder, dest_filename)
                        shutil.copy2(file_path, dest_path)


def merge_mir_pdfs(project_id: int, mir_number: str, db_session):
    """Merge all PDFs from source_files into FINAL_MIR.pdf"""
    project = db_session.query(Project).filter(Project.id == project_id).first()
    if not project:
                return None
    
    base_path = f"storage/project_{project_id}/MIR/{project.project_code}-{mir_number}"
    mir_path = f"{base_path}/source_files"
    output_pdf = f"{base_path}/FINAL_MIR.pdf"
    if not os.path.exists(mir_path):
        return None

    merger = PdfWriter()

    ordered_groups = ["MIR_FORM_", "PANEL_LIST_", "CHECKLIST", "DRAWING_", "PHOTO"]
    files = os.listdir(mir_path)

    for group in ordered_groups:
        for file in sorted(files):
            if file.endswith(".pdf") and group in file:
                merger.append(os.path.join(mir_path, file))

    with open(output_pdf, "wb") as output_file:
        merger.write(output_file)

    merger.close()
    return output_pdf


# API Routes
@app.get("/projects")
def list_projects(db=Depends(get_db)):
    projects = db.query(Project).all()
    return projects


@app.post("/projects")
def create_project(project: ProjectCreate, db=Depends(get_db)):
    db_project = Project(
        project_name=project.project_name,
        project_code=project.project_code,
        location=project.location,
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)

    project_folder = f"storage/project_{db_project.id}"
    os.makedirs(f"{project_folder}/production_logs", exist_ok=True)
    os.makedirs(f"{project_folder}/MIR", exist_ok=True)

    return db_project


@app.post("/production-logs")
def create_production_log(log: ProductionLogCreate, db=Depends(get_db)):
    db_log = ProductionLog(
        panel_id=log.panel_id,
        product_type=log.product_type,
        quantity=log.quantity,
        project_id=log.project_id,
    )
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log


@app.get("/qc-logs")
def list_qc_logs(db=Depends(get_db)):
    qc_logs = db.query(QCLog).all()
    return qc_logs


@app.post("/qc-logs/{qc_log_id}/approve")
def approve_qc_log(qc_log_id: int, db=Depends(get_db)):
    qc_log = db.query(QCLog).filter(QCLog.id == qc_log_id).first()
    if not qc_log:
        raise HTTPException(status_code=404, detail="QC Log not found")

    qc_log.status = "Approved"
    db.commit()
    return {"message": "QC Log approved", "qc_log_id": qc_log_id, "status": "Approved"}


@app.post("/projects/{project_id}/checklist-template")
def upload_checklist_template(project_id: int, template_name: str, db=Depends(get_db)):
    template = ChecklistTemplate(project_id=project_id, template_name=template_name)
    db.add(template)
    db.commit()
    db.refresh(template)
    return {"message": "Checklist template uploaded", "template_id": template.id}


@app.post("/projects/{project_id}/mir-template")
async def upload_mir_template(
    project_id: int,
    template_name: str,
    template_type: str = "cover_page",
    file: UploadFile = File(...),
    db=Depends(get_db)
):
    """Upload MIR template PDF for a project"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Create templates folder
    template_folder = f"storage/project_{project_id}/templates"
    os.makedirs(template_folder, exist_ok=True)
    
    # Save uploaded file
    file_path = f"{template_folder}/{template_type}_{file.filename}"
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    
    # Save template record in database
    template = MIRTemplate(
        project_id=project_id,
        template_name=template_name,
        template_type=template_type,
        file_path=file_path
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    
    return {
        "message": "MIR template uploaded successfully",
        "template_id": template.id,
        "file_path": file_path
    }

@app.post("/projects/{project_id}/mir")
def create_mir(project_id: int, panel_ids: list[str], db=Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    mir_number = generate_mir_number(project.project_code, db)

    mir = MIRMaster(project_id=project_id, mir_number=mir_number)
    db.add(mir)
    db.commit()
    db.refresh(mir)

    for panel in panel_ids:
        db.add(MIRPanel(mir_id=mir.id, panel_id=panel))
    db.commit()

    create_mir_folder(project_id, mir_number, panel_ids, db)
    
    # Generate PDF documents
    generate_mir_cover_page(project_id, mir_number, panel_ids, db)
    generate_panel_list_pdf(project_id, mir_number, panel_ids, db)
    attach_documents_to_mir(project_id, mir_number, panel_ids)
    final_pdf = merge_mir_pdfs(project_id, mir_number, db)

    mir.status = "Final" if final_pdf else "Ready"
    db.commit()

    return {
        "mir_number": mir_number,
        "status": mir.status,
        "folder_created": True,
        "pdf_merged": final_pdf is not None,
    }

# ============== PDF DOWNLOAD ENDPOINTS ==============

@app.get("/projects/{project_id}/mir/{mir_number}/pdf")
def download_mir_pdf(
    project_id: int,
    mir_number: str,
    view: bool = False,
    db = Depends(get_db)
):
    """
    Download or view MIR PDF file
    
    Args:
        project_id: Project ID number
        mir_number: MIR number (e.g., MIR-0001)
        view: If True, opens in browser. If False, downloads.
    
    Example URLs:
        Download: /projects/1/mir/MIR-0001/pdf
        View: /projects/1/mir/MIR-0001/pdf?view=true
    """
    from fastapi.responses import FileResponse
    from pathlib import Path
    
    # Get project to get project_code
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Build PDF path
    pdf_path = Path(f"storage/project_{project_id}/MIR/{project.project_code}-{mir_number}/FINAL_MIR.pdf")
    
    # Check if file exists
    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "MIR PDF not found",
                "project_id": project_id,
                "mir_number": mir_number,
                "expected_path": str(pdf_path)
            }
        )
    
    # Set headers for download or view
    disposition = "inline" if view else "attachment"
    headers = {
        "Content-Disposition": f'{disposition}; filename="{project.project_code}-{mir_number}.pdf"'
    }
    
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        headers=headers,
        filename=f"{project.project_code}-{mir_number}.pdf"
    )

@app.get("/projects/{project_id}/mir/list")
def list_project_mirs(project_id: int, db = Depends(get_db)):
    """
    List all available MIR PDFs for a project
    
    Returns information about all generated MIRs including:
    - MIR number
    - Status
    - File size
    - Download URL
    """
    from pathlib import Path
    
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    # Get all MIRs from database
    mirs = db.query(MIRMaster).filter(MIRMaster.project_id == project_id).all()
    
    result = []
    for mir in mirs:
        pdf_path = Path(f"storage/project_{project_id}/MIR/{project.project_code}-{mir.mir_number}/FINAL_MIR.pdf")
        
        mir_info = {
            "mir_number": mir.mir_number,
            "status": mir.status,
            "created_at": mir.created_at.isoformat() if mir.created_at else None,
            "pdf_exists": pdf_path.exists(),
            "download_url": f"/projects/{project_id}/mir/{mir.mir_number}/pdf" if pdf_path.exists() else None
        }
        
        if pdf_path.exists():
            mir_info["size_bytes"] = pdf_path.stat().st_size
            mir_info["size_mb"] = round(pdf_path.stat().st_size / (1024 * 1024), 2)
        
        result.append(mir_info)
    
    return {
        "project_id": project_id,
        "project_code": project.project_code,
        "mirs": result,
        "count": len(result)
    }

@app.get("/health")
def health_check():
    """
    Health check endpoint for monitoring
    """
    from pathlib import Path
    return {
        "status": "healthy",
        "service": "QC System Backend",
        "storage_accessible": Path("storage").exists()
    }
