import json
from datetime import datetime

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..decorators import hmac_required, role_required
from ..extensions import db
from ..utils import safe_int
from ..models import (
    Assessment,
    AssessmentAssignment,
    AssessmentResult,
    Question,
    User,
    UserAnswer,
    utcnow,
)

assessments_bp = Blueprint("assessments", __name__)


def _current_user():
    identity = get_jwt_identity()
    return User.query.get(identity) if identity else None


@assessments_bp.route("/", methods=["GET"])
@jwt_required()
@role_required("admin", "trainer", "staff")
def index():
    user = _current_user()
    if user and user.role in ("trainer", "admin"):
        assessments = Assessment.query.order_by(Assessment.created_at.desc()).all()
    else:
        assessments = (
            Assessment.query.join(AssessmentAssignment)
            .filter(AssessmentAssignment.user_id == user.id)
            .order_by(AssessmentAssignment.assigned_at.desc())
            .all()
        )
    return render_template("assessments/list.html", assessments=assessments, user=user)


@assessments_bp.route("/", methods=["POST"])
@jwt_required()
@role_required("trainer")
@hmac_required
def create_assessment():
    assessment = Assessment(
        title=request.form.get("title", "").strip(),
        description=request.form.get("description", ""),
        created_by=get_jwt_identity(),
        time_limit_minutes=safe_int(request.form.get("time_limit_minutes"))
        if request.form.get("time_limit_minutes")
        else None,
        passing_score_percent=safe_int(request.form.get("passing_score_percent"), 70),
        is_published=request.form.get("is_published") == "on",
    )
    db.session.add(assessment)
    db.session.commit()
    return redirect(url_for("assessments.detail", assessment_id=assessment.id))


@assessments_bp.route("/<int:assessment_id>", methods=["GET"])
@jwt_required()
@role_required("trainer", "staff", "admin")
def detail(assessment_id):
    assessment = Assessment.query.get_or_404(assessment_id)
    questions = Question.query.filter_by(assessment_id=assessment_id).all()
    user = _current_user()
    assignment = None
    if user and user.role == "staff":
        assignment = AssessmentAssignment.query.filter_by(
            assessment_id=assessment_id, user_id=user.id
        ).first()
        if not assignment:
            return abort(403)
    staff_users = User.query.filter_by(role="staff").order_by(User.username.asc()).all()
    return render_template(
        "assessments/detail.html",
        assessment=assessment,
        questions=questions,
        assignment=assignment,
        staff_users=staff_users,
        user=user,
    )


@assessments_bp.route("/<int:assessment_id>", methods=["PUT"])
@jwt_required()
@role_required("trainer")
@hmac_required
def update_assessment(assessment_id):
    assessment = Assessment.query.get_or_404(assessment_id)
    assessment.title = request.form.get("title", assessment.title)
    assessment.description = request.form.get("description", assessment.description)
    assessment.time_limit_minutes = (
        safe_int(request.form.get("time_limit_minutes"))
        if request.form.get("time_limit_minutes")
        else None
    )
    assessment.passing_score_percent = safe_int(
        request.form.get("passing_score_percent", assessment.passing_score_percent)
    )
    db.session.commit()
    return redirect(url_for("assessments.detail", assessment_id=assessment_id))


@assessments_bp.route("/<int:assessment_id>/toggle-publish", methods=["POST"])
@jwt_required()
@role_required("trainer")
@hmac_required
def toggle_publish(assessment_id):
    assessment = Assessment.query.get_or_404(assessment_id)
    assessment.is_published = not assessment.is_published
    db.session.commit()
    return render_template("assessments/partials/publish_button.html", assessment=assessment)


@assessments_bp.route("/<int:assessment_id>/questions", methods=["POST"])
@jwt_required()
@role_required("trainer")
@hmac_required
def add_question(assessment_id):
    question = Question(
        assessment_id=assessment_id,
        question_text=request.form.get("question_text", ""),
        question_type=request.form.get("question_type", "multiple_choice"),
        options=request.form.get("options") or None,
        correct_answer=request.form.get("correct_answer", ""),
        points=safe_int(request.form.get("points", 1)),
    )
    db.session.add(question)
    db.session.commit()
    return render_template("assessments/partials/question_row.html", question=question)


