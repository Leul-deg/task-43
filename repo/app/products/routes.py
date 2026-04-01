import csv
import io
import os
from datetime import datetime

import bleach
from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from ..decorators import hmac_required, role_required
from ..extensions import db
from ..models import (
    AuditLog,
    Batch,
    Category,
    Product,
    ProductVariant,
    Tag,
    TieredPrice,
    utcnow,
)
from ..pricing.services import calculate_effective_price
from ..utils import safe_int, safe_float

products_bp = Blueprint("products", __name__)


ALLOWED_TAGS = ["p", "br", "strong", "em", "ul", "ol", "li", "h1", "h2", "h3", "h4", "a"]
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024

IMAGE_MAGIC_BYTES = {
    b"\xff\xd8\xff": {"jpg", "jpeg"},
    b"\x89PNG\r\n\x1a\n": {"png"},
    b"GIF87a": {"gif"},
    b"GIF89a": {"gif"},
    b"RIFF": {"webp"},
}


def _validate_image(image):
    """Returns error message string or None if valid."""
    if "." not in image.filename:
        return "Invalid image file."
    ext = image.filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return f"Invalid image type. Allowed: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}."
    image.seek(0, 2)
    size = image.tell()
    image.seek(0)
    if size > MAX_IMAGE_BYTES:
        return "Image too large. Maximum 5 MB."
    header = image.read(12)
    image.seek(0)
    if len(header) < 4:
        return "Invalid image file."
    matched = False
    for magic, exts in IMAGE_MAGIC_BYTES.items():
        if header[:len(magic)] == magic and ext in exts:
            matched = True
            break
    if not matched:
        return "File content does not match a valid image format."
    return None


def slugify(value):
    value = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in value:
        value = value.replace("--", "-")
    return value or "product"


def unique_slug(base):
    slug = base
    counter = 1
    while Product.query.filter_by(slug=slug).first():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def get_or_create_tag(name):
    tag = Tag.query.filter_by(name=name).first()
    if tag:
        return tag
    tag = Tag(name=name)
    db.session.add(tag)
    return tag


@products_bp.route("/", methods=["GET"])
@jwt_required()
@role_required("admin", "content_editor", "inventory_manager", "trainer", "staff")
def index():
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category_id")
    tag_ids = request.args.getlist("tag_id")
    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")
    sort = request.args.get("sort", "date")
    page = safe_int(request.args.get("page", 1))
    per_page = safe_int(request.args.get("per_page", 25))

    query = ProductVariant.query.join(Product)

    if q:
        like = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(like), ProductVariant.sku.ilike(like)))

    if category_id:
        query = query.filter(ProductVariant.category_id == safe_int(category_id))

    if tag_ids:
        query = query.join(Product.tags).filter(Tag.id.in_([safe_int(t) for t in tag_ids])).distinct()

    if min_price:
        query = query.filter(ProductVariant.base_price >= safe_float(min_price))
    if max_price:
        query = query.filter(ProductVariant.base_price <= safe_float(max_price))

    if sort == "name":
        query = query.order_by(Product.name.asc())
    elif sort == "price":
        query = query.order_by(ProductVariant.base_price.asc())
    else:
        query = query.order_by(Product.created_at.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    variants = pagination.items
    variant_ids = [variant.id for variant in variants]

    stock_totals = {
        row[0]: row[1]
        for row in db.session.query(Batch.variant_id, db.func.coalesce(db.func.sum(Batch.quantity), 0))
        .filter(Batch.variant_id.in_(variant_ids) if variant_ids else False)
        .group_by(Batch.variant_id)
        .all()
    }

    products = []
    for variant in variants:
        products.append(
            {
                "variant": variant,
                "product": variant.product,
                "category": Category.query.get(variant.category_id) if variant.category_id else None,
                "tags": variant.product.tags,
                "stock_total": stock_totals.get(variant.id, 0),
            }
        )

    categories = Category.query.order_by(Category.name.asc()).all()
    tags = Tag.query.order_by(Tag.name.asc()).all()
    filters = {
        "q": q,
        "category_id": category_id,
        "tag_id": tag_ids,
        "min_price": min_price,
        "max_price": max_price,
        "sort": sort,
        "per_page": per_page,
    }

    if request.headers.get("HX-Request") == "true":
        return render_template(
            "products/partials/product_rows.html",
            products=products,
            pagination=pagination,
            filters=filters,
        )

    return render_template(
        "products/list.html",
        products=products,
        pagination=pagination,
        filters=filters,
        categories=categories,
        tags=tags,
    )


@products_bp.route("/new", methods=["GET"])
@jwt_required()
@role_required("admin", "content_editor")
def new_product():
    categories = Category.query.order_by(Category.name.asc()).all()
    return render_template("products/form.html", categories=categories, product=None)


@products_bp.route("/", methods=["POST"])
@jwt_required()
@role_required("admin", "content_editor")
@hmac_required
def create_product():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Product name is required.", "danger")
        return redirect(url_for("products.new_product"))
    slug = request.form.get("slug", "").strip() or slugify(name)
    slug = unique_slug(slug)
    description = bleach.clean(request.form.get("description", ""), tags=ALLOWED_TAGS)
    purchase_limit = request.form.get("purchase_limit")
    is_published = request.form.get("is_published") == "on"

    product = Product(
        name=name,
        slug=slug,
        description=description,
        purchase_limit=safe_int(purchase_limit) if purchase_limit else None,
        is_published=is_published,
    )

    image = request.files.get("primary_image")
    if image and image.filename:
        img_error = _validate_image(image)
        if img_error:
            flash(img_error, "danger")
            return redirect(url_for("products.new_product"))
        filename = secure_filename(image.filename)
        if filename:
            upload_dir = current_app.config.get("UPLOAD_FOLDER", "app/static/uploads")
            os.makedirs(upload_dir, exist_ok=True)
            stamp = utcnow().strftime("%Y%m%d%H%M%S")
            stored_name = f"{stamp}_{filename}"
            image.save(os.path.join(upload_dir, stored_name))
            product.primary_image = f"uploads/{stored_name}"

    tag_names = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]
    product.tags = [get_or_create_tag(name) for name in tag_names]

    db.session.add(product)
    db.session.flush()

    sku = request.form.get("sku", "").strip()
    base_price = safe_float(request.form.get("base_price", 0))
    category_id = request.form.get("category_id")
    variant = ProductVariant(
        product_id=product.id,
        sku=sku,
        base_price=base_price,
        category_id=safe_int(category_id) if category_id else None,
    )
    db.session.add(variant)
    db.session.flush()

    tiered_mins = request.form.getlist("tiered_min[]")
    tiered_prices = request.form.getlist("tiered_price[]")
    for min_qty, price in zip(tiered_mins, tiered_prices):
        if min_qty and price:
            db.session.add(
                TieredPrice(
                    variant_id=variant.id,
                    min_quantity=safe_int(min_qty),
                    unit_price=safe_float(price),
                )
            )

    db.session.add(
        AuditLog(
            user_id=get_jwt_identity(),
            action="product_created",
            detail=f"Product: {name}",
            ip_address=AuditLog.hash_ip(request.remote_addr),
        )
    )
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("A product with this SKU already exists.", "danger")
        return redirect(url_for("products.index"))
    return redirect(url_for("products.detail", product_id=product.id))


