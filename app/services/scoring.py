"""
Scoring Engine — Section 12

A reliable, deterministic scoring system that does NOT depend on visual UI
state.  Every assessment result is calculated purely from the stored question
data and the answers submitted by the employee.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.training import Assessment, Question, Attempt
from app.services.config import PerformanceConfig


@dataclass
class ScoreResult:
    total_questions: int = 0
    correct_answers: int = 0
    incorrect_answers: int = 0
    points_earned: int = 0
    max_points: int = 0
    percentage: int = 0
    passing_score: int = 70
    passed: bool = False
    performance_label: str = ""
    performance_key: str = ""
    questions_detail: list = field(default_factory=list)


class ScoreService:
    """Deterministic scoring engine for training assessments (section 12)."""

    @staticmethod
    def parse_question_options(question: Question) -> list:
        """Parse the JSON options string of a question into a list."""
        if not question.options:
            return []
        try:
            opts = json.loads(question.options)
            if isinstance(opts, list):
                return opts
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @staticmethod
    def parse_correct_answer(question: Question) -> any:
        """Parse the correct_answer field of a question.

        Supports both legacy single-value (string) storage and JSON array
        storage for multi-select questions.
        """
        raw = question.correct_answer
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed
        except (json.JSONDecodeError, TypeError):
            return raw.strip()

    @staticmethod
    def _normalize_answer(raw_answer: str | list) -> str | list:
        """Normalise a stored answer for comparison."""
        if raw_answer is None:
            return None
        if isinstance(raw_answer, (list, tuple)):
            return [str(a).strip() for a in raw_answer]
        return str(raw_answer).strip()

    @staticmethod
    def _answers_match(submitted: str | list, expected: str | list, question_type: str) -> bool:
        """Compare submitted answer(s) against the correct answer(s) based on question type."""
        if question_type == "multiple_select":
            if isinstance(expected, list):
                expected_set = set(str(e).strip() for e in expected)
            else:
                try:
                    expected_set = set(str(e).strip() for e in json.loads(expected))
                except (json.JSONDecodeError, TypeError):
                    expected_set = {str(expected).strip()}

            if isinstance(submitted, list):
                submitted_set = set(str(s).strip() for s in submitted)
            else:
                submitted_set = {str(submitted).strip()}

            return submitted_set == expected_set

        else:
            if isinstance(expected, list):
                expected = expected[0] if expected else ""
            if isinstance(submitted, list):
                submitted = submitted[0] if submitted else ""

            return str(submitted).strip().lower() == str(expected).strip().lower()

    @staticmethod
    def calculate_score(
        assessment: Assessment,
        answers: dict,
    ) -> ScoreResult:
        """Calculate the score for an assessment given a dict of answers.

        ``answers`` maps ``question_id (str)`` -> answer value (string or list).
        The calculation is fully deterministic from stored data.
        """
        questions = sorted(assessment.questions, key=lambda q: q.order)
        result = ScoreResult()
        result.max_points = sum(q.points for q in questions)
        result.total_questions = len(questions)
        result.passing_score = assessment.passing_score

        for q in questions:
            qid_str = str(q.id)
            correct = ScoreService.parse_correct_answer(q)
            submitted = ScoreService._normalize_answer(answers.get(qid_str))

            is_correct = False
            if submitted is not None and submitted != "" and submitted != []:
                is_correct = ScoreService._answers_match(submitted, correct, q.type)

            points = q.points if is_correct else 0
            result.points_earned += points

            if is_correct:
                result.correct_answers += 1
            else:
                result.incorrect_answers += 1

            result.questions_detail.append({
                "question_id": q.id,
                "question": q.question,
                "type": q.type,
                "options": ScoreService.parse_question_options(q),
                "correct_answer": correct,
                "submitted_answer": submitted,
                "is_correct": is_correct,
                "points": q.points,
                "points_earned": points,
                "explanation": q.explanation,
                "difficulty": q.difficulty,
                "topic": q.topic,
            })

        if result.max_points > 0:
            result.percentage = round((result.points_earned / result.max_points) * 100)
        else:
            result.percentage = 0

        result.passed = result.percentage >= result.passing_score
        label, key = PerformanceConfig.classify(result.percentage)
        result.performance_label = label
        result.performance_key = key

        return result

    @staticmethod
    def save_attempt(
        db: Session,
        assessment: Assessment,
        user_keycloak_id: str,
        answers: dict,
        score_result: ScoreResult,
    ) -> Attempt:
        """Persist a scored attempt to the database (section 16 — does not overwrite history)."""
        existing_attempts = (
            db.query(Attempt)
            .filter(Attempt.assessment_id == assessment.id,
                    Attempt.user_keycloak_id == user_keycloak_id)
            .order_by(Attempt.attempt_number.desc())
            .all()
        )
        next_number = (existing_attempts[0].attempt_number + 1
                       if existing_attempts else 1)

        attempt = Attempt(
            assessment_id=assessment.id,
            user_keycloak_id=user_keycloak_id,
            attempt_number=next_number,
            answers=json.dumps(answers),
            score=score_result.points_earned,
            percentage=score_result.percentage,
            passed=score_result.passed,
            completed_at=datetime.utcnow(),
        )
        db.add(attempt)
        db.commit()
        db.refresh(attempt)
        return attempt

    @staticmethod
    def can_attempt(assessment: Assessment, db: Session, user_keycloak_id: str) -> tuple[bool, str, int, int]:
        """Check whether the user is still allowed to take the assessment (section 16).

        Returns (allowed, reason, current_attempt, max_attempts).
        """
        prior = (
            db.query(Attempt)
            .filter(Attempt.assessment_id == assessment.id,
                    Attempt.user_keycloak_id == user_keycloak_id)
            .count()
        )

        if not assessment.retakes_allowed and prior >= 1:
            return (False, "Retakes are not allowed for this assessment.", prior, assessment.max_attempts)

        if assessment.max_attempts > 0 and prior >= assessment.max_attempts:
            return (False, f"You have used all {assessment.max_attempts} attempt(s).", prior, assessment.max_attempts)

        return (True, "", prior, assessment.max_attempts)

    @staticmethod
    def get_best_attempt(db: Session, assessment_id: int, user_keycloak_id: str) -> Attempt | None:
        """Return the best-scoring attempt for a user on an assessment (section 18)."""
        return (
            db.query(Attempt)
            .filter(Attempt.assessment_id == assessment_id,
                    Attempt.user_keycloak_id == user_keycloak_id)
            .order_by(Attempt.percentage.desc())
            .first()
        )

    @staticmethod
    def get_all_attempts(db: Session, assessment_id: int, user_keycloak_id: str) -> list[Attempt]:
        """Return all attempts for a user on an assessment, newest first (section 17)."""
        return (
            db.query(Attempt)
            .filter(Attempt.assessment_id == assessment_id,
                    Attempt.user_keycloak_id == user_keycloak_id)
            .order_by(Attempt.attempt_number.asc())
            .all()
        )
