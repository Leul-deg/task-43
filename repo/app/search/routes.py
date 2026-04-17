import json
from datetime import timedelta

from flask import Blueprint, abort, render_template, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from markupsafe import Markup, escape

from ..decorators import hmac_required, role_required
from ..extensions import db
from sqlalchemy import func, literal, or_, select

from ..models import (
    AnomalyAlert,
    AuditLog,
    Category,
    NewsItem,
    Product,
    ProductVariant,
    Question,
    SavedSearch,
    Tag,
    utcnow,
)
from ..utils import parse_date, safe_float, safe_int

search_bp = Blueprint("search", __name__)


def highlight(text, term):
    if not text:
        return ""
    if not term:
        return Markup(escape(text[:150]))
    lowered = text.lower()
    term_lower = term.lower()
    index = lowered.find(term_lower)
    if index == -1:
        return Markup(escape(text[:150]))
    start = max(index - 60, 0)
    end = min(index + 90, len(text))
    snippet = text[start:end]
    snippet_lower = snippet.lower()
    inner_index = snippet_lower.find(term_lower)
    if inner_index == -1:
        return Markup(escape(snippet))
    before = escape(snippet[:inner_index])
    match = escape(snippet[inner_index:inner_index + len(term)])
    after = escape(snippet[inner_index + len(term):])
    return Markup(f"{before}<mark>{match}</mark>{after}")