@products_bp.route("/<int:product_id>", methods=["GET"])
@jwt_required()
@role_required("admin", "content_editor", "inventory_manager", "trainer", "staff")
def detail(product_id):
    product = Product.query.get_or_404(product_id)
    variants = ProductVariant.query.filter_by(product_id=product.id).all()
    tiered_prices = {
        variant.id: TieredPrice.query.filter_by(variant_id=variant.id)
        .order_by(TieredPrice.min_quantity.asc())
        .all()
        for variant in variants
    }
    effective_prices = {
        variant.id: calculate_effective_price(variant.id, 1) for variant in variants
    }
    return render_template(
        "products/detail.html",
        product=product,
        variants=variants,
        tiered_prices=tiered_prices,
        effective_prices=effective_prices,
    )


@products_bp.route("/<int:product_id>/edit", methods=["GET"])
@jwt_required()
@role_required("admin", "content_editor")
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    categories = Category.query.order_by(Category.name.asc()).all()
    return render_template("products/form.html", product=product, categories=categories)


@products_bp.route("/<int:product_id>", methods=["PUT"])
@jwt_required()
@role_required("admin", "content_editor")
@hmac_required
def update_product(product_id):
    product = Product.query.get_or_404(product_id)
    product.name = request.form.get("name", product.name)
    product.slug = request.form.get("slug", product.slug)
    product.description = bleach.clean(
        request.form.get("description", product.description), tags=ALLOWED_TAGS
    )
    purchase_limit = request.form.get("purchase_limit")
    product.purchase_limit = safe_int(purchase_limit) if purchase_limit else None
    product.is_published = request.form.get("is_published") == "on"

    image = request.files.get("primary_image")
    if image and image.filename:
        img_error = _validate_image(image)
        if img_error:
            flash(img_error, "danger")
            return redirect(url_for("products.edit_product", product_id=product_id))
        filename = secure_filename(image.filename)
        if filename:
            upload_dir = current_app.config.get("UPLOAD_FOLDER", "app/static/uploads")
            os.makedirs(upload_dir, exist_ok=True)
            stamp = utcnow().strftime("%Y%m%d%H%M%S")
            stored_name = f"{stamp}_{filename}"
            image.save(os.path.join(upload_dir, stored_name))
            product.primary_image = f"uploads/{stored_name}"

    tag_names = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]
    product.tags = [get_or_create_tag(name) for name in tag_names]

    db.session.add(
        AuditLog(
            user_id=get_jwt_identity(),
            action="product_updated",
            detail=f"Product ID: {product_id}",
            ip_address=AuditLog.hash_ip(request.remote_addr),
        )
    )
    db.session.commit()
    return render_template("products/partials/product_detail.html", product=product)


