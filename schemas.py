"""
Database Schemas for School/College Management System

Each Pydantic model below maps to a MongoDB collection (class name lowercased).
Use these to validate data and as the source of truth for the application domain.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime

# Core identities
class Admin(BaseModel):
    name: str
    email: str

class Teacher(BaseModel):
    name: str
    email: str
    department: Optional[str] = None
    phone: Optional[str] = None
    join_date: Optional[date] = None

class Student(BaseModel):
    name: str
    email: str
    roll_number: str
    department: Optional[str] = None
    year: Optional[int] = Field(None, ge=1, le=8)
    section: Optional[str] = None
    phone: Optional[str] = None

# Academic structure
class Classroom(BaseModel):
    name: str
    department: Optional[str] = None
    year: Optional[int] = Field(None, ge=1, le=8)
    section: Optional[str] = None
    teacher_id: Optional[str] = Field(None, description="Class in-charge teacher id")

class Enrollment(BaseModel):
    class_id: str
    student_id: str
    active: bool = True

# Communications
class Announcement(BaseModel):
    title: str
    body: str
    audience: str = Field("all", description="all | students | teachers | department name | class id")
    author_id: Optional[str] = None
    pinned: bool = False

class Circular(BaseModel):
    title: str
    body: str
    audience: str = "all"
    author_id: Optional[str] = None

class Event(BaseModel):
    title: str
    description: Optional[str] = None
    starts_at: datetime
    ends_at: datetime
    location: Optional[str] = None
    audience: str = "all"
    host_id: Optional[str] = None

class EventRegistration(BaseModel):
    event_id: str
    user_id: str
    role: str = Field(..., description="student|teacher|admin")

# Learning resources and work
class StudyMaterial(BaseModel):
    class_id: str
    title: str
    description: Optional[str] = None
    file_url: Optional[str] = None
    uploaded_by: str

class Assignment(BaseModel):
    class_id: str
    title: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    type: str = Field("homework", description="homework|test|project|quiz")
    created_by: str

class Submission(BaseModel):
    assignment_id: str
    student_id: str
    file_url: Optional[str] = None
    text: Optional[str] = None
    score: Optional[float] = Field(None, ge=0)
    graded_by: Optional[str] = None

# Attendance and performance
class AttendanceRecord(BaseModel):
    class_id: str
    student_id: str
    date: date
    status: str = Field("present", description="present|absent|late|excused")
    marked_by: Optional[str] = Field(None, description="who marked (student or teacher id)")
    approved: bool = False
    approved_by: Optional[str] = None

class PerformanceReview(BaseModel):
    teacher_id: str
    reviewer_id: str
    period: str = Field(..., description="e.g., 2024-Q1")
    score: float = Field(..., ge=0, le=5)
    feedback: Optional[str] = None
