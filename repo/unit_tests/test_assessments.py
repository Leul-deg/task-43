from datetime import datetime

from app.extensions import db
from app.models import (
    Assessment, AssessmentAssignment, AssessmentResult, Question, User, UserAnswer,
)
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


def _make_assessment_with_assignment(app, question_type="multiple_choice"):
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        staff = User.query.filter_by(username="test_staff").first()
        assessment = Assessment(
            title="Base Assessment",
            description="",
            created_by=trainer.id,
            passing_score_percent=70,
        )
        db.session.add(assessment)
        db.session.flush()
        question = Question(
            assessment_id=assessment.id,
            question_text="Q?",
            question_type=question_type,
            options='["A","B"]' if question_type == "multiple_choice" else None,
            correct_answer="A",
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
        return assessment.id, question.id, assignment.id


def test_update_assessment(client, app):
    assessment_id, _, _ = _make_assessment_with_assignment(app)

    login_as(client, "trainer")
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()

    data = {"title": "Updated Title", "passing_score_percent": "80"}
    headers = hmac_headers(trainer, "PUT", f"/assessments/{assessment_id}", data)
    resp = client.put(f"/assessments/{assessment_id}", data=data, headers=headers,
                      follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        a = Assessment.query.get(assessment_id)
        assert a.title == "Updated Title"
        assert a.passing_score_percent == 80


def test_toggle_publish_assessment(client, app):
    assessment_id, _, _ = _make_assessment_with_assignment(app)

    login_as(client, "trainer")
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()

    headers = hmac_headers(trainer, "POST", f"/assessments/{assessment_id}/toggle-publish")
    resp = client.post(f"/assessments/{assessment_id}/toggle-publish", headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        assert Assessment.query.get(assessment_id).is_published is True


def test_add_update_delete_question(client, app):
    assessment_id, _, _ = _make_assessment_with_assignment(app)

    login_as(client, "trainer")
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()

    # Add question
    data = {
        "question_text": "New Q?",
        "question_type": "multiple_choice",
        "options": '["X","Y"]',
        "correct_answer": "X",
        "points": "2",
    }
    headers = hmac_headers(trainer, "POST", f"/assessments/{assessment_id}/questions", data)
    resp = client.post(f"/assessments/{assessment_id}/questions", data=data, headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        question = Question.query.filter_by(
            assessment_id=assessment_id, question_text="New Q?"
        ).first()
        assert question is not None
        assert question.points == 2
        q_id = question.id

    # Update question
    update_data = {"question_text": "Updated Q?", "question_type": "multiple_choice",
                   "correct_answer": "Y", "points": "3"}
    headers = hmac_headers(trainer, "PUT", f"/assessments/questions/{q_id}", update_data)
    resp = client.put(f"/assessments/questions/{q_id}", data=update_data, headers=headers)
    assert resp.status_code == 200

    with app.app_context():
        q = Question.query.get(q_id)
        assert q.question_text == "Updated Q?"
        assert q.points == 3

    # Delete question
    headers = hmac_headers(trainer, "DELETE", f"/assessments/questions/{q_id}")
    resp = client.delete(f"/assessments/questions/{q_id}", headers=headers)
    assert resp.status_code == 204

    with app.app_context():
        assert Question.query.get(q_id) is None


def test_peer_trainer_cannot_update_question(client, app):
    assessment_id, question_id, _ = _make_assessment_with_assignment(app)
    with app.app_context():
        peer = User(username="peer_trainer", role="trainer")
        peer.set_password("TestPassword123!")
        db.session.add(peer)
        db.session.commit()

    client.post(
        "/auth/login",
        data={"username": "peer_trainer", "password": "TestPassword123!"},
        follow_redirects=False,
    )
    with app.app_context():
        peer = User.query.filter_by(username="peer_trainer").first()
    update_data = {"question_text": "Hacked", "question_type": "multiple_choice",
                   "correct_answer": "A", "points": "1"}
    headers = hmac_headers(
        peer, "PUT", f"/assessments/questions/{question_id}", update_data
    )
    resp = client.put(
        f"/assessments/questions/{question_id}",
        data=update_data,
        headers=headers,
        follow_redirects=False,
    )
    assert resp.status_code == 403


def test_staff_cannot_view_other_staff_results(client, app):
    assessment_id, question_id, assignment_id = _make_assessment_with_assignment(app)

    # Submit assignment as original staff so a result exists
    login_as(client, "staff")
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    submit_data = {f"question_{question_id}": "A"}
    headers = hmac_headers(staff, "POST",
                           f"/assessments/assignments/{assignment_id}/submit", submit_data)
    client.post(f"/assessments/assignments/{assignment_id}/submit",
                data=submit_data, headers=headers, follow_redirects=False)

    # Create a second staff user and try to access the first staff's results
    with app.app_context():
        staff2 = User(username="test_staff2", role="staff")
        staff2.set_password("TestPassword123!")
        db.session.add(staff2)
        db.session.commit()

    client.post("/auth/login",
                data={"username": "test_staff2", "password": "TestPassword123!"},
                follow_redirects=False)

    resp = client.get(f"/assessments/assignments/{assignment_id}/results")
    assert resp.status_code == 403


def test_other_staff_cannot_start_assignment(client, app):
    _, _, assignment_id = _make_assessment_with_assignment(app)

    # Create second staff user
    with app.app_context():
        intruder = User(username="test_intruder", role="staff")
        intruder.set_password("TestPassword123!")
        db.session.add(intruder)
        db.session.commit()
        intruder = User.query.filter_by(username="test_intruder").first()

    client.post("/auth/login",
                data={"username": "test_intruder", "password": "TestPassword123!"},
                follow_redirects=False)

    with app.app_context():
        intruder = User.query.filter_by(username="test_intruder").first()
    headers = hmac_headers(intruder, "POST",
                           f"/assessments/assignments/{assignment_id}/start")
    resp = client.post(f"/assessments/assignments/{assignment_id}/start",
                       headers=headers, follow_redirects=False)
    assert resp.status_code == 403
