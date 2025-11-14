import os
from datetime import datetime
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import (
    Admin, Teacher, Student, Classroom, Enrollment,
    Announcement, Circular, Event, EventRegistration,
    StudyMaterial, Assignment, Submission,
    AttendanceRecord, PerformanceReview
)

app = FastAPI(title="School/College Management API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- Utilities -------------------- #

def collection_name(model_cls) -> str:
    return model_cls.__name__.lower()


def serialize_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    d = {**doc}
    if "_id" in d:
        d["id"] = str(d.pop("_id"))
    # Convert datetime objects to ISO
    for k, v in list(d.items()):
        if hasattr(v, 'isoformat'):
            try:
                d[k] = v.isoformat()
            except Exception:
                pass
    return d


def serialize_list(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [serialize_doc(d) for d in docs]


# -------------------- Meta endpoints -------------------- #

@app.get("/")
def read_root():
    return {"message": "School/College Management Backend is running"}


@app.get("/schema")
def get_schema():
    """Expose Pydantic schema definitions for the database viewer/tools."""
    models = [
        Admin, Teacher, Student, Classroom, Enrollment,
        Announcement, Circular, Event, EventRegistration,
        StudyMaterial, Assignment, Submission,
        AttendanceRecord, PerformanceReview
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
                response["collections"] = collections[:20]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# -------------------- Admin endpoints -------------------- #

@app.post("/admin/teachers")
def add_teacher(payload: Teacher):
    teacher_id = create_document(collection_name(Teacher), payload)
    return {"id": teacher_id}


@app.get("/admin/teachers")
def list_teachers():
    docs = get_documents(collection_name(Teacher))
    return serialize_list(docs)


@app.post("/admin/announcements")
def add_announcement(payload: Announcement):
    ann_id = create_document(collection_name(Announcement), payload)
    return {"id": ann_id}


@app.get("/admin/announcements")
def list_announcements():
    docs = get_documents(collection_name(Announcement))
    # Show pinned first, then by created_at desc
    docs.sort(key=lambda d: (not d.get("pinned", False), d.get("created_at", datetime.min)), reverse=False)
    return serialize_list(docs)


@app.post("/admin/circulars")
def add_circular(payload: Circular):
    cid = create_document(collection_name(Circular), payload)
    return {"id": cid}


@app.get("/admin/circulars")
def list_circulars():
    docs = get_documents(collection_name(Circular))
    return serialize_list(docs)


@app.post("/admin/events")
def add_event(payload: Event):
    eid = create_document(collection_name(Event), payload)
    return {"id": eid}


@app.get("/admin/events")
def list_events():
    docs = get_documents(collection_name(Event))
    # upcoming first
    docs.sort(key=lambda d: d.get("starts_at", datetime.min))
    return serialize_list(docs)


@app.post("/admin/performance")
def add_performance_review(payload: PerformanceReview):
    rid = create_document(collection_name(PerformanceReview), payload)
    return {"id": rid}


@app.get("/admin/performance")
def list_performance_reviews():
    docs = get_documents(collection_name(PerformanceReview))
    return serialize_list(docs)


# -------------------- Teacher endpoints -------------------- #

@app.post("/teachers/students")
def add_student(payload: Student):
    sid = create_document(collection_name(Student), payload)
    return {"id": sid}


@app.get("/teachers/students")
def list_students(department: str | None = None, year: int | None = None, section: str | None = None):
    filt: Dict[str, Any] = {}
    if department: filt["department"] = department
    if year: filt["year"] = year
    if section: filt["section"] = section
    docs = get_documents(collection_name(Student), filter_dict=filt or None)
    return serialize_list(docs)


@app.post("/teachers/classes")
def add_classroom(payload: Classroom):
    cid = create_document(collection_name(Classroom), payload)
    return {"id": cid}


@app.get("/teachers/classes")
def list_classrooms(department: str | None = None, year: int | None = None, section: str | None = None):
    filt: Dict[str, Any] = {}
    if department: filt["department"] = department
    if year: filt["year"] = year
    if section: filt["section"] = section
    docs = get_documents(collection_name(Classroom), filter_dict=filt or None)
    return serialize_list(docs)


@app.post("/teachers/materials")
def add_material(payload: StudyMaterial):
    mid = create_document(collection_name(StudyMaterial), payload)
    return {"id": mid}


@app.get("/teachers/materials")
def list_materials(class_id: str | None = None):
    filt = {"class_id": class_id} if class_id else None
    docs = get_documents(collection_name(StudyMaterial), filter_dict=filt)
    return serialize_list(docs)


@app.post("/teachers/assignments")
def add_assignment(payload: Assignment):
    aid = create_document(collection_name(Assignment), payload)
    return {"id": aid}


@app.get("/teachers/assignments")
def list_assignments(class_id: str | None = None):
    filt = {"class_id": class_id} if class_id else None
    docs = get_documents(collection_name(Assignment), filter_dict=filt)
    return serialize_list(docs)


class ApproveAttendancePayload(BaseModel):
    record_id: str
    approved_by: str


@app.post("/teachers/attendance/approve")
def approve_attendance(payload: ApproveAttendancePayload):
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


# -------------------- Student endpoints -------------------- #

@app.post("/students/attendance")
def mark_attendance(payload: AttendanceRecord):
    rid = create_document(collection_name(AttendanceRecord), payload)
    return {"id": rid, "approved": False}


@app.get("/students/materials")
def student_materials(class_id: str):
    docs = get_documents(collection_name(StudyMaterial), filter_dict={"class_id": class_id})
    return serialize_list(docs)


@app.get("/students/assignments")
def student_assignments(class_id: str):
    docs = get_documents(collection_name(Assignment), filter_dict={"class_id": class_id})
    return serialize_list(docs)


# -------------------- Common/Feed endpoints -------------------- #

@app.get("/feed")
def feed():
    anns = serialize_list(get_documents(collection_name(Announcement)))
    cirs = serialize_list(get_documents(collection_name(Circular)))
    evts = serialize_list(get_documents(collection_name(Event)))
    return {"announcements": anns, "circulars": cirs, "events": evts}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
