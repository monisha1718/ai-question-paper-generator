"""
FastAPI application – exposes REST endpoints for authentication, PDF upload,
question-paper generation, chat history, and file downloads.
"""

import os
import shutil
import logging
from typing import List

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from .database import get_db, init_db
from .models import (
    ChatHistory,
    ChatHistoryResponse,
    ChatMessage,
    DownloadRequest,
    RoleEnum,
    TokenResponse,
    User,
    UserCreate,
    UserLogin,
    UserResponse,
)
from .pdf_processor import process_pdf
from .question_generator import (
    export_to_docx,
    export_to_pdf,
    generate_question_paper,
)

# ── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App setup ───────────────────────────────────────────────────────────
app = FastAPI(title="Question Paper AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.on_event("startup")
def on_startup():
    init_db()
    # Seed a default HOD user if the database is empty
    from .database import SessionLocal
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            default_users = [
                User(
                    username="hod",
                    hashed_password=hash_password("hod123"),
                    name="Dr. Admin",
                    department="Computer Science",
                    assigned_subject="All",
                    role=RoleEnum.HOD,
                ),
                User(
                    username="prof1",
                    hashed_password=hash_password("prof123"),
                    name="Prof. Sharma",
                    department="Computer Science",
                    assigned_subject="Data Structures",
                    role=RoleEnum.PROFESSOR,
                ),
                User(
                    username="assoc1",
                    hashed_password=hash_password("assoc123"),
                    name="Dr. Patel",
                    department="Computer Science",
                    assigned_subject="Operating Systems",
                    role=RoleEnum.ASSOCIATE_PROFESSOR,
                ),
                User(
                    username="asst1",
                    hashed_password=hash_password("asst123"),
                    name="Ms. Gupta",
                    department="Computer Science",
                    assigned_subject="Database Management",
                    role=RoleEnum.ASSISTANT_PROFESSOR,
                ),
            ]
            db.add_all(default_users)
            db.commit()
            logger.info("Seeded default users into the database.")
    finally:
        db.close()


# ── Auth endpoints ──────────────────────────────────────────────────────

@app.post("/api/register", response_model=UserResponse, status_code=201)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new faculty member."""
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(
        username=user_data.username,
        hashed_password=hash_password(user_data.password),
        name=user_data.name,
        department=user_data.department,
        assigned_subject=user_data.assigned_subject,
        role=user_data.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/login", response_model=TokenResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """Authenticate a user and return a JWT."""
    user = db.query(User).filter(User.username == credentials.username).first()
    if not user or not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(data={"sub": user.username})
    return TokenResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@app.get("/api/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)):
    """Return the profile of the currently logged-in user."""
    return current_user


# ── PDF upload ──────────────────────────────────────────────────────────

@app.post("/api/upload-pdf")
def upload_pdf(
    subject: str = Query(..., description="Subject name for the PDF"),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a PDF, extract text, create embeddings, and store in FAISS."""
    # Role-based access check
    if current_user.role != RoleEnum.HOD and current_user.assigned_subject.lower() != subject.lower():
        raise HTTPException(
            status_code=403,
            detail="You can only upload material for your assigned subject.",
        )

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Save the uploaded file
    safe_filename = file.filename.replace(" ", "_")
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        num_chunks = process_pdf(file_path, subject)
    except Exception as e:
        logger.exception("Error processing PDF")
        raise HTTPException(status_code=500, detail=f"PDF processing failed: {e}")

    # Save an assistant chat message noting the upload
    _save_chat(db, current_user.id, "assistant",
               f"PDF '{file.filename}' processed successfully. "
               f"Created {num_chunks} text chunks for subject '{subject}'.")

    return {
        "message": "PDF uploaded and processed successfully.",
        "filename": file.filename,
        "chunks_created": num_chunks,
        "subject": subject,
    }


# ── Question paper generation ──────────────────────────────────────────

@app.post("/api/generate")
def generate(
    subject: str = Query(...),
    unit_or_topic: str = Query(...),
    exam_type: str = Query(...),
    marks_distribution: str = Query(None),
    regenerate: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate (or regenerate) a question paper for a subject."""
    if current_user.role != RoleEnum.HOD and current_user.assigned_subject.lower() != subject.lower():
        raise HTTPException(
            status_code=403,
            detail="You can only generate papers for your assigned subject.",
        )

    paper = generate_question_paper(
        subject=subject,
        unit_or_topic=unit_or_topic,
        exam_type=exam_type,
        marks_distribution=marks_distribution,
        regenerate=regenerate,
    )

    _save_chat(db, current_user.id, "user",
               f"Generate {'(regenerate) ' if regenerate else ''}question paper for "
               f"{subject} – {unit_or_topic} ({exam_type})")
    _save_chat(db, current_user.id, "assistant", paper)

    return {"question_paper": paper}


# ── Download endpoints ──────────────────────────────────────────────────

@app.post("/api/download/pdf")
def download_pdf(
    body: DownloadRequest,
    current_user: User = Depends(get_current_user),
):
    """Return the question paper as a downloadable PDF."""
    pdf_bytes = export_to_pdf(body.paper_text, body.subject, body.unit_or_topic, body.exam_type)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=question_paper_{body.subject}.pdf"},
    )


@app.post("/api/download/docx")
def download_docx(
    body: DownloadRequest,
    current_user: User = Depends(get_current_user),
):
    """Return the question paper as a downloadable DOCX."""
    docx_bytes = export_to_docx(body.paper_text, body.subject, body.unit_or_topic, body.exam_type)
    return Response(
        content=docx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=question_paper_{body.subject}.docx"},
    )


# ── Chat history ────────────────────────────────────────────────────────

@app.get("/api/chat-history", response_model=List[ChatHistoryResponse])
def chat_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the chat history for the logged-in user."""
    records = (
        db.query(ChatHistory)
        .filter(ChatHistory.user_id == current_user.id)
        .order_by(ChatHistory.timestamp.asc())
        .all()
    )
    return records


@app.post("/api/chat")
def chat(
    body: ChatMessage,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Simple chat endpoint. Saves the user message and returns a
    context-aware assistant response using RAG if material is available.
    """
    _save_chat(db, current_user.id, "user", body.message)

    # Determine subject for RAG context
    subject = current_user.assigned_subject if current_user.role != RoleEnum.HOD else ""

    from .rag_pipeline import query_rag
    if subject and subject.lower() != "all":
        answer = query_rag(subject, body.message)
    else:
        answer = (
            "As HOD, please specify the subject when generating a question paper. "
            "Use the question paper generation flow to get started."
        )

    _save_chat(db, current_user.id, "assistant", answer)
    return {"reply": answer}


# ── Helpers ─────────────────────────────────────────────────────────────

def _save_chat(db: Session, user_id: int, role: str, message: str):
    record = ChatHistory(user_id=user_id, role=role, message=message)
    db.add(record)
    db.commit()
