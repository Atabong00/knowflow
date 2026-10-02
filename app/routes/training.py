"""
Training / Quiz / Assessment Routes

Section 1-54 of the DDC HUB advanced training brief.

IMPORTANT: This module ONLY improves the Training, Quiz, Assessment, Scoring,
Progress, and Training Analytics functionality.  It does NOT touch the
authentication / Keycloak / OIDC / MFA / RBAC system in any way.  Authentication
is enforced exclusively through the existing `require_user` and `RoleRequirement`
dependencies which are themselves backed by the untouched Keycloak integration.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.auth.dependencies import require_user, RoleRequirement, AuthenticatedUser
from app.models.training import Course, Module, Assessment, Question, Attempt, Progress
from app.models.document import Document
from app.core.security import render_markdown_safely
from app.utils import slugify, log_audit
from app.core.logging_config import log_business_event
from app.schemas import (
    form_parser,
    CourseCreate, CourseUpdate,
    AssessmentCreate, AssessmentUpdate,
)
from app.services.scoring import ScoreService
from app.services.progress import ProgressService
from app.services.analytics import AnalyticsService
from app.services.seed import QuizGenerator, QUESTION_TEMPLATES

router = APIRouter(tags=["Training"])
templates = Jinja2Templates(directory="app/templates")

require_editor = RoleRequirement(allowed_roles=["Editor", "Admin"])
require_admin = RoleRequirement(allowed_roles=["Admin"])

DIFFICULTY_LEVELS = ["Beginner", "Intermediate", "Advanced"]
QUESTION_DIFFICULTIES = ["Easy", "Medium", "Hard"]
QUESTION_TYPES = ["multiple_choice", "true_false", "multiple_select"]
CATEGORIES = [
    "Cybersecurity", "Company Policies", "Health & Safety", "HR & Workplace",
    "Data Protection", "IT Systems", "Compliance", "Onboarding",
    "Professional Development",
]


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None


def _due_status(course: Course) -> dict:
    """Return due-date status info for a course (section 32)."""
    if not course.due_date:
        return {"has_due": False, "label": "", "overdue": False}
    now = datetime.utcnow()
    delta = (course.due_date - now).days
    if delta < 0:
        return {"has_due": True, "label": "Overdue", "overdue": True}
    return {"has_due": True, "label": f"Due in {delta} day{'s' if delta != 1 else ''}", "overdue": False}


def _user_training_stats(db: Session, user_id: str) -> dict:
    """Compute the employee training dashboard statistics (section 6)."""
    published_courses = db.query(Course).filter(Course.published.is_(True)).all()
    assigned = len(published_courses)

    progresses = (
        db.query(Progress)
        .filter(Progress.user_keycloak_id == user_id)
        .all()
    )

    completed = sum(1 for p in progresses if p.status in ("completed", "passed", "failed"))
    in_progress = sum(1 for p in progresses if p.status == "in_progress")
    not_started = assigned - (completed + in_progress)
    if not_started < 0:
        not_started = 0

    # Average score from best attempt per assessment
    assessments = db.query(Assessment).all()
    all_percentages = []
    passed_count = 0
    failed_count = 0
    for a in assessments:
        best = ScoreService.get_best_attempt(db, a.id, user_id)
        if best:
            all_percentages.append(best.percentage)
            if best.passed:
                passed_count += 1
            else:
                failed_count += 1

    avg_score = round(sum(all_percentages) / len(all_percentages)) if all_percentages else 0
    completion_rate = round((completed / assigned) * 100) if assigned > 0 else 0
    certificates = sum(1 for p in progresses if p.status == "passed")

    return {
        "assigned": assigned,
        "completed": completed,
        "in_progress": in_progress,
        "not_started": not_started,
        "average_score": avg_score,
        "completion_rate": completion_rate,
        "certificates": certificates,
        "assessments_passed": passed_count,
        "assessments_failed": failed_count,
    }


def _course_card_data(db: Session, course: Course, user_id: str) -> dict:
    """Compute data needed to render a single course card (section 5)."""
    module_count = len(course.modules)
    assessment_count = (
        len(course.assessments) +
        sum(1 for m in course.modules if m.assessment)
    )
    progress = ProgressService.get_progress(db, user_id, course.id)
    progress_pct = progress.progress_percentage if progress else 0
    status = progress.status if progress else "not_started"

    return {
        "course": course,
        "module_count": module_count,
        "assessment_count": assessment_count,
        "progress_percentage": progress_pct,
        "status": status,
        "due": _due_status(course),
    }


# ===========================================================================
# EMPLOYEE TRAINING ROUTES (protected by require_user only)
# ===========================================================================

@router.get("/training")
def training_dashboard(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Employee Training Dashboard (section 6)."""
    stats = _user_training_stats(db, user.keycloak_id)

    # Continue learning: last in-progress course module
    continue_learning = None
    progresses = (
        db.query(Progress)
        .filter(Progress.user_keycloak_id == user.keycloak_id,
                Progress.status == "in_progress")
        .all()
    )
    if progresses:
        prog = progresses[0]
        course = db.get(Course, prog.course_id)
        if course:
            completed = set(ProgressService.get_completed_modules(prog))
            next_module = None
            for m in course.modules:
                if m.id not in completed:
                    next_module = m
                    break
            if next_module:
                continue_learning = {
                    "course_title": course.title,
                    "module_title": next_module.title,
                    "progress_percentage": prog.progress_percentage,
                    "course_id": course.id,
                    "module_id": next_module.id,
                }

    # Recent results (best attempt per assessment, most recent completions)
    attempts = (
        db.query(Attempt)
        .filter(Attempt.user_keycloak_id == user.keycloak_id)
        .order_by(Attempt.completed_at.desc())
        .limit(8)
        .all()
    )
    recent_results = []
    seen = set()
    for a in attempts:
        if a.assessment_id in seen:
            continue
        seen.add(a.assessment_id)
        assessment = db.get(Assessment, a.assessment_id)
        if assessment:
            recent_results.append({
                "course_title": assessment.course.title if assessment.course else "Unknown",
                "assessment_title": assessment.title,
                "percentage": a.percentage,
                "passed": a.passed,
                "completed_at": a.completed_at,
                "attempt_id": a.id,
            })

    return templates.TemplateResponse(
        request,
        "training/dashboard.html",
        {
            "request": request,
            "user": user,
            "stats": stats,
            "continue_learning": continue_learning,
            "recent_results": recent_results,
            "active_page": "training",
        }
    )


