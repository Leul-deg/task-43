import os
import shutil
from datetime import datetime

import bleach
from flask import Blueprint, abort, current_app, redirect, render_template, request, url_for
from flask_jwt_extended import get_jwt_identity, jwt_required

from ..decorators import hmac_required, role_required
from ..extensions import db
from ..models import IngestionLog, NewsItem, NewsSource, QuarantinedFile
from ..utils import safe_int

news_bp = Blueprint("news", __name__)

ALLOWED_TAGS = ["p", "br", "strong", "em", "ul", "ol", "li", "h1", "h2", "h3", "h4", "a"]


@news_bp.route("/", methods=["GET"])
@jwt_required()
@role_required("admin", "content_editor", "inventory_manager", "trainer", "staff")
def index():
    source_id = request.args.get("source_id")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    page = safe_int(request.args.get("page"), 1)

    query = NewsItem.query
    if source_id:
        query = query.filter(NewsItem.source_id == safe_int(source_id))
    if date_from:
        query = query.filter(
            NewsItem.ingested_at >= datetime.strptime(date_from, "%Y-%m-%d")
        )
    if date_to:
        query = query.filter(
            NewsItem.ingested_at <= datetime.strptime(date_to, "%Y-%m-%d")
        )

    pagination = query.order_by(NewsItem.ingested_at.desc()).paginate(
        page=page, per_page=25, error_out=False
    )
    sources = NewsSource.query.order_by(NewsSource.name.asc()).all()
    return render_template(
        "news/list.html",
        items=pagination.items,
        pagination=pagination,
        sources=sources,
        filters={"source_id": source_id, "date_from": date_from, "date_to": date_to},
    )


@news_bp.route("/<int:item_id>", methods=["GET"])
@jwt_required()
@role_required("admin", "content_editor", "inventory_manager", "trainer", "staff")
def detail(item_id):
    item = NewsItem.query.get_or_404(item_id)
    item.content = bleach.clean(item.content or "", tags=ALLOWED_TAGS)
    return render_template("news/detail.html", item=item)


@news_bp.route("/sources", methods=["GET"])
@jwt_required()
@role_required("admin")
def sources():
    sources = NewsSource.query.order_by(NewsSource.name.asc()).all()
    return render_template("news/sources.html", sources=sources)


@news_bp.route("/sources", methods=["POST"])
@jwt_required()
@role_required("admin")
@hmac_required
def create_source():
    source = NewsSource(
        name=request.form.get("name", "").strip(),
        source_type=request.form.get("source_type", "").strip(),
        filename_prefix=request.form.get("filename_prefix", "").strip() or None,
        parsing_rules=request.form.get("parsing_rules"),
        is_allowed=request.form.get("is_allowed") == "on",
        created_by=get_jwt_identity(),
    )
    db.session.add(source)
    db.session.commit()
    return redirect(url_for("news.sources"))


@news_bp.route("/sources/<int:source_id>", methods=["PUT"])
@jwt_required()
@role_required("admin")
@hmac_required
def update_source(source_id):
    source = NewsSource.query.get_or_404(source_id)
    source.name = request.form.get("name", source.name)
    source.source_type = request.form.get("source_type", source.source_type)
    source.filename_prefix = request.form.get("filename_prefix", "").strip() or None
    source.parsing_rules = request.form.get("parsing_rules", source.parsing_rules)
    source.is_allowed = request.form.get("is_allowed") == "on"
    db.session.commit()
    return render_template("news/partials/source_row.html", source=source)


@news_bp.route("/sources/<int:source_id>", methods=["DELETE"])
@jwt_required()
@role_required("admin")
@hmac_required
def delete_source(source_id):
    source = NewsSource.query.get_or_404(source_id)
    db.session.delete(source)
    db.session.commit()
    return "", 204


@news_bp.route("/<int:item_id>", methods=["PUT"])
@jwt_required()
@role_required("content_editor")
@hmac_required
def update_item(item_id):
    item = NewsItem.query.get_or_404(item_id)
    item.title = request.form.get("title", item.title)
    item.summary = bleach.clean(request.form.get("summary", item.summary or ""), tags=ALLOWED_TAGS)
    item.content = bleach.clean(request.form.get("content", item.content or ""), tags=ALLOWED_TAGS)
    db.session.commit()
    return render_template("news/partials/detail_card.html", item=item)


@news_bp.route("/logs", methods=["GET"])
@jwt_required()
@role_required("admin")
def logs():
    page = int(request.args.get("page", 1))
    pagination = IngestionLog.query.order_by(IngestionLog.started_at.desc()).paginate(
        page=page, per_page=25, error_out=False
    )
    return render_template("news/logs.html", logs=pagination.items, pagination=pagination)


@news_bp.route("/quarantine", methods=["GET"])
@jwt_required()
@role_required("admin")
def quarantine():
    files = QuarantinedFile.query.order_by(QuarantinedFile.quarantined_at.desc()).all()
    return render_template("news/quarantine.html", files=files)


@news_bp.route("/quarantine/<int:file_id>/release", methods=["POST"])
@jwt_required()
@role_required("admin")
@hmac_required
def release_quarantine(file_id):
    file = QuarantinedFile.query.get_or_404(file_id)
    quarantine_folder = current_app.config.get("QUARANTINE_FOLDER", "quarantine")
    watch_folder = current_app.config.get("WATCH_FOLDER", "watch_folder")
    src = os.path.join(quarantine_folder, file.filename)
    if os.path.exists(src):
        os.makedirs(watch_folder, exist_ok=True)
        shutil.move(src, os.path.join(watch_folder, file.filename))
    db.session.delete(file)
    db.session.commit()
    return redirect(url_for("news.quarantine"))


@news_bp.route("/quarantine/<int:file_id>", methods=["DELETE"])
@jwt_required()
@role_required("admin")
@hmac_required
def delete_quarantine(file_id):
    file = QuarantinedFile.query.get_or_404(file_id)
    db.session.delete(file)
    db.session.commit()
    return "", 204
