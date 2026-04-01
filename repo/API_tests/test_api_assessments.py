from datetime import datetime

from app.extensions import db
from app.models import Assessment, AssessmentAssignment, Question, User
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
