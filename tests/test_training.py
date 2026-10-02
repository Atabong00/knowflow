import pytest

from app.auth.dependencies import AuthenticatedUser, generate_csrf_token
from app.routes.training import require_user, require_editor, require_admin
from app.services.seed import seed_training_data
from app.models.training import Course, Assessment, Question, Progress


def make_user(role="Employee", keycloak_id="test-kc-id"):
    return AuthenticatedUser({
        "sub": keycloak_id,
        "preferred_username": "testuser",
        "email": "test@example.com",
        "name": "Test User",
        "realm_access": {"roles": [role]},
        "resource_access": {"wiki-app": {"roles": [role]}},
    })


@pytest.fixture
def employee_client(client):
    user = make_user("Employee")
    client.app.dependency_overrides[require_user] = lambda: user
    client.app.dependency_overrides[require_editor] = lambda: user
    client.app.dependency_overrides[require_admin] = lambda: user
    return client


@pytest.fixture
def admin_client(client):
    user = make_user("Admin")
    client.app.dependency_overrides[require_user] = lambda: user
    client.app.dependency_overrides[require_editor] = lambda: user
    client.app.dependency_overrides[require_admin] = lambda: user
    return client


@pytest.fixture
def editor_client(client):
    user = make_user("Editor")
    client.app.dependency_overrides[require_user] = lambda: user
    client.app.dependency_overrides[require_editor] = lambda: user
    client.app.dependency_overrides[require_admin] = lambda: user
    return client


@pytest.fixture
def seeded_db(db):
    seed_training_data(db)
    return db


def csrf_post(client, url, data=None, files=None):
    token = generate_csrf_token()
    client.cookies.set("csrf_token", token)
    return client.post(url, data=data or {}, files=files, headers={"X-CSRF-Token": token}, follow_redirects=False)


class TestTrainingEmployeeFlow:
    def test_training_dashboard_requires_auth(self, client):
        # No overrides -> unauthenticated. Browser requests send text/html.
        resp = client.get("/training", headers={"Accept": "text/html"}, follow_redirects=False)
        assert resp.status_code == 307
        assert "/login" in resp.headers["location"]

    def test_training_dashboard_loads(self, employee_client, seeded_db):
        resp = employee_client.get("/training")
        assert resp.status_code == 200
        assert "Training Overview" in resp.text
        assert "Continue Learning" in resp.text

    def test_course_catalog_loads(self, employee_client, seeded_db):
        resp = employee_client.get("/training/courses")
        assert resp.status_code == 200
        assert "Information Security Awareness" in resp.text

    def test_course_catalog_filter_by_category(self, employee_client, seeded_db):
        resp = employee_client.get("/training/courses?category=Cybersecurity")
        assert resp.status_code == 200
        assert "Information Security Awareness" in resp.text

    def test_course_detail_loads(self, employee_client, seeded_db):
        course = seeded_db.query(Course).filter(Course.slug == "information-security-awareness").first()
        resp = employee_client.get(f"/training/course/{course.slug}")
        assert resp.status_code == 200
        assert "Password Security" in resp.text
        assert "What you will learn" in resp.text

    def test_module_view_loads_mark_complete(self, employee_client, seeded_db):
        course = seeded_db.query(Course).filter(Course.slug == "information-security-awareness").first()
        module = course.modules[0]
        resp = employee_client.get(f"/training/module/{module.id}")
        assert resp.status_code == 200
        assert "Mark Module Complete" in resp.text

        # Mark complete
        resp2 = csrf_post(employee_client, f"/training/module/{module.id}/complete")
        assert resp2.status_code == 303
        progress = seeded_db.query(Progress).filter(
            Progress.user_keycloak_id == "test-kc-id",
            Progress.course_id == course.id
        ).first()
        assert progress is not None
        import json
        completed = json.loads(progress.completed_modules)
        assert module.id in completed

    def test_quiz_view_and_submit_pass(self, employee_client, seeded_db):
        from app.models.training import Course
        course = seeded_db.query(Course).filter(Course.slug == "information-security-awareness").first()
        module_assessment_ids = {m.assessment_id for m in course.modules if m.assessment_id}
        assessment = next(a for a in course.assessments if a.id not in module_assessment_ids)
        # GET quiz
        resp = employee_client.get(f"/training/quiz/{assessment.id}")
        assert resp.status_code == 200
        assert "Submit Assessment" in resp.text

        # Build correct answers
        import json as _json
        data = {}
        for q in assessment.questions:
            if q.type == "multiple_select":
                data[f"q_{q.id}"] = _json.loads(q.correct_answer)
            else:
                data[f"q_{q.id}"] = q.correct_answer

        resp2 = csrf_post(employee_client, f"/training/quiz/{assessment.id}/submit", data=data)
        assert resp2.status_code == 303
        attempt_id = int(resp2.headers["location"].rstrip("/").split("/")[-1])
        assert attempt_id > 0

        # Result page
        resp3 = employee_client.get(f"/training/result/{attempt_id}")
        assert resp3.status_code == 200
        assert "PASSED" in resp3.text

        # Review page
        resp4 = employee_client.get(f"/training/review/{attempt_id}")
        assert resp4.status_code == 200
        assert "Answer Review" in resp4.text

    def test_quiz_submit_fail(self, employee_client, seeded_db):
        from app.models.training import Course
        course = seeded_db.query(Course).filter(Course.slug == "information-security-awareness").first()
        module_assessment_ids = {m.assessment_id for m in course.modules if m.assessment_id}
        assessment = next(a for a in course.assessments if a.id not in module_assessment_ids)
        import json as _json
        data = {}
        for q in assessment.questions:
            opts = _json.loads(q.options) if q.options else []
            if q.type == "multiple_select":
                # submit none -> incorrect
                data[f"q_{q.id}"] = []
            else:
                # submit first option (likely wrong for most)
                data[f"q_{q.id}"] = opts[0] if opts else "wrong"

        resp = csrf_post(employee_client, f"/training/quiz/{assessment.id}/submit", data=data)
        assert resp.status_code == 303
        attempt_id = int(resp.headers["location"].rstrip("/").split("/")[-1])
        resp2 = employee_client.get(f"/training/result/{attempt_id}")
        assert resp2.status_code == 200
        assert "Assessment Complete" in resp2.text

    def test_attempt_history(self, employee_client, seeded_db):
        # Submit one attempt first
        assessment = seeded_db.query(Assessment).join(Course).filter(
            Course.slug == "information-security-awareness"
        ).first()
        csrf_post(employee_client, f"/training/quiz/{assessment.id}/submit", data={
            f"q_{q.id}": (__import__("json").loads(q.correct_answer) if q.type == "multiple_select" else q.correct_answer)
            for q in assessment.questions
        })
        resp = employee_client.get("/training/history")
        assert resp.status_code == 200
        assert "Assessment History" in resp.text

    def test_personal_report(self, employee_client, seeded_db):
        resp = employee_client.get("/training/report")
        assert resp.status_code == 200
        assert "My Training" in resp.text


