"""
Analytics Service — Sections 26, 27, 28, 29

Provides aggregated training analytics for administrators and
per-employee performance insights.
"""
import json
from collections import defaultdict
from sqlalchemy.orm import Session

from app.models.training import Course, Assessment, Question, Attempt, Progress
from app.models.user import User
from app.services.scoring import ScoreService


class AnalyticsService:
    """Training analytics for administrators (sections 26-29)."""

    @staticmethod
    def get_admin_overview(db: Session) -> dict:
        """Return high-level training analytics (section 26)."""
        total_employees = db.query(User).count()
        total_courses = db.query(Course).filter(Course.published.is_(True)).count()
        total_assessments = (
            db.query(Assessment)
            .filter(Assessment.published.is_(True))
            .count()
        )

        completed_courses = (
            db.query(Progress)
            .filter(Progress.status.in_(["completed", "passed", "failed"]))
            .count()
        )

        total_enrollments = db.query(Progress).count()
        completion_rate = (
            round((completed_courses / total_enrollments) * 100)
            if total_enrollments > 0
            else 0
        )

        # Average score across all attempts
        all_attempts = db.query(Attempt).all()
        if all_attempts:
            avg_score = round(sum(a.percentage for a in all_attempts) / len(all_attempts))
        else:
            avg_score = 0

        # Pass rate
        passed_attempts = [a for a in all_attempts if a.passed]
        failed_attempts = [a for a in all_attempts if not a.passed]
        pass_rate = (
            round((len(passed_attempts) / len(all_attempts)) * 100)
            if all_attempts
            else 0
        )
        failure_rate = 100 - pass_rate if all_attempts else 0

        # Needing attention = employees with attempts below passing
        needs_attention = len(set(
            fa.user_keycloak_id for fa in failed_attempts
        ))

        return {
            "total_employees": total_employees,
            "total_courses": total_courses,
            "total_assessments": total_assessments,
            "completed_courses": completed_courses,
            "total_enrollments": total_enrollments,
            "completion_rate": completion_rate,
            "average_score": avg_score,
            "pass_rate": pass_rate,
            "failure_rate": failure_rate,
            "needs_attention": needs_attention,
        }

    @staticmethod
    def get_course_performance(db: Session, course: Course) -> dict:
        """Return per-course performance analytics (section 27)."""
        enrollments = (
            db.query(Progress)
            .filter(Progress.course_id == course.id)
            .all()
        )
        enrolled = len(enrollments)
        completed = sum(
            1 for p in enrollments
            if p.status in ("completed", "passed", "failed")
        )
        passed = sum(1 for p in enrollments if p.status == "passed")
        failed = sum(1 for p in enrollments if p.status == "failed")

        # Average score across all attempts on this course's assessments
        assessment_ids = [a.id for a in course.assessments]
        course_attempts = (
            db.query(Attempt)
            .filter(Attempt.assessment_id.in_(assessment_ids))
            .all()
        )

        if course_attempts:
            avg_score = round(
                sum(a.percentage for a in course_attempts) / len(course_attempts)
            )
        else:
            avg_score = 0

        completion_rate = (
            round((completed / enrolled) * 100) if enrolled > 0 else 0
        )

        return {
            "enrolled": enrolled,
            "completed": completed,
            "passed": passed,
            "failed": failed,
            "completion_rate": completion_rate,
            "average_score": avg_score,
        }

    @staticmethod
    def get_question_analytics(db: Session, question_id: int) -> dict | None:
        """Return per-question analytics (section 28)."""
        question = db.get(Question, question_id)
        if not question:
            return None

        correct_rate = 0
        attempts_count = 0
        correct_count = 0
        incorrect_count = 0

        # Look at all attempts for the assessment this question belongs to
        attempts = (
            db.query(Attempt)
            .filter(Attempt.assessment_id == question.assessment_id)
            .all()
        )

        for attempt in attempts:
            try:
                answers = json.loads(attempt.answers)
            except (json.JSONDecodeError, TypeError):
                continue

            answer = answers.get(str(question.id))
            if answer is not None and answer != "" and answer != []:
                attempts_count += 1
                correct = ScoreService.parse_correct_answer(question)
                is_correct = ScoreService._answers_match(
                    answer, correct, question.type
                )
                if is_correct:
                    correct_count += 1
                else:
                    incorrect_count += 1

        if attempts_count > 0:
            correct_rate = round((correct_count / attempts_count) * 100)

        return {
            "question": question.question,
            "correct_rate": correct_rate,
            "difficulty": question.difficulty,
            "attempts": attempts_count,
            "correct": correct_count,
            "incorrect": incorrect_count,
        }

    @staticmethod
    def get_employee_performance(db: Session) -> list[dict]:
        """Return per-employee training results for admins (section 39)."""
        rows = (
            db.query(
                Attempt.user_keycloak_id,
                Attempt.assessment_id,
                Attempt.percentage,
                Attempt.passed,
                Attempt.completed_at,
            )
            .order_by(Attempt.user_keycloak_id, Attempt.completed_at.desc())
            .all()
        )

        seen = set()
        results = []
        for user_id, assessment_id, percentage, passed, completed_at in rows:
            key = (user_id, assessment_id)
            if key in seen:
                continue
            seen.add(key)

            assessment = db.get(Assessment, assessment_id)
            user = db.query(User).filter(User.keycloak_id == user_id).first()
            course = assessment.course if assessment else None

            results.append({
                "employee_name": user.display_name if user else "Unknown",
                "employee_email": user.email if user else "",
                "course": course.title if course else "Unknown",
                "score": percentage,
                "status": "Passed" if passed else "Failed",
                "completed_at": completed_at,
            })

        return results

    @staticmethod
    def get_weak_topics(db: Session, user_keycloak_id: str) -> dict:
        """Identify strong and weak topics for a user (section 29)."""
        attempts = (
            db.query(Attempt)
            .filter(Attempt.user_keycloak_id == user_keycloak_id)
            .all()
        )

        topic_scores = defaultdict(list)

        for attempt in attempts:
            try:
                answers = json.loads(attempt.answers)
            except (json.JSONDecodeError, TypeError):
                continue

            for question in attempt.assessment.questions:
                answer = answers.get(str(question.id))
                if answer is None or answer == "" or answer == []:
                    continue
                correct = ScoreService.parse_correct_answer(question)
                is_correct = ScoreService._answers_match(
                    answer, correct, question.type
                )
                topic = question.topic or "General"
                topic_scores[topic].append(1 if is_correct else 0)

        strong = {}
        weak = {}
        recommendations = []

        for topic, scores in topic_scores.items():
            avg = round((sum(scores) / len(scores)) * 100) if scores else 0
            if avg >= 70:
                strong[topic] = avg
            else:
                weak[topic] = avg

        # Sort
        strong = dict(sorted(strong.items(), key=lambda x: x[1], reverse=True))
        weak = dict(sorted(weak.items(), key=lambda x: x[1]))

        for topic in weak:
            recommendations.append(topic)

        return {
            "strong": strong,
            "weak": weak,
            "recommendations": recommendations,
        }

    @staticmethod
    def get_user_training_summary(db: Session, user_keycloak_id: str) -> dict:
        """Return personal training summary (section 30)."""
        progresses = (
            db.query(Progress)
            .filter(Progress.user_keycloak_id == user_keycloak_id)
            .all()
        )
        user = db.query(User).filter(User.keycloak_id == user_keycloak_id).first()

        total_courses = len(progresses)
        completed = sum(
            1 for p in progresses
            if p.status in ("completed", "passed", "failed")
        )
        in_progress = sum(1 for p in progresses if p.status == "in_progress")

        # Get best attempt per assessment
        assessments = (
            db.query(Assessment)
            .join(Course)
            .filter(Course.published.is_(True))
            .all()
        )

        passed_count = 0
        all_percentages = []
        for assessment in assessments:
            best = ScoreService.get_best_attempt(
                db, assessment.id, user_keycloak_id
            )
            if best:
                all_percentages.append(best.percentage)
                if best.passed:
                    passed_count += 1

        avg_score = (
            round(sum(all_percentages) / len(all_percentages))
            if all_percentages else 0
        )

        # Strong/weak topics
        topic_info = AnalyticsService.get_weak_topics(db, user_keycloak_id)

        return {
            "user": user,
            "courses_completed": completed,
            "courses_in_progress": in_progress,
            "assessments_passed": passed_count,
            "average_score": avg_score,
            "total_courses": total_courses,
            "strong_areas": topic_info["strong"],
            "weak_areas": topic_info["weak"],
        }