@search_bp.route("/", methods=["GET"])
@jwt_required()
@role_required("admin", "content_editor", "inventory_manager", "trainer", "staff")
def index():
    q = request.args.get("q", "").strip()
    search_type = request.args.get("type", "all")
    category_id = request.args.get("category_id")
    tag_id = request.args.get("tag_id")
    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    sort = request.args.get("sort", "recency")
    page = safe_int(request.args.get("page", 1))
    per_page = 25
    parsed_date_from = parse_date(date_from) if date_from else None
    parsed_date_to = parse_date(date_to) if date_to else None
    if date_from and not parsed_date_from:
        return abort(400)
    if date_to and not parsed_date_to:
        return abort(400)

    now = utcnow()
    total = 0
    paginated = []

    def _build_product_query():
        pq = ProductVariant.query.join(Product).filter(Product.is_published.is_(True))
        if q:
            for term in q.split():
                like = f"%{term}%"
                fuzzy = "%" + "%".join(list(term)) + "%"
                pq = pq.filter(
                    or_(
                        Product.name.ilike(like),
                        ProductVariant.sku.ilike(like),
                        Product.description.ilike(like),
                        Product.name.ilike(fuzzy),
                    )
                )
        if category_id:
            pq = pq.filter(ProductVariant.category_id == safe_int(category_id))
        if tag_id:
            pq = pq.join(Product.tags).filter(Tag.id == safe_int(tag_id))
        if min_price:
            pq = pq.filter(ProductVariant.base_price >= safe_float(min_price))
        if max_price:
            pq = pq.filter(ProductVariant.base_price <= safe_float(max_price))
        return pq

    def _build_news_query():
        nq = NewsItem.query
        if q:
            for term in q.split():
                like = f"%{term}%"
                fuzzy = "%" + "%".join(list(term)) + "%"
                nq = nq.filter(
                    or_(
                        NewsItem.title.ilike(like),
                        NewsItem.content.ilike(like),
                        NewsItem.summary.ilike(like),
                        NewsItem.title.ilike(fuzzy),
                    )
                )
        if date_from:
            nq = nq.filter(NewsItem.ingested_at >= parsed_date_from)
        if date_to:
            nq = nq.filter(NewsItem.ingested_at <= parsed_date_to)
        return nq

    def _build_question_query():
        qq = Question.query
        if q:
            for term in q.split():
                like = f"%{term}%"
                fuzzy = "%" + "%".join(list(term)) + "%"
                qq = qq.filter(
                    or_(Question.question_text.ilike(like), Question.question_text.ilike(fuzzy))
                )
        return qq

    if search_type != "all":
        if search_type == "products":
            pq = _build_product_query()
            if sort == "price":
                pq = pq.order_by(ProductVariant.base_price.asc())
            else:
                pq = pq.order_by(Product.created_at.desc())
            total = pq.count()
            for variant in pq.offset((page - 1) * per_page).limit(per_page).all():
                paginated.append({
                    "type": "product", "title": variant.product.name,
                    "snippet": highlight(variant.product.description or "", q),
                    "link": f"/products/{variant.product.id}",
                    "price": variant.base_price,
                    "date": variant.product.created_at or now,
                })
        elif search_type == "news":
            nq = _build_news_query().order_by(NewsItem.ingested_at.desc())
            total = nq.count()
            for item in nq.offset((page - 1) * per_page).limit(per_page).all():
                paginated.append({
                    "type": "news", "title": item.title,
                    "snippet": highlight(item.summary or item.content or "", q),
                    "link": f"/news/{item.id}",
                    "price": None,
                    "date": item.published_date or item.ingested_at or now,
                })
        elif search_type == "questions":
            qq = _build_question_query()
            total = qq.count()
            for question in qq.offset((page - 1) * per_page).limit(per_page).all():
                paginated.append({
                    "type": "question", "title": question.question_text[:80],
                    "snippet": highlight(question.question_text, q),
                    "link": f"/assessments/{question.assessment_id}",
                    "price": None, "date": now,
                })
    else:
        product_stmt = select(
            literal("product").label("type"),
            Product.name.label("title"),
            func.coalesce(Product.description, "").label("snippet_text"),
            func.printf("/products/%d", Product.id).label("link"),
            ProductVariant.base_price.label("price"),
            Product.created_at.label("date"),
        ).select_from(ProductVariant).join(Product).where(Product.is_published.is_(True))

        if q:
            for term in q.split():
                like = f"%{term}%"
                fuzzy = "%" + "%".join(list(term)) + "%"
                product_stmt = product_stmt.where(
                    or_(
                        Product.name.ilike(like),
                        ProductVariant.sku.ilike(like),
                        Product.description.ilike(like),
                        Product.name.ilike(fuzzy),
                    )
                )
        if category_id:
            product_stmt = product_stmt.where(ProductVariant.category_id == safe_int(category_id))
        if tag_id:
            product_stmt = product_stmt.join(Product.tags).where(Tag.id == safe_int(tag_id))
        if min_price:
            product_stmt = product_stmt.where(ProductVariant.base_price >= safe_float(min_price))
        if max_price:
            product_stmt = product_stmt.where(ProductVariant.base_price <= safe_float(max_price))

        news_stmt = select(
            literal("news").label("type"),
            NewsItem.title.label("title"),
            func.coalesce(NewsItem.summary, NewsItem.content, "").label("snippet_text"),
            func.printf("/news/%d", NewsItem.id).label("link"),
            literal(None).label("price"),
            func.coalesce(NewsItem.published_date, NewsItem.ingested_at).label("date"),
        )

        if q:
            for term in q.split():
                like = f"%{term}%"
                fuzzy = "%" + "%".join(list(term)) + "%"
                news_stmt = news_stmt.where(
                    or_(
                        NewsItem.title.ilike(like),
                        NewsItem.content.ilike(like),
                        NewsItem.summary.ilike(like),
                        NewsItem.title.ilike(fuzzy),
                    )
                )
        if parsed_date_from:
            news_stmt = news_stmt.where(NewsItem.ingested_at >= parsed_date_from)
        if parsed_date_to:
            news_stmt = news_stmt.where(NewsItem.ingested_at <= parsed_date_to)

        question_stmt = select(
            literal("question").label("type"),
            func.substr(Question.question_text, 1, 80).label("title"),
            Question.question_text.label("snippet_text"),
            func.printf("/assessments/%d", Question.assessment_id).label("link"),
            literal(None).label("price"),
            literal(now).label("date"),
        )

        if q:
            for term in q.split():
                like = f"%{term}%"
                fuzzy = "%" + "%".join(list(term)) + "%"
                question_stmt = question_stmt.where(
                    or_(Question.question_text.ilike(like), Question.question_text.ilike(fuzzy))
                )

        combined = product_stmt.union_all(news_stmt, question_stmt).subquery()

        total = db.session.query(func.count()).select_from(combined).scalar() or 0
        query_all = db.session.query(combined)
        if sort == "price":
            query_all = query_all.order_by(combined.c.price.is_(None), combined.c.price.asc())
        else:
            query_all = query_all.order_by(combined.c.date.desc())

        rows = query_all.offset((page - 1) * per_page).limit(per_page).all()
        paginated = [
            {
                "type": row.type,
                "title": row.title,
                "snippet": highlight(row.snippet_text or "", q),
                "link": row.link,
                "price": row.price,
                "date": row.date or now,
            }
            for row in rows
        ]

    total_pages = max((total + per_page - 1) // per_page, 1)

    saved_searches = SavedSearch.query.filter_by(user_id=get_jwt_identity()).all()
    saved_payload = []
    for saved in saved_searches:
        try:
            params = json.loads(saved.query_params)
        except Exception:
            params = {}
        saved_payload.append({"saved": saved, "params": params})

    context = {
        "results": paginated,
        "q": q,
        "type": search_type,
        "category_id": category_id,
        "tag_id": tag_id,
        "min_price": min_price,
        "max_price": max_price,
        "date_from": date_from,
        "date_to": date_to,
        "sort": sort,
        "page": page,
        "total": total,
        "total_pages": total_pages,
        "per_page": per_page,
        "saved_searches": saved_payload,
        "categories": Category.query.order_by(Category.name.asc()).all(),
        "tags": Tag.query.order_by(Tag.name.asc()).all(),
    }

    is_htmx = request.headers.get("HX-Request") == "true"
    db.session.add(
        AuditLog(
            user_id=get_jwt_identity(),
            action="search",
            detail=f"Query: {q} (htmx={is_htmx})",
            ip_address=AuditLog.hash_ip(request.remote_addr),
        )
    )
    db.session.commit()

    one_minute_ago = utcnow() - timedelta(minutes=1)
    recent_searches = AuditLog.query.filter(
        AuditLog.user_id == get_jwt_identity(),
        AuditLog.action == "search",
        AuditLog.created_at >= one_minute_ago,
    ).count()
    if recent_searches >= 20:
        db.session.add(
            AnomalyAlert(
                user_id=get_jwt_identity(),
                rule_triggered="rapid_search_burst",
                detail="20+ searches within 1 minute",
                severity="medium",
            )
        )
        db.session.add(
            AuditLog(
                user_id=get_jwt_identity(),
                action="anomaly_detected",
                detail="Rule: rapid_search_burst — 20+ searches within 1 minute",
            )
        )
        db.session.commit()

    if request.headers.get("HX-Request") == "true":
        return render_template("search/partials/results.html", **context)

    return render_template("search/index.html", **context)


@search_bp.route("/saved", methods=["POST"])
@jwt_required()
@role_required("admin", "content_editor", "inventory_manager", "trainer", "staff")
@hmac_required
def save_search():
    name = request.form.get("name", "").strip()
    params = {
        "q": request.form.get("q", ""),
        "type": request.form.get("type", "all"),
        "category_id": request.form.get("category_id"),
        "tag_id": request.form.get("tag_id"),
        "min_price": request.form.get("min_price"),
        "max_price": request.form.get("max_price"),
        "date_from": request.form.get("date_from"),
        "date_to": request.form.get("date_to"),
        "sort": request.form.get("sort", "recency"),
    }
    saved = SavedSearch(
        user_id=get_jwt_identity(),
        name=name,
        query_params=json.dumps(params),
    )
    db.session.add(saved)
    db.session.commit()
    return render_template(
        "search/partials/saved_list.html",
        saved_searches=[{"saved": saved, "params": params}],
    )


@search_bp.route("/saved", methods=["GET"])
@jwt_required()
@role_required("admin", "content_editor", "inventory_manager", "trainer", "staff")
def saved_searches():
    saved = SavedSearch.query.filter_by(user_id=get_jwt_identity()).all()
    payload = []
    for item in saved:
        try:
            params = json.loads(item.query_params)
        except Exception:
            params = {}
        payload.append({"saved": item, "params": params})
    return render_template("search/partials/saved_list.html", saved_searches=payload)


@search_bp.route("/saved/<int:saved_id>", methods=["DELETE"])
@jwt_required()
@role_required("admin", "content_editor", "inventory_manager", "trainer", "staff")
@hmac_required
def delete_saved(saved_id):
    saved = SavedSearch.query.get_or_404(saved_id)
    if saved.user_id != get_jwt_identity():
        return "", 403
    db.session.delete(saved)
    db.session.commit()
    return "", 204


@search_bp.route("/saved/<int:saved_id>/pin", methods=["POST"])
@jwt_required()
@role_required("admin", "content_editor", "inventory_manager", "trainer", "staff")
@hmac_required
def toggle_pin(saved_id):
    saved = SavedSearch.query.get_or_404(saved_id)
    if saved.user_id != get_jwt_identity():
        return "", 403
    saved.is_pinned = not saved.is_pinned
    db.session.commit()
    try:
        params = json.loads(saved.query_params)
    except Exception:
        params = {}
    return render_template("search/partials/saved_button.html", saved=saved, params=params)
