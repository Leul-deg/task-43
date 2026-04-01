from datetime import date, datetime, timedelta, timezone
import base64
import hashlib
import os
import secrets

from cryptography.fernet import Fernet
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_fernet():
    secret = os.getenv("SECRET_KEY", "fallback-secret-key-change-me")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


product_tags = db.Table(
    "product_tags",
    db.Column("product_id", db.Integer, db.ForeignKey("product.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tag.id"), primary_key=True),
)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    hmac_key = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    is_locked = db.Column(db.Boolean, default=False)
    failed_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    def set_password(self, password):
        if len(password) < 12:
            raise ValueError("Password must be at least 12 characters.")
        # Werkzeug's generate_password_hash uses salted scrypt (default),
        # satisfying the "salted hashing" requirement.
        self.password_hash = generate_password_hash(password)
        if not self.hmac_key:
            self.set_hmac_key()

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_account_locked(self):
        if self.locked_until and utcnow() < self.locked_until:
            return True
        return False

    def set_hmac_key(self, raw_key=None):
        if raw_key is None:
            raw_key = secrets.token_hex(32)
        f = _get_fernet()
        self.hmac_key = f.encrypt(raw_key.encode()).decode()
        return raw_key

    def get_hmac_key(self):
        f = _get_fernet()
        return f.decrypt(self.hmac_key.encode()).decode()


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    action = db.Column(db.String(120), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    @staticmethod
    def hash_ip(ip_address):
        if not ip_address:
            return None
        return hashlib.sha256(ip_address.encode()).hexdigest()[:16]


class UsedNonce(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nonce = db.Column(db.String(255), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    @classmethod
    def is_replay(cls, nonce):
        return db.session.query(cls.id).filter_by(nonce=nonce).first() is not None

    @classmethod
    def cleanup_expired(cls):
        cutoff = utcnow() - timedelta(hours=24)
        cls.query.filter(cls.created_at < cutoff).delete(synchronize_session=False)
        db.session.commit()


class AnomalyAlert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    rule_triggered = db.Column(db.String(120), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    severity = db.Column(db.String(20), nullable=False)
    is_reviewed = db.Column(db.Boolean, default=False)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    primary_image = db.Column(db.String(255), nullable=True)
    is_published = db.Column(db.Boolean, default=True)
    purchase_limit = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    variants = db.relationship("ProductVariant", back_populates="product", lazy=True)
    tags = db.relationship("Tag", secondary=product_tags, back_populates="products", lazy=True)


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)

    products = db.relationship("Product", secondary=product_tags, back_populates="tags", lazy=True)


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)


class ProductVariant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    sku = db.Column(db.String(120), unique=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=True)
    base_price = db.Column(db.Float, nullable=False)
    version = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)

    __mapper_args__ = {"version_id_col": version}

    product = db.relationship("Product", back_populates="variants")
    tiered_prices = db.relationship("TieredPrice", back_populates="variant", lazy=True)
    batches = db.relationship("Batch", back_populates="variant", lazy=True)


class TieredPrice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variant.id"), nullable=False)
    min_quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)

    variant = db.relationship("ProductVariant", back_populates="tiered_prices")


class Warehouse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    location = db.Column(db.String(255), nullable=True)


class Bin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("warehouse.id"), nullable=False)
    label = db.Column(db.String(120), nullable=False)


class Batch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variant.id"), nullable=False)
    bin_id = db.Column(db.Integer, db.ForeignKey("bin.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    expiration_date = db.Column(db.Date, nullable=True)
    received_at = db.Column(db.DateTime, default=utcnow)

    variant = db.relationship("ProductVariant", back_populates="batches")


class StockCount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("batch.id"), nullable=False)
    expected_qty = db.Column(db.Integer, nullable=False)
    counted_qty = db.Column(db.Integer, nullable=False)
    variance = db.Column(db.Float, nullable=False)
    variance_pct = db.Column(db.Float, nullable=False)
    variance_reason = db.Column(db.Text, nullable=True)
    counted_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    counted_at = db.Column(db.DateTime, default=utcnow)


class Reservation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variant.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    booking_datetime = db.Column(db.DateTime, nullable=True)
    held_at = db.Column(db.DateTime, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    confirmed_at = db.Column(db.DateTime, nullable=True)
    unit_price = db.Column(db.Float, nullable=True)
    total_price = db.Column(db.Float, nullable=True)


class PriceRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variant.id"), nullable=False)
    rule_type = db.Column(db.String(20), nullable=False)
    value = db.Column(db.Float, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    min_booking_minutes = db.Column(db.Integer, default=60)
    advance_min_hours = db.Column(db.Integer, default=2)
    advance_max_days = db.Column(db.Integer, default=60)
    created_at = db.Column(db.DateTime, default=utcnow)


class NewsSource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    source_type = db.Column(db.String(20), nullable=False)
    filename_prefix = db.Column(db.String(100), nullable=True)
    parsing_rules = db.Column(db.Text, nullable=True)
    is_allowed = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)


class NewsItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("news_source.id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    content = db.Column(db.Text, nullable=True)
    author = db.Column(db.String(120), nullable=True)
    published_date = db.Column(db.DateTime, nullable=True)
    ingested_at = db.Column(db.DateTime, default=utcnow)
    file_hash = db.Column(db.String(255), nullable=False)


class IngestionLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("news_source.id"), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    message = db.Column(db.Text, nullable=True)
    retries = db.Column(db.Integer, default=0)
    started_at = db.Column(db.DateTime, default=utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)


class QuarantinedFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    file_hash = db.Column(db.String(255), nullable=False)
    quarantined_at = db.Column(db.DateTime, default=utcnow)


class SavedSearch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    query_params = db.Column(db.Text, nullable=False)
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class Assessment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    is_published = db.Column(db.Boolean, default=False)
    time_limit_minutes = db.Column(db.Integer, nullable=True)
    passing_score_percent = db.Column(db.Integer, default=70)
    created_at = db.Column(db.DateTime, default=utcnow)


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessment.id"), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    question_type = db.Column(db.String(30), nullable=False)
    options = db.Column(db.Text, nullable=True)
    correct_answer = db.Column(db.Text, nullable=False)
    points = db.Column(db.Integer, default=1)


class AssessmentAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assessment_id = db.Column(db.Integer, db.ForeignKey("assessment.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    assigned_at = db.Column(db.DateTime, default=utcnow)
    due_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)


class UserAnswer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("assessment_assignment.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("question.id"), nullable=False)
    answer_text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, nullable=True)
    points_earned = db.Column(db.Integer, default=0)


class AssessmentResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(
        db.Integer, db.ForeignKey("assessment_assignment.id"), unique=True, nullable=False
    )
    total_score = db.Column(db.Integer, nullable=False)
    max_score = db.Column(db.Integer, nullable=False)
    percentage = db.Column(db.Float, nullable=False)
    passed = db.Column(db.Boolean, nullable=False)
    graded_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    graded_at = db.Column(db.DateTime, nullable=True)
