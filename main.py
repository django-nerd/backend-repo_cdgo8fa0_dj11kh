import os
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from jose import jwt, JWTError
from passlib.context import CryptContext

from database import db, create_document, get_documents
from schemas import (
    Admin, Teacher, Student, Classroom, Enrollment,
    Announcement, Circular, Event, EventRegistration,
    StudyMaterial, Assignment, Submission,
    AttendanceRecord, PerformanceReview,
    AuthUser, TimetableEntry, Exam, Notification, AuditLog
)

app = FastAPI(title="School/College Management API", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Auth & Security -------------------- #
SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def collection_name(model_cls) -> str:
    return model_cls.__name__.lower()


def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    d = {**doc}
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    # Convert datetime/date objects to ISO
    for k, v in list(d.items()):
        if hasattr(v, 'isoformat'):
            try:
                d[k] = v.isoformat()
            except Exception:
                pass
    return d


def serialize_list(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [serialize_doc(d) for d in docs]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterPayload(BaseModel):
    email: str
    password: str
    role: str
    ref_id: Optional[str] = None


class LoginPayload(BaseModel):
    email: str
    password: str


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Return decoded JWT user if present, else None. Does not enforce auth to preserve existing flows."""
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload  # contains: sub(email), role, ref_id
    except JWTError:
        return None


def require_roles(*roles: str):
    async def _dep(user: Optional[Dict[str, Any]] = Depends(get_current_user)):
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        if roles and user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="Forbidden for role")
        return user
    return _dep


# -------------------- Static files & Uploads -------------------- #
UPLOAD_DIR = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=UPLOAD_DIR), name="static")


# -------------------- Audit Middleware -------------------- #
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    start = datetime.utcnow()
    user = None
    try:
        user = await get_current_user(request)
    except Exception:
        user = None
    response = await call_next(request)
    try:
        if db is not None:
            log = AuditLog(
                user_id=(user or {}).get("ref_id"),
                role=(user or {}).get("role"),
                action="request",
                path=str(request.url.path),
                method=request.method,
                status=response.status_code,
                ip=request.client.host if request.client else None,
            )
            create_document(collection_name(AuditLog), log)
    except Exception:
        pass
    return response


# -------------------- Meta endpoints -------------------- #

@app.get("/")
def read_root():
    return {"message": "School/College Management Backend is running"}


@app.get("/schema")
def get_schema():
    models = [
        Admin, Teacher, Student, Classroom, Enrollment,
        Announcement, Circular, Event, EventRegistration,
        StudyMaterial, Assignment, Submission,
        AttendanceRecord, PerformanceReview,
        AuthUser, TimetableEntry, Exam, Notification, AuditLog
    ]
    return {m.__name__: m.model_json_schema() for m in models}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:50]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# -------------------- Auth endpoints -------------------- #

@app.post("/auth/register", response_model=Dict[str, str])
def register_user(payload: RegisterPayload):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    existing = db[collection_name(AuthUser)].find_one({"email": payload.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = AuthUser(email=payload.email, password_hash=hash_password(payload.password), role=payload.role, ref_id=payload.ref_id)
    uid = create_document(collection_name(AuthUser), doc)
    return {"id": uid}


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginPayload):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    user = db[collection_name(AuthUser)].find_one({"email": payload.email})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({
        "sub": user.get("email"),
        "role": user.get("role"),
        "ref_id": str(user.get("_id")) if user.get("_id") else user.get("ref_id")
    })
    return TokenResponse(access_token=token)


# -------------------- Admin endpoints -------------------- #

@app.post("/admin/teachers")
def add_teacher(payload: Teacher, user=Depends(get_current_user)):
    teacher_id = create_document(collection_name(Teacher), payload)
    return {"id": teacher_id}


@app.get("/admin/teachers")
def list_teachers(user=Depends(get_current_user)):
    docs = get_documents(collection_name(Teacher))
    return serialize_list(docs)


@app.post("/admin/announcements")
def add_announcement(payload: Announcement, user=Depends(get_current_user)):
    ann_id = create_document(collection_name(Announcement), payload)
    return {"id": ann_id}


@app.get("/admin/announcements")
def list_announcements(user=Depends(get_current_user)):
    docs = get_documents(collection_name(Announcement))
    docs.sort(key=lambda d: (not d.get("pinned", False), d.get("created_at", datetime.min)), reverse=False)
    return serialize_list(docs)


@app.post("/admin/circulars")
def add_circular(payload: Circular, user=Depends(get_current_user)):
    cid = create_document(collection_name(Circular), payload)
    return {"id": cid}


@app.get("/admin/circulars")
def list_circulars(user=Depends(get_current_user)):
    docs = get_documents(collection_name(Circular))
    return serialize_list(docs)


@app.post("/admin/events")
def add_event(payload: Event, user=Depends(get_current_user)):
    eid = create_document(collection_name(Event), payload)
    return {"id": eid}


@app.get("/admin/events")
def list_events(user=Depends(get_current_user)):
    docs = get_documents(collection_name(Event))
    docs.sort(key=lambda d: d.get("starts_at", datetime.min))
    return serialize_list(docs)


@app.post("/admin/performance")
def add_performance_review(payload: PerformanceReview, user=Depends(get_current_user)):
    rid = create_document(collection_name(PerformanceReview), payload)
    return {"id": rid}


@app.get("/admin/performance")
def list_performance_reviews(user=Depends(get_current_user)):
    docs = get_documents(collection_name(PerformanceReview))
    return serialize_list(docs)


# -------------------- Teacher endpoints -------------------- #

@app.post("/teachers/students")
def add_student(payload: Student, user=Depends(get_current_user)):
    sid = create_document(collection_name(Student), payload)
    return {"id": sid}


@app.get("/teachers/students")
def list_students(department: str | None = None, year: int | None = None, section: str | None = None, user=Depends(get_current_user)):
    filt: Dict[str, Any] = {}
    if department: filt["department"] = department
    if year: filt["year"] = year
    if section: filt["section"] = section
    docs = get_documents(collection_name(Student), filter_dict=filt or None)
    return serialize_list(docs)


@app.post("/teachers/classes")
def add_classroom(payload: Classroom, user=Depends(get_current_user)):
    cid = create_document(collection_name(Classroom), payload)
    return {"id": cid}


@app.get("/teachers/classes")
def list_classrooms(department: str | None = None, year: int | None = None, section: str | None = None, user=Depends(get_current_user)):
    filt: Dict[str, Any] = {}
    if department: filt["department"] = department
    if year: filt["year"] = year
    if section: filt["section"] = section
    docs = get_documents(collection_name(Classroom), filter_dict=filt or None)
    return serialize_list(docs)


@app.post("/teachers/materials")
def add_material(payload: StudyMaterial, user=Depends(get_current_user)):
    mid = create_document(collection_name(StudyMaterial), payload)
    return {"id": mid}


@app.get("/teachers/materials")
def list_materials(class_id: str | None = None, user=Depends(get_current_user)):
    filt = {"class_id": class_id} if class_id else None
    docs = get_documents(collection_name(StudyMaterial), filter_dict=filt)
    return serialize_list(docs)


@app.post("/teachers/assignments")
def add_assignment(payload: Assignment, user=Depends(get_current_user)):
    aid = create_document(collection_name(Assignment), payload)
    return {"id": aid}


@app.get("/teachers/assignments")
def list_assignments(class_id: str | None = None, user=Depends(get_current_user)):
    filt = {"class_id": class_id} if class_id else None
    docs = get_documents(collection_name(Assignment), filter_dict=filt)
    return serialize_list(docs)


class ApproveAttendancePayload(BaseModel):
    record_id: str
    approved_by: str


@app.post("/teachers/attendance/approve")
def approve_attendance(payload: ApproveAttendancePayload, user=Depends(get_current_user)):
    from bson import ObjectId
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        res = db[collection_name(AttendanceRecord)].update_one(
            {"_id": ObjectId(payload.record_id)},
            {"$set": {"approved": True, "approved_by": payload.approved_by, "updated_at": datetime.utcnow()}}
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Attendance record not found")
        return {"status": "approved", "updated": res.modified_count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Grade submission
class GradePayload(BaseModel):
    submission_id: str
    score: float
    graded_by: str


@app.post("/teachers/submissions/grade")
def grade_submission(payload: GradePayload, user=Depends(get_current_user)):
    from bson import ObjectId
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    try:
        res = db[collection_name(Submission)].update_one(
            {"_id": ObjectId(payload.submission_id)},
            {"$set": {"score": payload.score, "graded_by": payload.graded_by, "updated_at": datetime.utcnow()}}
        )
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Submission not found")
        return {"status": "graded", "updated": res.modified_count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# -------------------- Student endpoints -------------------- #

@app.post("/students/attendance")
def mark_attendance(payload: AttendanceRecord, user=Depends(get_current_user)):
    rid = create_document(collection_name(AttendanceRecord), payload)
    return {"id": rid, "approved": False}


@app.get("/students/materials")
def student_materials(class_id: str, user=Depends(get_current_user)):
    docs = get_documents(collection_name(StudyMaterial), filter_dict={"class_id": class_id})
    return serialize_list(docs)


@app.get("/students/assignments")
def student_assignments(class_id: str, user=Depends(get_current_user)):
    docs = get_documents(collection_name(Assignment), filter_dict={"class_id": class_id})
    return serialize_list(docs)


@app.post("/students/submissions")
def submit_assignment(payload: Submission, user=Depends(get_current_user)):
    sid = create_document(collection_name(Submission), payload)
    return {"id": sid}


@app.get("/students/submissions")
def list_submissions(assignment_id: Optional[str] = None, student_id: Optional[str] = None, user=Depends(get_current_user)):
    filt: Dict[str, Any] = {}
    if assignment_id:
        filt["assignment_id"] = assignment_id
    if student_id:
        filt["student_id"] = student_id
    docs = get_documents(collection_name(Submission), filter_dict=filt or None)
    return serialize_list(docs)


# -------------------- Common/Feed/Event Registration -------------------- #

@app.get("/feed")
def feed(user=Depends(get_current_user)):
    anns = serialize_list(get_documents(collection_name(Announcement)))
    cirs = serialize_list(get_documents(collection_name(Circular)))
    evts = serialize_list(get_documents(collection_name(Event)))
    return {"announcements": anns, "circulars": cirs, "events": evts}


class RegisterEventPayload(BaseModel):
    user_id: str
    role: str


@app.post("/events/{event_id}/register")
def register_event(event_id: str, payload: RegisterEventPayload, user=Depends(get_current_user)):
    reg = EventRegistration(event_id=event_id, user_id=payload.user_id, role=payload.role)
    rid = create_document(collection_name(EventRegistration), reg)
    return {"id": rid}


# -------------------- Timetable & Exams -------------------- #

@app.post("/teachers/timetable")
def add_timetable_entry(entry: TimetableEntry, user=Depends(get_current_user)):
    tid = create_document(collection_name(TimetableEntry), entry)
    return {"id": tid}


@app.get("/timetable")
def get_timetable(class_id: str, user=Depends(get_current_user)):
    docs = get_documents(collection_name(TimetableEntry), filter_dict={"class_id": class_id})
    docs.sort(key=lambda d: (d.get("day_of_week", 0), d.get("start_time", "")))
    return serialize_list(docs)


@app.post("/teachers/exams")
def add_exam(exam: Exam, user=Depends(get_current_user)):
    eid = create_document(collection_name(Exam), exam)
    return {"id": eid}


@app.get("/exams")
def get_exams(class_id: str, user=Depends(get_current_user)):
    docs = get_documents(collection_name(Exam), filter_dict={"class_id": class_id})
    docs.sort(key=lambda d: (d.get("date", datetime.min), d.get("start_time", "")))
    return serialize_list(docs)


# -------------------- Attendance Reports & CSV -------------------- #

@app.get("/reports/attendance")
def attendance_report(class_id: str, start: Optional[date] = None, end: Optional[date] = None, format: str = "json", user=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    filt: Dict[str, Any] = {"class_id": class_id}
    if start or end:
        rng: Dict[str, Any] = {}
        if start:
            rng["$gte"] = start
        if end:
            rng["$lte"] = end
        filt["date"] = rng
    records = list(db[collection_name(AttendanceRecord)].find(filt))
    # Aggregate per student_id
    summary: Dict[str, Dict[str, int]] = {}
    for r in records:
        sid = r.get("student_id")
        status = r.get("status", "present")
        if sid not in summary:
            summary[sid] = {"present": 0, "absent": 0, "late": 0, "excused": 0, "total": 0}
        summary[sid][status] = summary[sid].get(status, 0) + 1
        summary[sid]["total"] += 1
    rows = [(sid, v["present"], v["absent"], v["late"], v["excused"], v["total"]) for sid, v in summary.items()]
    if format == "csv":
        def gen():
            yield "student_id,present,absent,late,excused,total\n"
            for row in rows:
                yield ",".join(map(str, row)) + "\n"
        return StreamingResponse(gen(), media_type="text/csv")
    # json
    return [{"student_id": sid, "present": p, "absent": a, "late": l, "excused": e, "total": t} for sid, p, a, l, e, t in rows]


# -------------------- Performance Dashboard -------------------- #

@app.get("/dashboards/teacher-performance")
def teacher_performance_dashboard(department: Optional[str] = None, start: Optional[str] = None, end: Optional[str] = None, user=Depends(get_current_user)):
    filt: Dict[str, Any] = {}
    if department:
        filt["department"] = department
    # get teachers
    teachers = get_documents(collection_name(Teacher), filter_dict=filt or None)
    t_ids = set(str(t.get("_id")) for t in teachers)
    # get reviews
    reviews = get_documents(collection_name(PerformanceReview))
    agg: Dict[str, Dict[str, Any]] = {}
    for r in reviews:
        tid = r.get("teacher_id")
        if t_ids and tid not in t_ids:
            continue
        entry = agg.setdefault(tid, {"count": 0, "sum": 0.0, "avg": 0.0})
        score = float(r.get("score", 0))
        entry["count"] += 1
        entry["sum"] += score
        entry["avg"] = round(entry["sum"] / entry["count"], 2)
    # attach teacher info
    result = []
    t_map = {str(t.get("_id")): t for t in teachers}
    for tid, met in agg.items():
        t = t_map.get(tid, {})
        result.append({
            "teacher_id": tid,
            "teacher_name": t.get("name"),
            "department": t.get("department"),
            **met
        })
    return result


# -------------------- Metadata pickers -------------------- #

@app.get("/meta/departments")
def list_departments(user=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    deps = db[collection_name(Classroom)].distinct("department")
    return sorted([d for d in deps if d])


@app.get("/meta/years")
def list_years(user=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    years = db[collection_name(Classroom)].distinct("year")
    return sorted([y for y in years if y is not None])


@app.get("/meta/sections")
def list_sections(department: Optional[str] = None, year: Optional[int] = None, user=Depends(get_current_user)):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    filt: Dict[str, Any] = {}
    if department:
        filt["department"] = department
    if year is not None:
        filt["year"] = year
    secs = db[collection_name(Classroom)].distinct("section", filt or None)
    return sorted([s for s in secs if s])


# -------------------- File upload -------------------- #

@app.post("/upload")
async def upload_file(file: UploadFile = File(...), user=Depends(get_current_user)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename required")
    name, ext = os.path.splitext(file.filename)
    safe = name.replace(" ", "_").replace("/", "_")[:64]
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    filename = f"{safe}_{ts}{ext}"
    dest = os.path.join(UPLOAD_DIR, filename)
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)
    url = f"/static/{filename}"
    return {"file_url": url, "filename": filename}


# -------------------- Notifications -------------------- #

@app.post("/notify")
def send_notification(payload: Notification, user=Depends(get_current_user)):
    nid = create_document(collection_name(Notification), payload)
    return {"id": nid}


# -------------------- Run -------------------- #

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
