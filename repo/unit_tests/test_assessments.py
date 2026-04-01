from datetime import datetime

from app.extensions import db
from app.models import Assessment, AssessmentAssignment, Question, User, UserAnswer, AssessmentResult
from conftest import hmac_headers, login_as


def test_assessment_flow(client, app):
    login_as(client, "trainer")
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        staff = User.query.filter_by(username="test_staff").first()
        assessment = Assessment(
            title="Basics",
            description="Test",
            created_by=trainer.id,
            passing_score_percent=70,
        )
        db.session.add(assessment)
        db.session.flush()
        question = Question(
            assessment_id=assessment.id,
            question_text="2+2",
            question_type="multiple_choice",
            options='["4","5"]',
            correct_answer="4",
            points=1,
        )
        db.session.add(question)
        assignment = AssessmentAssignment(
            assessment_id=assessment.id,
            user_id=staff.id,
            assigned_by=trainer.id,
            status="assigned",
            assigned_at=datetime.utcnow(),
        )
        db.session.add(assignment)
        db.session.commit()

    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
        headers = hmac_headers(staff, "POST", f"/assessments/assignments/{assignment.id}/start")
    response = client.post(
        f"/assessments/assignments/{assignment.id}/start", headers=headers, follow_redirects=False
    )
    assert response.status_code == 302

    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
        headers = hmac_headers(
            staff,
            "POST",
            f"/assessments/assignments/{assignment.id}/submit",
            {f"question_{question.id}": "4"},
        )
    response = client.post(
        f"/assessments/assignments/{assignment.id}/submit",
        data={f"question_{question.id}": "4"},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        result = AssessmentResult.query.filter_by(assignment_id=assignment.id).first()
        assert result is not None
        assert result.passed is True


def test_assessment_fail_threshold(client, app):
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        staff = User.query.filter_by(username="test_staff").first()
        assessment = Assessment(
            title="Fail Test",
            description="",
            created_by=trainer.id,
            passing_score_percent=100,
        )
        db.session.add(assessment)
        db.session.flush()
        question = Question(
            assessment_id=assessment.id,
            question_text="2+3",
            question_type="multiple_choice",
            options='["4","5"]',
            correct_answer="5",
            points=1,
        )
        db.session.add(question)
        assignment = AssessmentAssignment(
            assessment_id=assessment.id,
            user_id=staff.id,
            assigned_by=trainer.id,
            status="assigned",
            assigned_at=datetime.utcnow(),
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
            {f"question_{question.id}": "4"},
        )
    response = client.post(
        f"/assessments/assignments/{assignment.id}/submit",
        data={f"question_{question.id}": "4"},
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        result = AssessmentResult.query.filter_by(assignment_id=assignment.id).first()
        assert result is not None
        assert result.passed is False
