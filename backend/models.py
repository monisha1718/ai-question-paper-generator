"""
SQLAlchemy ORM models and Pydantic schemas for the application.
"""

import datetime
from enum import Enum as PyEnum
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


# ── SQLAlchemy ORM Models ───────────────────────────────────────────────

class RoleEnum(str, PyEnum):
    HOD = "HOD"
    PROFESSOR = "Professor"
    ASSOCIATE_PROFESSOR = "Associate Professor"
    ASSISTANT_PROFESSOR = "Assistant Professor"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(128), nullable=False)
    name = Column(String(100), nullable=False)
    department = Column(String(100), nullable=False)
    assigned_subject = Column(String(100), nullable=False)
    role = Column(Enum(RoleEnum), nullable=False)

    chat_histories = relationship("ChatHistory", back_populates="user")


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="chat_histories")


# ── Pydantic Schemas ────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str
    password: str
    name: str
    department: str
    assigned_subject: str
    role: RoleEnum


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    department: str
    assigned_subject: str
    role: RoleEnum

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ChatMessage(BaseModel):
    message: str


class QuestionPaperRequest(BaseModel):
    subject: str
    unit_or_topic: str
    exam_type: str  # "Internal" or "Semester"
    marks_distribution: Optional[str] = None


class ChatHistoryResponse(BaseModel):
    id: int
    role: str
    message: str
    timestamp: datetime.datetime

    class Config:
        from_attributes = True


class DownloadRequest(BaseModel):
    paper_text: str
    subject: str
    unit_or_topic: str = "General"
    exam_type: str = "Semester"
