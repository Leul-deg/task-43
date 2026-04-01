from datetime import timedelta

from flask import Blueprint, render_template
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..models import (
    AnomalyAlert,
    AssessmentAssignment,
    Batch,
    NewsItem,
    Product,
    SavedSearch,
    User,
    utcnow,
)

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@jwt_required()
def index():
    identity = get_jwt_identity()
    user = User.query.get(identity) if identity else None
    published_products = Product.query.filter_by(is_published=True).count()

    today = utcnow().date()
    expiring_7 = (
        Batch.query.filter(Batch.expiration_date != None)
        .filter(Batch.expiration_date <= today + timedelta(days=7))
        .count()
    )

    news_24h = NewsItem.query.filter(
        NewsItem.ingested_at >= utcnow() - timedelta(hours=24)
    ).count()

    pending_assignments = 0
    if user:
        if user.role in ["admin", "trainer"]:
            pending_assignments = AssessmentAssignment.query.filter(
                AssessmentAssignment.status.in_(["assigned", "in_progress"])
            ).count()
        else:
            pending_assignments = AssessmentAssignment.query.filter(
                AssessmentAssignment.user_id == user.id,
                AssessmentAssignment.status.in_(["assigned", "in_progress"]),
            ).count()

    unreviewed_anomalies = 0
    if user and user.role == "admin":
        unreviewed_anomalies = AnomalyAlert.query.filter_by(is_reviewed=False).count()
    saved_search_count = SavedSearch.query.filter_by(user_id=user.id).count() if user else 0
    return render_template(
        "dashboard/index.html",
        username=user.username if user else "",
        role=user.role if user else "",
        published_products=published_products,
        expiring_7=expiring_7,
        news_24h=news_24h,
        pending_assignments=pending_assignments,
        unreviewed_anomalies=unreviewed_anomalies,
        saved_search_count=saved_search_count,
    )
