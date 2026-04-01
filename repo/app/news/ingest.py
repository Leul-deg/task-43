import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timedelta

import bleach
import feedparser
from flask import current_app

from ..extensions import db
from ..models import IngestionLog, NewsItem, NewsSource, QuarantinedFile, utcnow

logger = logging.getLogger(__name__)


ALLOWED_TAGS = ["p", "br", "strong", "em", "ul", "ol", "li", "h1", "h2", "h3", "h4", "a"]


def _hash_file(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _should_backoff(filename):
    last = (
        IngestionLog.query.filter_by(filename=filename, status="failed")
        .order_by(IngestionLog.completed_at.desc())
        .first()
    )
    if not last or not last.completed_at:
        return False, 0
    backoff_map = {0: timedelta(minutes=1), 1: timedelta(minutes=1), 2: timedelta(minutes=5), 3: timedelta(minutes=15)}
    retry_count = min(last.retries, 3)
    backoff = backoff_map.get(retry_count, timedelta(minutes=15))
    if utcnow() - last.completed_at < backoff:
        return True, last.retries
    return False, last.retries


def _record_log(filename, status, message=None, source_id=None, retries=0):
    log = IngestionLog(
        source_id=source_id,
        filename=filename,
        status=status,
        message=message,
        retries=retries,
        started_at=utcnow(),
        completed_at=utcnow(),
    )
    db.session.add(log)
    db.session.commit()


def _quarantine(file_path, filename, reason, file_hash, source_id=None, retries=0):
    quarantine_folder = current_app.config.get("QUARANTINE_FOLDER", "quarantine")
    os.makedirs(quarantine_folder, exist_ok=True)
    destination = os.path.join(quarantine_folder, filename)
    shutil.move(file_path, destination)
    db.session.add(
        QuarantinedFile(filename=filename, reason=reason, file_hash=file_hash)
    )
    db.session.commit()
    _record_log(filename, "quarantined", reason, source_id=source_id, retries=retries)


def _parse_feed(file_path):
    feed = feedparser.parse(file_path)
    items = []
    for entry in feed.entries:
        published = None
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6])
        items.append(
            {
                "title": entry.get("title"),
                "summary": entry.get("summary"),
                "content": (entry.get("content") or [{}])[0].get("value"),
                "author": entry.get("author"),
                "published": published,
            }
        )
    return items


def _parse_json(file_path, custom_rules=None):
    with open(file_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    items = []
    if custom_rules is None:
        custom_rules = {}
    items_key = custom_rules.get("items_key", "items")
    for entry in data.get(items_key, []):
        published = None
        if entry.get("published"):
            try:
                published = datetime.fromisoformat(entry.get("published"))
            except Exception:
                published = None
        items.append(
            {
                "title": entry.get("title"),
                "summary": entry.get("summary"),
                "content": entry.get("content"),
                "author": entry.get("author"),
                "published": published,
            }
        )
    return items


def _parse_html(file_path, custom_rules=None):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
        content = handle.read()
    title = None
    if "<title" in content.lower():
        start = content.lower().find("<title")
        end = content.lower().find("</title>")
        if start != -1 and end != -1:
            title = content[start:end].split(">")[-1].strip()
    body = ""
    for tag in ["<article", "<main"]:
        idx = content.lower().find(tag)
        if idx != -1:
            end_tag = "</article>" if tag == "<article" else "</main>"
            end_idx = content.lower().find(end_tag)
            if end_idx != -1:
                body = content[idx:end_idx]
                break
    if not body:
        body = content
    return [
        {
            "title": title,
            "summary": None,
            "content": body,
            "author": None,
            "published": None,
        }
    ]


def _resolve_source(filename, source_type):
    """Match file to the most specific allowed NewsSource.

    Priority: sources with a matching filename_prefix are preferred over
    generic (prefix-less) sources of the same type.  Among prefix matches
    the longest prefix wins, giving admins fine-grained per-source control.
    """
    candidates = (
        NewsSource.query
        .filter_by(source_type=source_type, is_allowed=True)
        .all()
    )
    if not candidates:
        return None
    name_lower = filename.rsplit(".", 1)[0].lower()
    best, best_len = None, -1
    for src in candidates:
        if src.filename_prefix:
            prefix = src.filename_prefix.lower()
            if name_lower.startswith(prefix) and len(prefix) > best_len:
                best, best_len = src, len(prefix)
    if best:
        return best
    # Fall back to first source with no prefix (generic type-level source)
    for src in candidates:
        if not src.filename_prefix:
            return src
    return candidates[0]


def ingest_news():
    watch_folder = current_app.config.get("WATCH_FOLDER", "watch_folder")
    processed_folder = os.path.join(watch_folder, "processed")
    os.makedirs(processed_folder, exist_ok=True)
    logger.info("Starting news ingestion")

    for filename in os.listdir(watch_folder):
        file_path = os.path.join(watch_folder, filename)
        if not os.path.isfile(file_path):
            continue
        if not filename.endswith((".rss", ".xml", ".atom", ".json", ".html")):
            continue

        should_wait, retries = _should_backoff(filename)
        if should_wait:
            continue

        file_hash = _hash_file(file_path)
        if NewsItem.query.filter_by(file_hash=file_hash).first():
            shutil.move(file_path, os.path.join(processed_folder, filename))
            continue
        if QuarantinedFile.query.filter_by(file_hash=file_hash).first():
            continue

        source_type = filename.split(".")[-1].lower()
        source = _resolve_source(filename, source_type)
        if not source:
            _record_log(filename, "failed", "No matching source", retries=retries)
            continue
        custom_rules = {}
        if source.parsing_rules:
            try:
                custom_rules = json.loads(source.parsing_rules)
            except Exception:
                pass

        try:
            if source_type in ["rss", "atom", "xml"]:
                items = _parse_feed(file_path)
            elif source_type == "json":
                items = _parse_json(file_path, custom_rules)
            else:
                items = _parse_html(file_path, custom_rules)

            if not items:
                _quarantine(file_path, filename, "No items found", file_hash, source_id=source.id)
                continue

            created_any = False
            quarantined = False
            for entry in items:
                if not entry.get("title"):
                    _quarantine(file_path, filename, "Missing title", file_hash, source_id=source.id)
                    quarantined = True
                    break
                content = entry.get("content") or entry.get("summary") or ""
                sanitized = bleach.clean(content, tags=ALLOWED_TAGS)
                item = NewsItem(
                    source_id=source.id,
                    title=entry.get("title"),
                    summary=bleach.clean(entry.get("summary") or "", tags=ALLOWED_TAGS),
                    content=sanitized,
                    author=entry.get("author"),
                    published_date=entry.get("published"),
                    file_hash=file_hash,
                )
                db.session.add(item)
                db.session.commit()
                created_any = True

            if quarantined:
                continue
            if created_any:
                _record_log(filename, "success", source_id=source.id)
                logger.info("Ingested file=%s", filename)

            shutil.move(file_path, os.path.join(processed_folder, filename))
        except Exception as exc:
            logger.error("Ingestion failed file=%s err=%s", filename, exc)
            retries += 1
            if retries > 3:
                _quarantine(file_path, filename, str(exc), file_hash, source_id=source.id, retries=retries)
            else:
                _record_log(filename, "failed", str(exc), source_id=source.id, retries=retries)