@assessments_bp.route("/questions/<int:question_id>", methods=["PUT"])
@jwt_required()
@role_required("trainer")
@hmac_required
def update_question(question_id):
    question = Question.query.get_or_404(question_id)
    question.question_text = request.form.get("question_text", question.question_text)
    question.question_type = request.form.get("question_type", question.question_type)
    question.options = request.form.get("options", question.options)
    question.correct_answer = request.form.get("correct_answer", question.correct_answer)
    question.points = safe_int(request.form.get("points", question.points))
    db.session.commit()
    return render_template("assessments/partials/question_row.html", question=question)


@assessments_bp.route("/questions/<int:question_id>", methods=["DELETE"])
@jwt_required()
@role_required("trainer")
@hmac_required
def delete_question(question_id):
    question = Question.query.get_or_404(question_id)
    db.session.delete(question)
    db.session.commit()
    return "", 204


@assessments_bp.route("/<int:assessment_id>/assign", methods=["POST"])
@jwt_required()
@role_required("trainer")
@hmac_required
def assign_assessment(assessment_id):
    user_ids = request.form.getlist("user_ids")
    due_date = request.form.get("due_date")
    for user_id in user_ids:
        assignment = AssessmentAssignment(
            assessment_id=assessment_id,
            user_id=safe_int(user_id),
            assigned_by=get_jwt_identity(),
            assigned_at=utcnow(),
            due_date=datetime.strptime(due_date, "%Y-%m-%d").date() if due_date else None,
            status="assigned",
        )
        db.session.add(assignment)
    db.session.commit()
    return redirect(url_for("assessments.detail", assessment_id=assessment_id))


@assessments_bp.route("/assignments", methods=["GET"])
@jwt_required()
@role_required("staff")
def assignments():
    assignments_list = AssessmentAssignment.query.filter_by(
        user_id=get_jwt_identity()
    ).order_by(AssessmentAssignment.assigned_at.desc()).all()
    assessment_ids = [assignment.assessment_id for assignment in assignments_list]
    assessments = Assessment.query.filter(Assessment.id.in_(assessment_ids)).all()
    assessment_map = {assessment.id: assessment for assessment in assessments}
    return render_template(
        "assessments/assignments.html",
        assignments=assignments_list,
        assessment_map=assessment_map,
    )


@assessments_bp.route("/assignments/<int:assignment_id>/start", methods=["POST"])
@jwt_required()
@role_required("staff")
@hmac_required
def start_assignment(assignment_id):
    assignment = AssessmentAssignment.query.get_or_404(assignment_id)
    if assignment.user_id != get_jwt_identity():
        return abort(403)
    assignment.status = "in_progress"
    assignment.started_at = utcnow()
    db.session.commit()
    return redirect(url_for("assessments.take", assignment_id=assignment_id))


@assessments_bp.route("/assignments/<int:assignment_id>/take", methods=["GET"])
@jwt_required()
@role_required("staff")
def take(assignment_id):
    assignment = AssessmentAssignment.query.get_or_404(assignment_id)
    if assignment.user_id != get_jwt_identity():
        return abort(403)
    questions = Question.query.filter_by(assessment_id=assignment.assessment_id).all()
    assessment = Assessment.query.get_or_404(assignment.assessment_id)
    question_options = {}
    for question in questions:
        if question.options:
            try:
                question_options[question.id] = json.loads(question.options)
            except Exception:
                question_options[question.id] = []
        else:
            question_options[question.id] = []
    return render_template(
        "assessments/take.html",
        assignment=assignment,
        assessment=assessment,
        questions=questions,
        question_options=question_options,
    )