@products_bp.route("/<int:product_id>", methods=["DELETE"])
@jwt_required()
@role_required("admin", "content_editor")
@hmac_required
def delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_published = False
    db.session.add(
        AuditLog(
            user_id=get_jwt_identity(),
            action="product_unpublished",
            detail=f"Product ID: {product_id}",
            ip_address=AuditLog.hash_ip(request.remote_addr),
        )
    )
    db.session.commit()
    return "", 204


@products_bp.route("/<int:product_id>/toggle-publish", methods=["POST"])
@jwt_required()
@role_required("admin", "content_editor")
@hmac_required
def toggle_publish(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_published = not product.is_published
    db.session.commit()
    return render_template("products/partials/publish_button.html", product=product)


@products_bp.route("/<int:product_id>/variants", methods=["POST"])
@jwt_required()
@role_required("admin", "content_editor")
@hmac_required
def add_variant(product_id):
    Product.query.get_or_404(product_id)
    sku = request.form.get("sku", "").strip()
    base_price = safe_float(request.form.get("base_price", 0))
    category_id = request.form.get("category_id")
    variant = ProductVariant(
        product_id=product_id,
        sku=sku,
        base_price=base_price,
        category_id=safe_int(category_id) if category_id else None,
    )
    db.session.add(variant)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return "SKU already exists.", 409
    return render_template("products/partials/variant_row.html", variant=variant)


@products_bp.route("/variants/<int:variant_id>", methods=["PUT"])
@jwt_required()
@role_required("admin", "content_editor")
@hmac_required
def update_variant(variant_id):
    variant = ProductVariant.query.get_or_404(variant_id)
    variant.sku = request.form.get("sku", variant.sku)
    variant.base_price = safe_float(request.form.get("base_price", variant.base_price))
    category_id = request.form.get("category_id")
    variant.category_id = safe_int(category_id) if category_id else variant.category_id
    db.session.commit()
    return render_template("products/partials/variant_row.html", variant=variant)


@products_bp.route("/export", methods=["GET"])
@jwt_required()
@role_required("admin", "content_editor")
def export_products():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "name",
            "sku",
            "description",
            "category",
            "tags",
            "base_price",
            "stock_total",
            "purchase_limit",
        ]
    )

    variants = ProductVariant.query.join(Product).all()
    stock_totals = {
        row[0]: row[1]
        for row in db.session.query(Batch.variant_id, db.func.coalesce(db.func.sum(Batch.quantity), 0))
        .group_by(Batch.variant_id)
        .all()
    }
    for variant in variants:
        product = variant.product
        category = Category.query.get(variant.category_id) if variant.category_id else None
        tags = ", ".join(tag.name for tag in product.tags)
        writer.writerow(
            [
                product.name,
                variant.sku,
                product.description or "",
                category.name if category else "",
                tags,
                variant.base_price,
                stock_totals.get(variant.id, 0),
                product.purchase_limit or "",
            ]
        )

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=products.csv"},
    )


@products_bp.route("/import", methods=["POST"])
@jwt_required()
@role_required("admin", "content_editor")
@hmac_required
def import_products():
    file = request.files.get("file")
    if not file:
        flash("No file uploaded.", "danger")
        return redirect(url_for("products.index"))

    content = file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    imported = 0
    skipped = 0
    errors = 0

    for row in reader:
        try:
            sku = row.get("sku", "").strip()
            name = row.get("name", "").strip()
            if not sku or not name:
                skipped += 1
                continue

            variant = ProductVariant.query.filter_by(sku=sku).first()
            if variant:
                product = variant.product
            else:
                product = Product(name=name, slug=unique_slug(slugify(name)))
                db.session.add(product)
                db.session.flush()
                variant = ProductVariant(product_id=product.id, sku=sku, base_price=0)
                db.session.add(variant)

            product.name = name
            product.description = row.get("description") or product.description
            purchase_limit = row.get("purchase_limit")
            product.purchase_limit = safe_int(purchase_limit) if purchase_limit else product.purchase_limit

            category_name = (row.get("category") or "").strip()
            if category_name:
                category = Category.query.filter_by(name=category_name).first()
                if not category:
                    category = Category(name=category_name)
                    db.session.add(category)
                    db.session.flush()
                variant.category_id = category.id

            base_price = row.get("base_price")
            if base_price:
                variant.base_price = safe_float(base_price)

            tags = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()]
            product.tags = [get_or_create_tag(tag) for tag in tags]

            imported += 1
        except Exception:
            errors += 1

    db.session.commit()
    flash(f"Imported {imported}, skipped {skipped}, errors {errors}.", "info")
    return redirect(url_for("products.index"))
