"""
Progress Tracking Service — Sections 19, 20

Tracks course progress, module completion, and course-level status
(NOT_STARTED, IN_PROGRESS, COMPLETED, PASSED, FAILED).
"""
import json
from sqlalchemy.orm import Session

from app.models.training import Course, Module, Assessment, Attempt, Progress
from app.services.scoring import ScoreService


class ProgressService:
    """Manage employee training progress and completion status."""

    @staticmethod
    def get_or_create_progress(
        db: Session, user_keycloak_id: str, course_id: int
    ) -> Progress:
        progress = (
            db.query(Progress)
            .filter(Progress.user_keycloak_id == user_keycloak_id,
                    Progress.course_id == course_id)
            .first()
        )
        if not progress:
            progress = Progress(
                user_keycloak_id=user_keycloak_id,
                course_id=course_id,
                completed_modules="",
                progress_percentage=0,
                status="not_started",
            )
            db.add(progress)
            db.commit()
            db.refresh(progress)
        return progress

    @staticmethod
    def get_completed_modules(progress: Progress) -> list[int]:
        """Return list of completed module IDs from the stored JSON string."""
        if not progress.completed_modules:
            return []
        try:
            data = json.loads(progress.completed_modules)
            if isinstance(data, list):
                return [int(m) for m in data]
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        return []

    @staticmethod
    def mark_module_complete(
        db: Session,
        user_keycloak_id: str,
        course: Course,
        module: Module,
    ) -> Progress:
        """Track actual completion of a module (section 8 — not just opening it)."""
        progress = ProgressService.get_or_create_progress(
            db, user_keycloak_id, course.id
        )
        completed = set(ProgressService.get_completed_modules(progress))
        completed.add(module.id)

        progress.completed_modules = json.dumps(list(completed))
        progress.status = "in_progress"
        ProgressService._recalculate(db, progress, course, user_keycloak_id)
        db.commit()
        db.refresh(progress)
        return progress

    @staticmethod
    def _recalculate(
        db: Session,
        progress: Progress,
        course: Course,
        user_keycloak_id: str,
    ):
        """Recalculate progress percentage and overall course status."""
        modules = course.modules
        completed = set(ProgressService.get_completed_modules(progress))

        if modules:
            progress.progress_percentage = round(
                (len(completed & {m.id for m in modules}) / len(modules)) * 100
            )
        else:
            progress.progress_percentage = 0

        # Determine overall status (section 20)
        # Course-level assessments are those not tied to a single module
        module_assessment_ids = {m.assessment_id for m in modules if m.assessment_id}
        course_assessments = [
            a for a in course.assessments if a.id not in module_assessment_ids
        ]

        if not completed and progress.progress_percentage == 0:
            progress.status = "not_started"
            return

        if progress.progress_percentage < 100:
            progress.status = "in_progress"
            return

        # All modules completed — check assessments
        all_module_passed = True
        for mod in modules:
            if mod.assessment_id:
                best = ScoreService.get_best_attempt(
                    db, mod.assessment_id, user_keycloak_id
                )
                if best is None or not best.passed:
                    all_module_passed = False
                    break

        if not all_module_passed:
            progress.status = "completed"
            return

        # All module assessments passed
        if course_assessments:
            final_best = ScoreService.get_best_attempt(
                db, course_assessments[0].id, user_keycloak_id
            )
            if final_best and final_best.passed:
                progress.status = "passed"
            elif final_best and not final_best.passed:
                progress.status = "failed"
            else:
                progress.status = "completed"
        else:
            progress.status = "passed"

    @staticmethod
    def get_progress(
        db: Session, user_keycloak_id: str, course_id: int
    ) -> Progress | None:
        return (
            db.query(Progress)
            .filter(Progress.user_keycloak_id == user_keycloak_id,
                    Progress.course_id == course_id)
            .first()
        )

    @staticmethod
    def can_access_assessment(
        db: Session,
        user_keycloak_id: str,
        course: Course,
        assessment: Assessment,
    ) -> bool:
        """Check whether a user can start an assessment, optionally requiring
        module completion first (section 19)."""
        if course.requires_module_completion:
            progress = ProgressService.get_progress(db, user_keycloak_id, course.id)
            completed = set(
                ProgressService.get_completed_modules(progress)
                if progress else []
            )
            for mod in course.modules:
                if mod.assessment_id == assessment.id and mod.id not in completed:
                    return False
        return True

    @staticmethod
    def get_user_attempts_for_course(
        db: Session, user_keycloak_id: str, course_id: int
    ) -> list[Attempt]:
        """Return all attempts the user made on any assessment belonging to a course."""
        return (
            db.query(Attempt)
            .join(Assessment, Attempt.assessment_id == Assessment.id)
            .filter(Attempt.user_keycloak_id == user_keycloak_id,
                    Assessment.course_id == course_id)
            .order_by(Attempt.attempt_number.asc())
            .all()
        )