@router.get("/training/courses")
def training_course_catalog(
    request: Request,
    q: str = "",
    category: str = "",
    difficulty: str = "",
    status_filter: str = "",
    sort: str = "newest",
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Training course catalog with search & filtering (section 5, 22)."""
    query = db.query(Course).filter(Course.published.is_(True))

    if category:
        query = query.filter(Course.category == category)
    if difficulty:
        query = query.filter(Course.difficulty == difficulty)

    courses = query.all()

    # Search
    if q.strip():
        ql = q.lower()
        courses = [c for c in courses if ql in c.title.lower() or ql in (c.description or "").lower()]

    # Status filter
    if status_filter:
        filtered = []
        for c in courses:
            prog = ProgressService.get_progress(db, user.keycloak_id, c.id)
            st = prog.status if prog else "not_started"
            if status_filter == "not_started" and st == "not_started":
                filtered.append(c)
            elif status_filter == "in_progress" and st == "in_progress":
                filtered.append(c)
            elif status_filter == "completed" and st in ("completed", "passed", "failed"):
                filtered.append(c)
        courses = filtered

    # Sorting
    if sort == "shortest":
        def dur_min(c):
            try:
                return int((c.duration or "0").split()[0])
            except (ValueError, IndexError):
                return 9999
        courses = sorted(courses, key=dur_min)
    elif sort == "title":
        courses = sorted(courses, key=lambda c: c.title)
    else:
        courses = sorted(courses, key=lambda c: c.created_at, reverse=True)

    cards = [_course_card_data(db, c, user.keycloak_id) for c in courses]

    categories = CATEGORIES

    return templates.TemplateResponse(
        request,
        "training/courses.html",
        {
            "request": request,
            "user": user,
            "courses": cards,
            "q": q,
            "categories": categories,
            "selected_category": category,
            "selected_difficulty": difficulty,
            "selected_status": status_filter,
            "selected_sort": sort,
            "active_page": "training",
        }
    )


@router.get("/training/course/{slug}")
def training_course_detail(
    request: Request,
    slug: str,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Course details page (section 7)."""
    course = db.query(Course).filter(Course.slug == slug).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    if not course.published and "Admin" not in user.roles and "Editor" not in user.roles:
        raise HTTPException(status_code=404, detail="Course not found")

    progress = ProgressService.get_progress(db, user.keycloak_id, course.id)
    completed = set(ProgressService.get_completed_modules(progress) if progress else [])

    module_data = []
    for m in course.modules:
        module_assessment = None
        if m.assessment:
            module_assessment = m.assessment
        module_data.append({
            "module": m,
            "is_complete": m.id in completed,
            "assessment": module_assessment,
        })

    # Course-level (final) assessments
    module_assessment_ids = {m.assessment_id for m in course.modules if m.assessment_id}
    course_assessments = [a for a in course.assessments if a.id not in module_assessment_ids]

    objectives = []
    if course.objectives:
        objectives = [o.strip() for o in course.objectives.split("\n") if o.strip()]

    due = _due_status(course)

    return templates.TemplateResponse(
        request,
        "training/course_detail.html",
        {
            "request": request,
            "user": user,
            "course": course,
            "modules": module_data,
            "course_assessments": course_assessments,
            "objectives": objectives,
            "progress": progress,
            "due": due,
            "active_page": "training",
        }
    )


@router.get("/training/module/{module_id}")
def training_module_view(
    request: Request,
    module_id: int,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Learning module page (section 8)."""
    module = db.get(Module, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    course = module.course

    # Render content (markdown or linked document)
    rendered_content = ""
    if module.content_type == "document" and module.document_id:
        doc = db.get(Document, module.document_id)
        if doc:
            rendered_content = render_markdown_safely(doc.content)
    elif module.content:
        rendered_content = render_markdown_safely(module.content)

    progress = ProgressService.get_progress(db, user.keycloak_id, course.id)
    completed = set(ProgressService.get_completed_modules(progress) if progress else [])
    is_complete = module.id in completed

    return templates.TemplateResponse(
        request,
        "training/module.html",
        {
            "request": request,
            "user": user,
            "module": module,
            "course": course,
            "rendered_content": rendered_content,
            "is_complete": is_complete,
            "active_page": "training",
        }
    )


@router.post("/training/module/{module_id}/complete")
def training_module_complete(
    request: Request,
    module_id: int,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Mark a module as actually complete (section 8)."""
    module = db.get(Module, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    ProgressService.mark_module_complete(db, user.keycloak_id, module.course, module)

    log_audit(
        db=db,
        action="COMPLETE_MODULE",
        user_id=user.keycloak_id,
        target_id=module.id,
        details=f"Completed module '{module.title}' in course '{module.course.title}'",
    )
    log_business_event("module_completed", f"module='{module.title}'", user.keycloak_id)

    return RedirectResponse(
        url=f"/training/course/{module.course.slug}",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/training/quiz/{assessment_id}")
def training_quiz_view(
    request: Request,
    assessment_id: int,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Quiz / assessment taking page (section 9)."""
    assessment = db.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    if not assessment.published and "Admin" not in user.roles and "Editor" not in user.roles:
        raise HTTPException(status_code=404, detail="Assessment not found")

    course = assessment.course

    # Enforce module-completion requirement before final assessment (section 19)
    if not ProgressService.can_access_assessment(db, user.keycloak_id, course, assessment):
        raise HTTPException(
            status_code=403,
            detail="You must complete the required learning modules before taking this assessment."
        )

    # Check attempt availability (section 16)
    allowed, reason, prior, max_attempts = ScoreService.can_attempt(
        assessment, db, user.keycloak_id
    )
    if not allowed:
        # Redirect to the best result page / history
        best = ScoreService.get_best_attempt(db, assessment_id, user.keycloak_id)
        if best:
            return RedirectResponse(
                url=f"/training/result/{best.id}",
                status_code=status.HTTP_303_SEE_OTHER
            )
        raise HTTPException(status_code=403, detail=reason)

    # Build question display data
    questions = sorted(assessment.questions, key=lambda q: q.order)
    question_display = []
    for q in questions:
        options = ScoreService.parse_question_options(q)
        question_display.append({
            "id": q.id,
            "type": q.type,
            "question": q.question,
            "options": options,
            "points": q.points,
            "difficulty": q.difficulty,
            "topic": q.topic,
            "explanation": q.explanation,
        })

    if not question_display:
        raise HTTPException(status_code=400, detail="This assessment has no questions yet.")

    return templates.TemplateResponse(
        request,
        "training/quiz.html",
        {
            "request": request,
            "user": user,
            "assessment": assessment,
            "course": course,
            "questions": question_display,
            "attempt_number": prior + 1,
            "max_attempts": max_attempts,
            "time_limit": assessment.time_limit,
            "active_page": "training",
        }
    )


@router.post("/training/quiz/{assessment_id}/submit")
async def training_quiz_submit(
    request: Request,
    assessment_id: int,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Submit a quiz attempt (section 12, 43 — prevents double submission)."""
    assessment = db.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    course = assessment.course

    if not ProgressService.can_access_assessment(db, user.keycloak_id, course, assessment):
        raise HTTPException(status_code=403, detail="Module completion required.")

    allowed, reason, prior, max_attempts = ScoreService.can_attempt(
        assessment, db, user.keycloak_id
    )
    if not allowed:
        raise HTTPException(status_code=403, detail=reason)

    form_data = await request.form()

    # Build answers dict from form
    answers = {}
    for q in assessment.questions:
        field_name = f"q_{q.id}"
        if q.type == "multiple_select":
            selected = form_data.getlist(field_name)
            answers[str(q.id)] = selected
        else:
            val = form_data.get(field_name)
            answers[str(q.id)] = val if val is not None else ""

    # Score deterministically (section 12)
    score_result = ScoreService.calculate_score(assessment, answers)

    # Persist attempt (does not overwrite history — section 16)
    attempt = ScoreService.save_attempt(
        db, assessment, user.keycloak_id, answers, score_result
    )

    # Recalculate course progress/status
    progress = ProgressService.get_or_create_progress(db, user.keycloak_id, course.id)
    ProgressService._recalculate(db, progress, course, user.keycloak_id)
    db.commit()

    log_audit(
        db=db,
        action="SUBMIT_ASSESSMENT",
        user_id=user.keycloak_id,
        target_id=assessment.id,
        details=f"Attempt {attempt.attempt_number} on '{assessment.title}': {score_result.percentage}% ({'PASS' if score_result.passed else 'FAIL'})",
    )
    log_business_event(
        "assessment_submitted",
        f"assessment='{assessment.title}' score={score_result.percentage}% passed={score_result.passed}",
        user.keycloak_id,
    )

    return RedirectResponse(
        url=f"/training/result/{attempt.id}",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/training/result/{attempt_id}")
def training_result(
    request: Request,
    attempt_id: int,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Assessment result page (section 13)."""
    attempt = db.get(Attempt, attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    # Data isolation: employees only see their own results (section 38)
    if attempt.user_keycloak_id != user.keycloak_id and "Admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Access denied.")

    assessment = attempt.assessment
    course = assessment.course

    score_result = ScoreService.calculate_score(assessment, json.loads(attempt.answers))

    # Attempt history for this assessment
    all_attempts = ScoreService.get_all_attempts(db, assessment.id, user.keycloak_id)
    best = ScoreService.get_best_attempt(db, assessment.id, user.keycloak_id)

    can_retake, reason, prior, max_attempts = ScoreService.can_attempt(
        assessment, db, user.keycloak_id
    )

    return templates.TemplateResponse(
        request,
        "training/result.html",
        {
            "request": request,
            "user": user,
            "attempt": attempt,
            "assessment": assessment,
            "course": course,
            "result": score_result,
            "all_attempts": all_attempts,
            "best": best,
            "can_retake": can_retake,
            "attempt_number": attempt.attempt_number,
            "max_attempts": max_attempts,
            "active_page": "training",
        }
    )


@router.get("/training/review/{attempt_id}")
def training_review(
    request: Request,
    attempt_id: int,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Answer review page (section 15)."""
    attempt = db.get(Attempt, attempt_id)
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    if attempt.user_keycloak_id != user.keycloak_id and "Admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Access denied.")

    assessment = attempt.assessment
    course = assessment.course

    score_result = ScoreService.calculate_score(assessment, json.loads(attempt.answers))

    return templates.TemplateResponse(
        request,
        "training/review.html",
        {
            "request": request,
            "user": user,
            "attempt": attempt,
            "assessment": assessment,
            "course": course,
            "result": score_result,
            "active_page": "training",
        }
    )


@router.get("/training/history")
def training_history(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Attempt history (section 17)."""
    attempts = (
        db.query(Attempt)
        .filter(Attempt.user_keycloak_id == user.keycloak_id)
        .order_by(Attempt.assessment_id, Attempt.attempt_number.asc())
        .all()
    )

    history = []
    for a in attempts:
        assessment = a.assessment
        history.append({
            "assessment_title": assessment.title if assessment else "Unknown",
            "course_title": assessment.course.title if assessment and assessment.course else "Unknown",
            "attempt_number": a.attempt_number,
            "percentage": a.percentage,
            "passed": a.passed,
            "completed_at": a.completed_at,
            "attempt_id": a.id,
        })

    return templates.TemplateResponse(
        request,
        "training/history.html",
        {
            "request": request,
            "user": user,
            "history": history,
            "active_page": "training",
        }
    )


@router.get("/training/report")
def training_report(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Personal training report (section 30)."""
    summary = AnalyticsService.get_user_training_summary(db, user.keycloak_id)
    return templates.TemplateResponse(
        request,
        "training/report.html",
        {
            "request": request,
            "user": user,
            "summary": summary,
            "active_page": "training",
        }
    )


@router.get("/training/certificate/{course_id}")
def training_certificate(
    request: Request,
    course_id: int,
    user: AuthenticatedUser = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Certificate / completion recognition (section 31)."""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    progress = ProgressService.get_progress(db, user.keycloak_id, course.id)
    if not progress or progress.status != "passed":
        raise HTTPException(
            status_code=403,
            detail="You must pass this course's assessments to receive a certificate."
        )

    # Best overall score across course assessments
    assessment_ids = [a.id for a in course.assessments]
    module_assessment_ids = [m.assessment_id for m in course.modules if m.assessment_id]
    all_ids = list(set(assessment_ids + module_assessment_ids))

    best_percentage = 0
    for aid in all_ids:
        best = ScoreService.get_best_attempt(db, aid, user.keycloak_id)
        if best and best.percentage > best_percentage:
            best_percentage = best.percentage

    return templates.TemplateResponse(
        request,
        "training/certificate.html",
        {
            "request": request,
            "user": user,
            "course": course,
            "progress": progress,
            "score": best_percentage,
            "completion_date": progress.updated_at.strftime("%d %B %Y"),
            "active_page": "training",
        }
    )


# ===========================================================================
# ADMIN / EDITOR TRAINING MANAGEMENT ROUTES
# ===========================================================================

@router.get("/admin/training")
def admin_training_panel(
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Training administration panel (section 24, 26)."""
    courses = db.query(Course).order_by(Course.created_at.desc()).all()
    overview = AnalyticsService.get_admin_overview(db)

    return templates.TemplateResponse(
        request,
        "training/admin/index.html",
        {
            "request": request,
            "user": user,
            "courses": courses,
            "overview": overview,
            "active_page": "admin_training",
        }
    )


# --- Course management ---

@router.get("/admin/training/course/new")
def admin_course_new_form(
    request: Request,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Create course form (section 24)."""
    return templates.TemplateResponse(
        request,
        "training/admin/course_form.html",
        {
            "request": request,
            "user": user,
            "course": None,
            "categories": CATEGORIES,
            "difficulties": DIFFICULTY_LEVELS,
            "active_page": "admin_training",
        }
    )


@router.post("/admin/training/course/new")
async def admin_course_create(
    request: Request,
    form: CourseCreate = Depends(form_parser(CourseCreate)),
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Create a course (section 24)."""
    slug = slugify(form.title)
    if db.query(Course).filter(Course.slug == slug).first():
        slug = f"{slug}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    course = Course(
        title=form.title,
        slug=slug,
        description=form.description,
        objectives=form.objectives,
        category=form.category,
        difficulty=form.difficulty,
        duration=form.duration,
        passing_score=form.passing_score,
        start_date=_parse_dt(form.start_date),
        due_date=_parse_dt(form.due_date),
        mandatory=form.mandatory,
        requires_module_completion=form.requires_module_completion,
        published=form.published,
    )
    db.add(course)
    db.commit()
    db.refresh(course)

    log_audit(db, "CREATE_COURSE", user.keycloak_id, course.id,
              f"Created course '{course.title}'")
    log_business_event("course_created", f"title='{course.title}'", user.keycloak_id)

    return RedirectResponse(url=f"/admin/training/course/{course.id}/edit",
                             status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/training/course/{course_id}/edit")
def admin_course_edit_form(
    request: Request,
    course_id: int,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Edit course form + module/assessment management (section 24)."""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    return templates.TemplateResponse(
        request,
        "training/admin/course_form.html",
        {
            "request": request,
            "user": user,
            "course": course,
            "categories": CATEGORIES,
            "difficulties": DIFFICULTY_LEVELS,
            "active_page": "admin_training",
        }
    )


@router.post("/admin/training/course/{course_id}/edit")
async def admin_course_update(
    request: Request,
    course_id: int,
    form: CourseUpdate = Depends(form_parser(CourseUpdate)),
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Update a course (section 24)."""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    course.title = form.title if form.title is not None else course.title
    course.description = form.description if form.description is not None else course.description
    course.objectives = form.objectives if form.objectives is not None else course.objectives
    course.category = form.category if form.category is not None else course.category
    course.difficulty = form.difficulty if form.difficulty is not None else course.difficulty
    course.duration = form.duration if form.duration is not None else course.duration
    if form.passing_score is not None:
        course.passing_score = form.passing_score
    course.start_date = _parse_dt(form.start_date) if form.start_date is not None else course.start_date
    course.due_date = _parse_dt(form.due_date) if form.due_date is not None else course.due_date
    if form.mandatory is not None:
        course.mandatory = form.mandatory
    if form.requires_module_completion is not None:
        course.requires_module_completion = form.requires_module_completion
    if form.published is not None:
        course.published = form.published

    db.commit()

    log_audit(db, "UPDATE_COURSE", user.keycloak_id, course.id,
              f"Updated course '{course.title}'")
    log_business_event("course_updated", f"title='{course.title}'", user.keycloak_id)

    return RedirectResponse(url=f"/admin/training/course/{course.id}/edit",
                             status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/training/course/{course_id}/delete")
def admin_course_delete(
    request: Request,
    course_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete a course (section 24 — Admin only)."""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    title = course.title
    db.delete(course)
    db.commit()

    log_audit(db, "DELETE_COURSE", user.keycloak_id, course_id,
              f"Deleted course '{title}'")
    log_business_event("course_deleted", f"title='{title}'", user.keycloak_id)

    return RedirectResponse(url="/admin/training", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/training/course/{course_id}/publish")
def admin_course_publish(
    request: Request,
    course_id: int,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Publish / unpublish a course (section 24)."""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    course.published = not course.published
    db.commit()

    action = "PUBLISH_COURSE" if course.published else "UNPUBLISH_COURSE"
    log_audit(db, action, user.keycloak_id, course.id,
              f"{'Published' if course.published else 'Unpublished'} course '{course.title}'")

    return RedirectResponse(url=f"/admin/training/course/{course.id}/edit",
                             status_code=status.HTTP_303_SEE_OTHER)


# --- Module management ---

@router.get("/admin/training/module/new/{course_id}")
def admin_module_new_form(
    request: Request,
    course_id: int,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Create module form (section 24)."""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    documents = db.query(Document).filter(Document.status == "published").all()
    course_assessments = (
        db.query(Assessment)
        .filter(Assessment.course_id == course_id)
        .order_by(Assessment.title)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "training/admin/module_form.html",
        {
            "request": request,
            "user": user,
            "course": course,
            "module": None,
            "documents": documents,
            "course_assessments": course_assessments,
            "active_page": "admin_training",
        }
    )


@router.post("/admin/training/module/new")
async def admin_module_create(
    request: Request,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Create a module (section 24)."""
    form_data = await request.form()
    course_id = int(form_data.get("course_id"))
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    content_type = form_data.get("content_type", "markdown")
    document_id = form_data.get("document_id")
    document_id = int(document_id) if document_id and document_id.isdigit() else None
    assessment_id = form_data.get("assessment_id")
    assessment_id = int(assessment_id) if assessment_id and assessment_id.isdigit() else None

    module = Module(
        course_id=course_id,
        title=form_data.get("title"),
        content=form_data.get("content") if content_type == "markdown" else None,
        content_type=content_type,
        document_id=document_id if content_type == "document" else None,
        assessment_id=assessment_id,
        order=int(form_data.get("order", len(course.modules))),
    )
    db.add(module)
    db.commit()
    db.refresh(module)

    log_audit(db, "CREATE_MODULE", user.keycloak_id, module.id,
              f"Created module '{module.title}' in course '{course.title}'")

    return RedirectResponse(url=f"/admin/training/course/{course.id}/edit",
                             status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/training/module/{module_id}/edit")
def admin_module_edit_form(
    request: Request,
    module_id: int,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Edit module form (section 24)."""
    module = db.get(Module, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    documents = db.query(Document).filter(Document.status == "published").all()
    course_assessments = (
        db.query(Assessment)
        .filter(Assessment.course_id == module.course_id)
        .order_by(Assessment.title)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "training/admin/module_form.html",
        {
            "request": request,
            "user": user,
            "course": module.course,
            "module": module,
            "documents": documents,
            "course_assessments": course_assessments,
            "active_page": "admin_training",
        }
    )


@router.post("/admin/training/module/{module_id}/edit")
async def admin_module_update(
    request: Request,
    module_id: int,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Update a module (section 24)."""
    module = db.get(Module, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    form_data = await request.form()
    module.title = form_data.get("title", module.title)
    content_type = form_data.get("content_type", module.content_type)
    module.content_type = content_type
    if content_type == "markdown":
        module.content = form_data.get("content", module.content)
        module.document_id = None
    else:
        module.content = None
        document_id = form_data.get("document_id")
        module.document_id = int(document_id) if document_id and document_id.isdigit() else None
    module.order = int(form_data.get("order", module.order))
    assessment_id = form_data.get("assessment_id")
    if assessment_id == "":
        module.assessment_id = None
    elif assessment_id and assessment_id.isdigit():
        module.assessment_id = int(assessment_id)
    else:
        module.assessment_id = module.assessment_id

    db.commit()

    log_audit(db, "UPDATE_MODULE", user.keycloak_id, module.id,
              f"Updated module '{module.title}'")

    return RedirectResponse(url=f"/admin/training/course/{module.course_id}/edit",
                             status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/training/module/{module_id}/delete")
def admin_module_delete(
    request: Request,
    module_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete a module (section 24 — Admin only)."""
    module = db.get(Module, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")

    course_id = module.course_id
    title = module.title
    db.delete(module)
    db.commit()

    log_audit(db, "DELETE_MODULE", user.keycloak_id, module_id,
              f"Deleted module '{title}'")

    return RedirectResponse(url=f"/admin/training/course/{course_id}/edit",
                             status_code=status.HTTP_303_SEE_OTHER)


# --- Assessment management ---

@router.get("/admin/training/assessment/new/{course_id}")
def admin_assessment_new_form(
    request: Request,
    course_id: int,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Create assessment form (section 24)."""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    return templates.TemplateResponse(
        request,
        "training/admin/assessment_form.html",
        {
            "request": request,
            "user": user,
            "course": course,
            "assessment": None,
            "active_page": "admin_training",
        }
    )


@router.post("/admin/training/assessment/new")
async def admin_assessment_create(
    request: Request,
    form: AssessmentCreate = Depends(form_parser(AssessmentCreate)),
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Create an assessment (section 24)."""
    course = db.get(Course, form.course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    assessment = Assessment(
        course_id=form.course_id,
        title=form.title,
        passing_score=form.passing_score,
        max_attempts=form.max_attempts,
        retakes_allowed=form.retakes_allowed,
        time_limit=form.time_limit,
        published=False,
    )
    db.add(assessment)
    db.commit()
    db.refresh(assessment)

    log_audit(db, "CREATE_ASSESSMENT", user.keycloak_id, assessment.id,
              f"Created assessment '{assessment.title}' in course '{course.title}'")

    return RedirectResponse(url=f"/admin/training/assessment/{assessment.id}/questions",
                             status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/training/assessment/{assessment_id}/edit")
def admin_assessment_edit_form(
    request: Request,
    assessment_id: int,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Edit assessment form (section 24)."""
    assessment = db.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    return templates.TemplateResponse(
        request,
        "training/admin/assessment_form.html",
        {
            "request": request,
            "user": user,
            "course": assessment.course,
            "assessment": assessment,
            "active_page": "admin_training",
        }
    )


@router.post("/admin/training/assessment/{assessment_id}/edit")
async def admin_assessment_update(
    request: Request,
    assessment_id: int,
    form: AssessmentUpdate = Depends(form_parser(AssessmentUpdate)),
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Update an assessment (section 24)."""
    assessment = db.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    assessment.title = form.title if form.title is not None else assessment.title
    if form.passing_score is not None:
        assessment.passing_score = form.passing_score
    if form.max_attempts is not None:
        assessment.max_attempts = form.max_attempts
    if form.retakes_allowed is not None:
        assessment.retakes_allowed = form.retakes_allowed
    assessment.time_limit = form.time_limit if form.time_limit is not None else assessment.time_limit
    if form.published is not None:
        assessment.published = form.published

    db.commit()

    log_audit(db, "UPDATE_ASSESSMENT", user.keycloak_id, assessment.id,
              f"Updated assessment '{assessment.title}'")

    return RedirectResponse(url=f"/admin/training/assessment/{assessment.id}/questions",
                             status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/training/assessment/{assessment_id}/delete")
def admin_assessment_delete(
    request: Request,
    assessment_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete an assessment (section 24 — Admin only)."""
    assessment = db.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    course_id = assessment.course_id
    title = assessment.title
    db.delete(assessment)
    db.commit()

    log_audit(db, "DELETE_ASSESSMENT", user.keycloak_id, assessment_id,
              f"Deleted assessment '{title}'")

    return RedirectResponse(url=f"/admin/training/course/{course_id}/edit",
                             status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/training/assessment/{assessment_id}/publish")
def admin_assessment_publish(
    request: Request,
    assessment_id: int,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Publish / unpublish an assessment (section 24)."""
    assessment = db.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    assessment.published = not assessment.published
    db.commit()

    return RedirectResponse(url=f"/admin/training/assessment/{assessment.id}/questions",
                             status_code=status.HTTP_303_SEE_OTHER)


# --- Question management ---

@router.get("/admin/training/assessment/{assessment_id}/questions")
def admin_question_bank(
    request: Request,
    assessment_id: int,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Question management page (section 24, 34)."""
    assessment = db.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    questions = sorted(assessment.questions, key=lambda q: q.order)

    question_display = []
    for q in questions:
        question_display.append({
            "id": q.id,
            "type": q.type,
            "type_label": {"multiple_choice": "Multiple Choice", "true_false": "True / False",
                           "multiple_select": "Multiple Select"}.get(q.type, q.type),
            "question": q.question,
            "options": ScoreService.parse_question_options(q),
            "correct_answer": ScoreService.parse_correct_answer(q),
            "points": q.points,
            "explanation": q.explanation,
            "difficulty": q.difficulty,
            "topic": q.topic,
            "order": q.order,
        })

    return templates.TemplateResponse(
        request,
        "training/admin/questions.html",
        {
            "request": request,
            "user": user,
            "assessment": assessment,
            "course": assessment.course,
            "questions": question_display,
            "question_types": QUESTION_TYPES,
            "difficulties": QUESTION_DIFFICULTIES,
            "active_page": "admin_training",
        }
    )


@router.post("/admin/training/question/new")
async def admin_question_create(
    request: Request,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Create a question (section 24)."""
    form_data = await request.form()
    assessment_id = int(form_data.get("assessment_id"))
    assessment = db.get(Assessment, assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")

    qtype = form_data.get("type", "multiple_choice")
    question_text = form_data.get("question_text", "").strip()
    options_raw = form_data.get("options", "")
    options = [o.strip() for o in options_raw.split("\n") if o.strip()]

    difficulty = form_data.get("difficulty", "Medium")
    topic = form_data.get("topic")
    points = int(form_data.get("points", 1))
    explanation = form_data.get("explanation")
    order = int(form_data.get("order", len(assessment.questions)))

    # Determine correct answer
    if qtype == "multiple_select":
        correct_indices = [int(i) for i in form_data.getlist("correct_options") if i.isdigit()]
        correct_answer = json.dumps([options[i] for i in correct_indices])
    else:
        correct_value = form_data.get("correct_answer", "")
        correct_answer = correct_value

    question = Question(
        assessment_id=assessment_id,
        type=qtype,
        question=question_text,
        options=json.dumps(options) if options else None,
        correct_answer=correct_answer,
        points=points,
        explanation=explanation,
        difficulty=difficulty,
        topic=topic,
        order=order,
    )
    db.add(question)
    db.commit()
    db.refresh(question)

    log_audit(db, "CREATE_QUESTION", user.keycloak_id, question.id,
              f"Created question in assessment '{assessment.title}'")

    return RedirectResponse(url=f"/admin/training/assessment/{assessment.id}/questions",
                             status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/training/question/{question_id}/edit")
async def admin_question_update(
    request: Request,
    question_id: int,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Update a question (section 24)."""
    question = db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    form_data = await request.form()
    qtype = form_data.get("type", question.type)
    question_text = form_data.get("question_text", question.question).strip()
    options_raw = form_data.get("options", "")
    options = [o.strip() for o in options_raw.split("\n") if o.strip()]

    question.type = qtype
    question.question = question_text
    question.options = json.dumps(options) if options else None
    question.difficulty = form_data.get("difficulty", question.difficulty)
    question.topic = form_data.get("topic", question.topic)
    question.points = int(form_data.get("points", question.points))
    question.explanation = form_data.get("explanation", question.explanation)
    question.order = int(form_data.get("order", question.order))

    if qtype == "multiple_select":
        correct_indices = [int(i) for i in form_data.getlist("correct_options") if i.isdigit()]
        question.correct_answer = json.dumps([options[i] for i in correct_indices])
    else:
        question.correct_answer = form_data.get("correct_answer", question.correct_answer)

    db.commit()

    log_audit(db, "UPDATE_QUESTION", user.keycloak_id, question.id,
              f"Updated question in assessment '{question.assessment.title}'")

    return RedirectResponse(url=f"/admin/training/assessment/{question.assessment_id}/questions",
                             status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/training/question/{question_id}/delete")
def admin_question_delete(
    request: Request,
    question_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Delete a question (section 24 — Admin only)."""
    question = db.get(Question, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    assessment_id = question.assessment_id
    db.delete(question)
    db.commit()

    log_audit(db, "DELETE_QUESTION", user.keycloak_id, question_id,
              f"Deleted question from assessment {assessment_id}")

    return RedirectResponse(url=f"/admin/training/assessment/{assessment_id}/questions",
                             status_code=status.HTTP_303_SEE_OTHER)


# --- Quiz Generator (section 34) ---

@router.get("/admin/training/quiz-generator")
def admin_quiz_generator_form(
    request: Request,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Quiz generator form (section 34)."""
    courses = db.query(Course).order_by(Course.title).all()
    topics = list(QUESTION_TEMPLATES.keys())

    return templates.TemplateResponse(
        request,
        "training/admin/quiz_generator.html",
        {
            "request": request,
            "user": user,
            "courses": courses,
            "topics": topics,
            "question_types": QUESTION_TYPES,
            "difficulties": QUESTION_DIFFICULTIES,
            "active_page": "admin_training",
        }
    )


@router.post("/admin/training/quiz-generator")
async def admin_quiz_generator_create(
    request: Request,
    user: AuthenticatedUser = Depends(require_editor),
    db: Session = Depends(get_db)
):
    """Generate a draft quiz from the template bank (section 34)."""
    form_data = await request.form()
    course_id = int(form_data.get("course_id"))
    title = form_data.get("title", "Generated Assessment")
    topic = form_data.get("topic", "Cybersecurity")
    num_questions = int(form_data.get("num_questions", 5))
    difficulty = form_data.get("difficulty", "Medium")
    question_type = form_data.get("question_type", "any")
    points = int(form_data.get("points", 5))

    assessment = QuizGenerator.create_draft_assessment(
        db, course_id, title, topic, num_questions, difficulty, question_type, points,
        user.keycloak_id
    )

    return RedirectResponse(url=f"/admin/training/assessment/{assessment.id}/questions",
                             status_code=status.HTTP_303_SEE_OTHER)


# --- Training Analytics (section 26, 27, 28, 29) ---

@router.get("/admin/training/analytics")
def admin_training_analytics(
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Training analytics overview (section 26)."""
    overview = AnalyticsService.get_admin_overview(db)
    employee_performance = AnalyticsService.get_employee_performance(db)

    # Per-course performance for table (section 27)
    courses = db.query(Course).filter(Course.published.is_(True)).all()
    course_performance = []
    for c in courses:
        perf = AnalyticsService.get_course_performance(db, c)
        course_performance.append({
            "course": c,
            "performance": perf,
        })

    return templates.TemplateResponse(
        request,
        "training/admin/analytics.html",
        {
            "request": request,
            "user": user,
            "overview": overview,
            "employee_performance": employee_performance,
            "course_performance": course_performance,
            "active_page": "admin_analytics",
        }
    )


@router.get("/admin/training/course/{course_id}/analytics")
def admin_course_analytics(
    request: Request,
    course_id: int,
    user: AuthenticatedUser = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Per-course performance analytics (section 27)."""
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    perf = AnalyticsService.get_course_performance(db, course)

    # Question-level analytics (section 28)
    questions = []
    for a in course.assessments:
        for q in a.questions:
            qa = AnalyticsService.get_question_analytics(db, q.id)
            if qa:
                qa["id"] = q.id
                qa["assessment"] = a.title
                questions.append(qa)

    return templates.TemplateResponse(
        request,
        "training/admin/course_analytics.html",
        {
            "request": request,
            "user": user,
            "course": course,
            "performance": perf,
            "questions": questions,
            "active_page": "admin_analytics",
        }
    )
