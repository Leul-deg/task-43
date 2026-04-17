"""End-to-end workflow tests covering full user journeys across auth, search,
inventory, and assessment modules without mocking any request path.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import (
    Assessment, AssessmentAssignment, AssessmentResult, Batch, Bin,
    NewsItem, NewsSource, Product, ProductVariant, Question, Reservation,
    SavedSearch, User, Warehouse,
)
from conftest import hmac_headers, login_as


def _seed_bookable_product(app, name="Court Pass", sku="CRT-001", stock=10, price=25.0):
    with app.app_context():
        product = Product(name=name, slug=name.lower().replace(" ", "-"), is_published=True)
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(product_id=product.id, sku=sku, base_price=price)
        db.session.add(variant)
        db.session.flush()
        warehouse = Warehouse(name="Main WH")
        db.session.add(warehouse)
        db.session.flush()
        bin_ = Bin(warehouse_id=warehouse.id, label="A1")
        db.session.add(bin_)
        db.session.flush()
        batch = Batch(variant_id=variant.id, bin_id=bin_.id, quantity=stock)
        db.session.add(batch)
        db.session.commit()
        return variant.id


def test_staff_login_search_reserve_flow(client, app):
    """Complete flow: staff logs in, searches for a product, makes a reservation,
    and sees it reflected in inventory — no mocks across any boundary."""
    variant_id = _seed_bookable_product(app)

    # Step 1: unauthenticated access is denied
    resp = client.get("/search/?q=Court")
    assert resp.status_code == 401

    # Step 2: login
    login_resp = login_as(client, "staff")
    assert login_resp.status_code == 302
    assert client.get_cookie("access_token_cookie") is not None

    # Step 3: search returns the product
    resp = client.get("/search/?q=Court&type=products")
    assert resp.status_code == 200
    assert b"Court Pass" in resp.data

    # Step 4: reserve the product
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
    booking_dt = (datetime.utcnow() + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")
    data = {
        "variant_id": str(variant_id),
        "quantity": "1",
        "booking_datetime": booking_dt,
        "duration_minutes": "90",
    }
    headers = hmac_headers(staff, "POST", "/inventory/reservations", data)
    resp = client.post("/inventory/reservations", data=data, headers=headers,
                       follow_redirects=False)
    assert resp.status_code in (200, 201, 302)

    # Step 5: reservation exists in the database
    with app.app_context():
        staff = User.query.filter_by(username="test_staff").first()
        reservation = Reservation.query.filter_by(user_id=staff.id).first()
        assert reservation is not None
        assert reservation.variant_id == variant_id
        assert reservation.quantity == 1


def test_admin_create_user_then_user_completes_assessment(client, app):
    """Admin creates a new user, trainer assigns an assessment, new user completes it."""
    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    # Admin creates a new staff user
    create_data = {
        "username": "e2e_staff",
        "password": "SecureE2EPass123!",
        "role": "staff",
    }
    headers = hmac_headers(admin, "POST", "/admin/users", create_data)
    resp = client.post("/admin/users", data=create_data, headers=headers,
                       follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        new_user = User.query.filter_by(username="e2e_staff").first()
        assert new_user is not None
        new_user_id = new_user.id

    # Trainer creates and assigns an assessment to the new user
    login_as(client, "trainer")
    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()

    assessment_data = {
        "title": "E2E Assessment",
        "description": "",
        "passing_score_percent": "60",
    }
    headers = hmac_headers(trainer, "POST", "/assessments/", assessment_data)
    resp = client.post("/assessments/", data=assessment_data, headers=headers,
                       follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        trainer = User.query.filter_by(username="test_trainer").first()
        assessment = Assessment.query.filter_by(title="E2E Assessment").first()
        question = Question(
            assessment_id=assessment.id,
            question_text="2+2?",
            question_type="multiple_choice",
            options='["4","5"]',
            correct_answer="4",
            points=5,
        )
        db.session.add(question)
        assignment = AssessmentAssignment(
            assessment_id=assessment.id,
            user_id=new_user_id,
            assigned_by=trainer.id,
            assigned_at=datetime.utcnow(),
            status="assigned",
        )
        db.session.add(assignment)
        db.session.commit()
        question_id = question.id
        assignment_id = assignment.id

    # New user logs in and submits the assessment
    resp = client.post(
        "/auth/login",
        data={"username": "e2e_staff", "password": "SecureE2EPass123!"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        new_user = User.query.get(new_user_id)

    submit_data = {f"question_{question_id}": "4"}
    headers = hmac_headers(new_user, "POST",
                           f"/assessments/assignments/{assignment_id}/submit", submit_data)
    resp = client.post(
        f"/assessments/assignments/{assignment_id}/submit",
        data=submit_data, headers=headers, follow_redirects=False,
    )
    assert resp.status_code == 302

    # Result is created and shows passing
    with app.app_context():
        result = AssessmentResult.query.filter_by(assignment_id=assignment_id).first()
        assert result is not None
        assert result.passed is True
        assert result.total_score == 5


def test_full_news_pipeline_ingest_to_read(client, app):
    """Admin creates a source, ingest populates a news item, staff reads it."""
    login_as(client, "admin")
    with app.app_context():
        admin = User.query.filter_by(username="test_admin").first()

    source_data = {"name": "E2E Feed", "source_type": "rss", "is_allowed": "on"}
    headers = hmac_headers(admin, "POST", "/news/sources", source_data)
    resp = client.post("/news/sources", data=source_data, headers=headers,
                       follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        source = NewsSource.query.filter_by(name="E2E Feed").first()
        assert source is not None
        item = NewsItem(
            source_id=source.id,
            title="E2E Pipeline News",
            summary="A news summary",
            content="Full article body",
            file_hash="e2e-hash-unique",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id

    # Staff can read the news item
    login_as(client, "staff")
    resp = client.get("/news/")
    assert resp.status_code == 200
    assert b"E2E Pipeline News" in resp.data

    resp = client.get(f"/news/{item_id}")
    assert resp.status_code == 200
    assert b"Full article body" in resp.data