@assessments_bp.route("/assignments/<int:assignment_id>/submit", methods=["POST"])
@jwt_required()
@role_required("staff")
@hmac_required
def submit_assignment(assignment_id):
    assignment = AssessmentAssignment.query.get_or_404(assignment_id)
    if assignment.user_id != get_jwt_identity():
        return abort(403)
    questions = Question.query.filter_by(assessment_id=assignment.assessment_id).all()
    assessment = Assessment.query.get_or_404(assignment.assessment_id)

    max_score = 0
    total_score = 0
    has_short = False

    for question in questions:
        answer_text = request.form.get(f"question_{question.id}", "")
        is_correct = None
        points_earned = 0
        max_score += question.points

        if question.question_type in ["multiple_choice", "true_false"]:
            is_correct = answer_text.strip().lower() == question.correct_answer.strip().lower()
            points_earned = question.points if is_correct else 0
            total_score += points_earned
        else:
            has_short = True

        db.session.add(
            UserAnswer(
                assignment_id=assignment.id,
                question_id=question.id,
                answer_text=answer_text,
                is_correct=is_correct,
                points_earned=points_earned,
            )
        )

    assignment.status = "completed"
    assignment.submitted_at = utcnow()
    db.session.commit()

    if not has_short:
        percentage = (total_score / max_score * 100) if max_score else 0
        result = AssessmentResult(
            assignment_id=assignment.id,
            total_score=total_score,
            max_score=max_score,
            percentage=percentage,
            passed=percentage >= assessment.passing_score_percent,
        )
        db.session.add(result)
        db.session.commit()

    return redirect(url_for("assessments.results", assignment_id=assignment.id))


@assessments_bp.route("/assignments/<int:assignment_id>/results", methods=["GET"])
@jwt_required()
@role_required("staff", "trainer", "admin")
def results(assignment_id):
    assignment = AssessmentAssignment.query.get_or_404(assignment_id)
    user = _current_user()
    if user and user.role == "staff" and assignment.user_id != user.id:
        return abort(403)
    questions = Question.query.filter_by(assessment_id=assignment.assessment_id).all()
    assessment = Assessment.query.get_or_404(assignment.assessment_id)
    answers = UserAnswer.query.filter_by(assignment_id=assignment.id).all()
    result = AssessmentResult.query.filter_by(assignment_id=assignment.id).first()

    if not result and assignment.status in ["completed", "graded"]:
        max_score = sum(question.points for question in questions)
        total_score = sum(answer.points_earned for answer in answers)
        percentage = (total_score / max_score * 100) if max_score else 0
        result = AssessmentResult(
            assignment_id=assignment.id,
            total_score=total_score,
            max_score=max_score,
            percentage=percentage,
            passed=percentage >= assessment.passing_score_percent,
        )
        db.session.add(result)
        db.session.commit()

    return render_template(
        "assessments/results.html",
        assignment=assignment,
        questions=questions,
        answers=answers,
        result=result,
        user=user,
    )


@assessments_bp.route("/assignments/<int:assignment_id>/grade", methods=["GET", "POST"])
@jwt_required()
@role_required("trainer")
@hmac_required
def grade(assignment_id):
    assignment = AssessmentAssignment.query.get_or_404(assignment_id)
    questions = Question.query.filter_by(assessment_id=assignment.assessment_id).all()
    assessment = Assessment.query.get_or_404(assignment.assessment_id)
    answers = UserAnswer.query.filter_by(assignment_id=assignment.id).all()
    if request.method == "POST":
        total_score = 0
        max_score = sum(question.points for question in questions)
        for answer in answers:
            question = next(q for q in questions if q.id == answer.question_id)
            if question.question_type == "short_answer":
                score = safe_int(request.form.get(f"score_{answer.id}", 0))
                answer.points_earned = score
                answer.is_correct = score == question.points
            total_score += answer.points_earned
        percentage = (total_score / max_score * 100) if max_score else 0
        result = AssessmentResult.query.filter_by(assignment_id=assignment.id).first()
        if not result:
            result = AssessmentResult(
                assignment_id=assignment.id,
                total_score=total_score,
                max_score=max_score,
                percentage=percentage,
                passed=percentage >= assessment.passing_score_percent,
                graded_by=get_jwt_identity(),
                graded_at=utcnow(),
            )
            db.session.add(result)
        else:
            result.total_score = total_score
            result.max_score = max_score
            result.percentage = percentage
            result.passed = percentage >= assessment.passing_score_percent
            result.graded_by = get_jwt_identity()
            result.graded_at = utcnow()
        assignment.status = "graded"
        db.session.commit()
        return redirect(url_for("assessments.results", assignment_id=assignment.id))

    return render_template(
        "assessments/grade.html",
        assignment=assignment,
        questions=questions,
        answers=answers,
    )