class TestTrainingAdminFlow:
    def test_admin_training_panel(self, admin_client, seeded_db):
        resp = admin_client.get("/admin/training")
        assert resp.status_code == 200
        assert "Training Courses" in resp.text

    def test_create_course(self, admin_client, seeded_db):
        resp = admin_client.get("/admin/training/course/new")
        assert resp.status_code == 200
        data = {
            "title": "Test Admin Course",
            "description": "desc",
            "category": "Compliance",
            "difficulty": "Beginner",
            "duration": "10 min",
            "passing_score": "70",
            "mandatory": "true",
            "requires_module_completion": "true",
            "published": "true",
        }
        resp2 = csrf_post(admin_client, "/admin/training/course/new", data=data)
        assert resp2.status_code == 303
        course = seeded_db.query(Course).filter(Course.title == "Test Admin Course").first()
        assert course is not None
        assert course.published is True

    def test_create_module_with_assessment(self, admin_client, seeded_db):
        course = Course(title="Mod Course", slug="mod-course", published=False)
        seeded_db.add(course)
        seeded_db.commit()
        seeded_db.refresh(course)

        # Create a module
        data = {
            "course_id": str(course.id),
            "title": "Intro Module",
            "content_type": "markdown",
            "content": "# Intro",
            "order": "0",
        }
        resp = csrf_post(admin_client, "/admin/training/module/new", data=data)
        assert resp.status_code == 303
        module = seeded_db.query(Course).filter(Course.id == course.id).first().modules[0]
        assert module.title == "Intro Module"

    def test_question_bank_and_create_question(self, admin_client, seeded_db):
        course = seeded_db.query(Course).filter(Course.slug == "information-security-awareness").first()
        assessment = course.assessments[0]
        resp = admin_client.get(f"/admin/training/assessment/{assessment.id}/questions")
        assert resp.status_code == 200

        data = {
            "assessment_id": str(assessment.id),
            "type": "multiple_choice",
            "question_text": "Sample question?",
            "options": "A\nB\nC\nD",
            "correct_answer": "B",
            "points": "5",
            "difficulty": "Easy",
            "topic": "Test",
            "explanation": "Because B.",
        }
        resp2 = csrf_post(admin_client, "/admin/training/question/new", data=data)
        assert resp2.status_code == 303
        q = seeded_db.query(Question).filter(Question.question == "Sample question?").first()
        assert q is not None
        assert q.correct_answer == "B"

    def test_quiz_generator(self, admin_client, seeded_db):
        course = seeded_db.query(Course).filter(Course.slug == "information-security-awareness").first()
        resp = admin_client.get("/admin/training/quiz-generator")
        assert resp.status_code == 200
        data = {
            "title": "Generated Quiz",
            "course_id": str(course.id),
            "topic": "Cybersecurity",
            "num_questions": "3",
            "question_type": "any",
            "difficulty": "Easy",
            "points": "5",
        }
        resp2 = csrf_post(admin_client, "/admin/training/quiz-generator", data=data)
        assert resp2.status_code == 303
        # Assessment created (not published)
        new_a = seeded_db.query(Assessment).filter(Assessment.title == "Generated Quiz").first()
        assert new_a is not None
        assert new_a.published is False

    def test_training_analytics(self, admin_client, seeded_db):
        resp = admin_client.get("/admin/training/analytics")
        assert resp.status_code == 200
        assert "Training Analytics" in resp.text
        assert "Course Performance" in resp.text

    def test_course_analytics(self, admin_client, seeded_db):
        course = seeded_db.query(Course).filter(Course.slug == "information-security-awareness").first()
        resp = admin_client.get(f"/admin/training/course/{course.id}/analytics")
        assert resp.status_code == 200
        assert "Question Analytics" in resp.text
