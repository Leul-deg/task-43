from datetime import datetime

from app.extensions import db
from app.models import (
    Assessment, AssessmentAssignment, AssessmentResult, Question, User, UserAnswer,
)
from conftest import hmac_headers, login_as


def test_post_create_trainer_ok_staff_forbidden(client, app):
    login_as(client, "trainer")
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
    data = {"title": "API Assessment", "description": "", "passing_score_percent": "70"}
    headers = hmac_headers(trainer, "POST", "/assessments/", data)
    response = client.post("/assessments/", data=data, headers=headers)
    assert response.status_code == 302

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    headers = hmac_headers(staff, "POST", "/assessments/", data)
    response = client.post("/assessments/", data=data, headers=headers)
    assert response.status_code == 403


def test_submit_and_results(client, app):
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        staff = User.query.filter_by(username="test_staff").first()
        assessment = Assessment(
            title="API Flow",
            description="",
            created_by=trainer.id,
            passing_score_percent=70,
        )
        db.session.add(assessment)
        db.session.flush()
        question = Question(
            assessment_id=assessment.id,
            question_text="1+1",
            question_type="multiple_choice",
            options='["2","3"]',
            correct_answer="2",
            points=1,
        )
        db.session.add(question)
        assignment = AssessmentAssignment(
            assessment_id=assessment.id,
            user_id=staff.id,
            assigned_by=trainer.id,
            assigned_at=datetime.utcnow(),
            status="assigned",
        )
        db.session.add(assignment)
        db.session.commit()

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    headers = hmac_headers(
        staff,
        "POST",
        f"/assessments/assignments/{assignment.id}/submit",
        {f"question_{question.id}": "2"},
    )
    response = client.post(
        f"/assessments/assignments/{assignment.id}/submit",
        data={f"question_{question.id}": "2"},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 302

    response = client.get(f"/assessments/assignments/{assignment.id}/results")
    assert response.status_code == 200


def test_manual_grading_workflow(client, app):
    """Short-answer questions skip auto-grade; trainer must grade manually."""
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        staff = User.query.filter_by(username="test_staff").first()
        assessment = Assessment(
            title="Manual Grade Assessment",
            description="",
            created_by=trainer.id,
            passing_score_percent=50,
        )
        db.session.add(assessment)
        db.session.flush()
        question = Question(
            assessment_id=assessment.id,
            question_text="Describe FEFO",
            question_type="short_answer",
            correct_answer="",
            points=10,
        )
        db.session.add(question)
        assignment = AssessmentAssignment(
            assessment_id=assessment.id,
            user_id=staff.id,
            assigned_by=trainer.id,
            assigned_at=datetime.utcnow(),
            status="assigned",
        )
        db.session.add(assignment)
        db.session.commit()

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    submit_data = {f"question_{question.id}": "First expired, first out"}
    headers = hmac_headers(
        staff, "POST",
        f"/assessments/assignments/{assignment.id}/submit",
        submit_data,
    )
    resp = client.post(
        f"/assessments/assignments/{assignment.id}/submit",
        data=submit_data, headers=headers, follow_redirects=False,
    )
    assert resp.status_code == 302

    # No auto-graded result should exist yet
    with app.app_context():
        result = AssessmentResult.query.filter_by(assignment_id=assignment.id).first()
        assert result is None

    # Trainer grades manually
    login_as(client, "trainer")
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        answer = UserAnswer.query.filter_by(assignment_id=assignment.id).first()

    grade_data = {f"score_{answer.id}": "8"}
    headers = hmac_headers(
        trainer, "POST",
        f"/assessments/assignments/{assignment.id}/grade",
        grade_data,
    )
    resp = client.post(
        f"/assessments/assignments/{assignment.id}/grade",
        data=grade_data, headers=headers, follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        result = AssessmentResult.query.filter_by(assignment_id=assignment.id).first()
        assert result is not None
        assert result.total_score == 8
        assert result.passed is True
        assignment_db = AssessmentAssignment.query.get(assignment.id)
        assert assignment_db.status == "graded"


def _make_assessment_with_assignment(app, assignment_status="assigned"):
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        staff = User.query.filter_by(username="test_staff").first()
        assessment = Assessment(
            title="View Test Assessment",
            description="",
            created_by=trainer.id,
            passing_score_percent=70,
        )
        db.session.add(assessment)
        db.session.flush()
        assignment = AssessmentAssignment(
            assessment_id=assessment.id,
            user_id=staff.id,
            assigned_by=trainer.id,
            assigned_at=datetime.utcnow(),
            status=assignment_status,
        )
        db.session.add(assignment)
        db.session.commit()
        return assessment.id, assignment.id


def test_get_assessments_list_trainer(client, app):
    _make_assessment_with_assignment(app)
    login_as(client, "trainer")
    resp = client.get("/assessments/")
    assert resp.status_code == 200
    assert b"View Test Assessment" in resp.data


def test_get_assessment_detail_trainer(client, app):
    assessment_id, _ = _make_assessment_with_assignment(app)
    login_as(client, "trainer")
    resp = client.get(f"/assessments/{assessment_id}")
    assert resp.status_code == 200


def test_get_assessment_detail_staff_without_assignment_forbidden(client, app):
    """Staff with no assignment for an assessment must get 403."""
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        assessment = Assessment(
            title="No-Assign Assessment",
            description="",
            created_by=trainer.id,
            passing_score_percent=70,
        )
        db.session.add(assessment)
        db.session.commit()
        assessment_id = assessment.id

    login_as(client, "staff")
    resp = client.get(f"/assessments/{assessment_id}")
    assert resp.status_code == 403


def test_get_assignments_list_staff(client, app):
    _make_assessment_with_assignment(app)
    login_as(client, "staff")
    resp = client.get("/assessments/assignments")
    assert resp.status_code == 200


def test_get_take_page_staff(client, app):
    _, assignment_id = _make_assessment_with_assignment(app, assignment_status="in_progress")
    login_as(client, "staff")
    resp = client.get(f"/assessments/assignments/{assignment_id}/take")
    assert resp.status_code == 200


def test_get_grade_page_trainer(client, app):
    _, assignment_id = _make_assessment_with_assignment(app, assignment_status="completed")
    login_as(client, "trainer")
    resp = client.get(f"/assessments/assignments/{assignment_id}/grade")
    assert resp.status_code == 200


def test_trainer_can_assign_assessment(client, app):
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        staff = User.query.filter_by(username="test_staff").first()
        assessment = Assessment(
            title="Assign Target", description="", created_by=trainer.id,
            passing_score_percent=70,
        )
        db.session.add(assessment)
        db.session.commit()
        assessment_id = assessment.id
        staff_id = staff.id

    login_as(client, "trainer")
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()

    data = {"user_ids": str(staff_id)}
    headers = hmac_headers(trainer, "POST", f"/assessments/{assessment_id}/assign", data)
    resp = client.post(
        f"/assessments/{assessment_id}/assign",
        data=data, headers=headers, follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        assignment = AssessmentAssignment.query.filter_by(
            assessment_id=assessment_id, user_id=staff_id
        ).first()
        assert assignment is not None
        assert assignment.status == "assigned"


def test_staff_cannot_assign_assessment(client, app):
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        staff = User.query.filter_by(username="test_staff").first()
        assessment = Assessment(
            title="Guard Assign", description="", created_by=trainer.id,
            passing_score_percent=70,
        )
        db.session.add(assessment)
        db.session.commit()
        assessment_id = assessment.id
        staff_id = staff.id

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()

    data = {"user_ids": str(staff_id)}
    headers = hmac_headers(staff, "POST", f"/assessments/{assessment_id}/assign", data)
    resp = client.post(
        f"/assessments/{assessment_id}/assign",
        data=data, headers=headers, follow_redirects=False,
    )
    assert resp.status_code == 403


def test_mixed_question_type_submission_requires_manual_grade(client, app):
    """MC + short_answer in same assessment: auto-grade skipped, status=completed, result=None."""
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        staff = User.query.filter_by(username="test_staff").first()
        assessment = Assessment(
            title="Mixed Type", description="", created_by=trainer.id,
            passing_score_percent=50,
        )
        db.session.add(assessment)
        db.session.flush()
        mc_q = Question(
            assessment_id=assessment.id,
            question_text="What is 2+2?",
            question_type="multiple_choice",
            options='["3","4","5"]',
            correct_answer="4",
            points=5,
        )
        sa_q = Question(
            assessment_id=assessment.id,
            question_text="Describe FEFO.",
            question_type="short_answer",
            correct_answer="",
            points=10,
        )
        db.session.add_all([mc_q, sa_q])
        assignment = AssessmentAssignment(
            assessment_id=assessment.id,
            user_id=staff.id,
            assigned_by=trainer.id,
            assigned_at=datetime.utcnow(),
            status="in_progress",
        )
        db.session.add(assignment)
        db.session.commit()
        assignment_id = assignment.id
        mc_id = mc_q.id
        sa_id = sa_q.id

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()

    submit_data = {f"question_{mc_id}": "4", f"question_{sa_id}": "First expired, first out"}
    headers = hmac_headers(
        staff, "POST",
        f"/assessments/assignments/{assignment_id}/submit",
        submit_data,
    )
    resp = client.post(
        f"/assessments/assignments/{assignment_id}/submit",
        data=submit_data, headers=headers, follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        result = AssessmentResult.query.filter_by(assignment_id=assignment_id).first()
        assert result is None, "Auto-grade must not run when short_answer questions are present"
        a = AssessmentAssignment.query.get(assignment_id)
        assert a.status == "completed"


def test_staff_cannot_access_grade_endpoint(client, app):
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        staff = User.query.filter_by(username="test_staff").first()
        assessment = Assessment(
            title="Guard Assessment", description="", created_by=trainer.id,
            passing_score_percent=70,
        )
        db.session.add(assessment)
        db.session.flush()
        assignment = AssessmentAssignment(
            assessment_id=assessment.id, user_id=staff.id,
            assigned_by=trainer.id, assigned_at=datetime.utcnow(), status="completed",
        )
        db.session.add(assignment)
        db.session.commit()

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    headers = hmac_headers(staff, "POST", f"/assessments/assignments/{assignment.id}/grade", {})
    resp = client.post(
        f"/assessments/assignments/{assignment.id}/grade",
        data={}, headers=headers,
    )
    assert resp.status_code == 403
