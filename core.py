"""Validated content library shared by local ingestion and the cloud worker."""
import copy
import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("XHS_OBSERVER_HOME", SOURCE / "var")).resolve()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def config():
    path = SOURCE / "config.json"
    return load_json(path if path.exists() else SOURCE / "config.example.json")


def empty_archive():
    return {"schema_version": 2, "posts": {}, "snapshots": {}, "batches": {}, "media": {}, "latest_batch_id": None}


def excluded(post, settings):
    return post.get("author_id") in settings["excluded_author_ids"] or post.get("author", "").strip().casefold() in {s.casefold() for s in settings["excluded_author_names"]}


def validate(batch, settings):
    if batch.get("topic", "credit-cards") not in settings["topics"]:
        raise ValueError("Unknown collection topic.")
    posts = batch.get("posts", [])
    if len(posts) != settings["batch_size"]:
        raise ValueError(f"Expected {settings['batch_size']} complete posts; the previous release is preserved.")
    ids = [p.get("id") for p in posts]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate post IDs in one batch.")
    start = date.fromisoformat(batch.get("period_start", batch["date"]))
    end = date.fromisoformat(batch.get("period_end", batch["date"]))
    if start > end:
        raise ValueError("Invalid publication window.")
    for post in posts:
        if not isinstance(post.get("id"), str) or not re.fullmatch(r"[a-f0-9]{24}", post["id"]):
            raise ValueError("Invalid post ID.")
        if excluded(post, settings):
            raise ValueError("Excluded publisher in batch; select a replacement before publishing.")
        for field in ("title", "author", "summary", "body"):
            if not isinstance(post.get(field), str) or not post[field].strip():
                raise ValueError(f"Missing {field}.")
        if not post.get("url", "").startswith("https://www.xiaohongshu.com/"):
            raise ValueError("Missing original post URL.")
        timestamp = datetime.fromisoformat(post["capturedAt"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Capture timestamp must include a timezone.")
        if batch.get("mode") == "weekly-backfill":
            published = date.fromisoformat(post["published_date"])
            if not start <= published <= end or post.get("publication_basis") != "detail-page":
                raise ValueError("Weekly demo requires a verified detail-page publication date.")
        for field in ("likes", "saves", "comments"):
            value = post.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
                raise ValueError(f"Missing or invalid {field}; do not substitute zero.")
        if not isinstance(post.get("keywords"), list) or not post["keywords"]:
            raise ValueError("Missing source keyword.")
    return posts


def read_assets(batch, directory):
    """Resolve every local media file before any library mutation."""
    directory = Path(directory).resolve()
    assets = {}
    for post in batch["posts"]:
        refs = []
        for i, name in enumerate(post.get("files", [])):
            path = (directory / name).resolve()
            if not path.is_relative_to(directory) or not path.is_file():
                raise ValueError("Missing or unsafe media file path.")
            raw = path.read_bytes()
            key = hashlib.sha256(raw).hexdigest()
            role = "cover" if "cover" in path.name else "image"
            refs.append({"id": key, "role": role, "order": i})
            assets[key] = {"bytes": raw, "path": "assets/" + key + ".webp", "content_type": "image/webp"}
        post["media_refs"] = refs
    return assets


def merge(archive, batch, assets, settings=None):
    settings = settings or config()
    posts = validate(batch, settings)
    incoming_topic = batch.get("topic", "credit-cards")
    incoming_end = batch.get("period_end", batch["date"])
    for existing in archive["batches"].values():
        if existing.get("topic", "credit-cards") != incoming_topic and existing.get("period_end", existing["date"]) == incoming_end:
            other_ids = {archive["snapshots"][key]["post_id"] for key in existing["snapshot_ids"] if key in archive["snapshots"]}
            if other_ids.intersection(post["id"] for post in posts):
                raise ValueError("The two topics must not repeat a post in the same period.")
    for post in posts:
        for reference in post.get("media_refs", []):
            if reference.get("id") not in assets and reference.get("id") not in archive["media"]:
                raise ValueError("Post references media not present in the batch or archive.")
    result = copy.deepcopy(archive)
    result["schema_version"] = 2
    # Apply the exclusion rule to existing state, not only future imports.
    removed = {key for key, post in result["posts"].items() if excluded(post, settings)}
    for key in removed:
        result["posts"].pop(key, None)
    for key in list(result["snapshots"]):
        if result["snapshots"][key]["post_id"] in removed:
            del result["snapshots"][key]
    for old in result["batches"].values():
        old["snapshot_ids"] = [key for key in old["snapshot_ids"] if key in result["snapshots"]]
        if len(old["snapshot_ids"]) != settings["batch_size"]:
            old["status"] = "incomplete"
    batch_id = batch.get("period_end", batch["date"]) + "-" + hashlib.sha256(canonical(batch)).hexdigest()[:16]
    if batch_id in result["batches"]:
        return result
    snapshot_ids = []
    for p in posts:
        content = {"id": p["id"], "title": p["title"], "author": p["author"], "author_id": p.get("author_id", ""), "body": p["body"], "summary": p["summary"], "image_summary": p.get("imageSummary", ""), "source_url": p["url"], "published_label": p.get("date", ""), "published_date": p.get("published_date"), "publication_basis": p.get("publication_basis"), "keywords": p["keywords"], "category": p.get("category", "图文"), "type": p.get("type", "image"), "is_brand": False, "media": p.get("media_refs", [])}
        snapshot_id = p["id"] + "@" + p["capturedAt"]
        result["snapshots"][snapshot_id] = {"id": snapshot_id, "post_id": p["id"], "captured_at": p["capturedAt"], **{k: int(p[k]) for k in ("likes", "saves", "comments")}, "content": content}
        if p["capturedAt"] >= result["posts"].get(p["id"], {}).get("last_captured_at", ""):
            result["posts"][p["id"]] = {**content, "last_captured_at": p["capturedAt"]}
        snapshot_ids.append(snapshot_id)
    for key, asset in assets.items():
        result["media"][key] = {"id": key, "path": asset["path"], "content_type": asset["content_type"]}
    result["batches"][batch_id] = {"id": batch_id, "topic": batch.get("topic", "credit-cards"), "date": batch["date"], "period_start": batch.get("period_start", batch["date"]), "period_end": batch.get("period_end", batch["date"]), "mode": batch.get("mode", "daily"), "completed_at": max(p["capturedAt"] for p in posts), "status": "complete", "candidate_count": batch.get("candidateCount"), "selection": batch.get("selection", ""), "snapshot_ids": snapshot_ids}
    complete = [b for b in result["batches"].values() if b["status"] == "complete"]
    result["latest_batch_id"] = max(complete, key=lambda b: (b.get("period_end", b["date"]), b["completed_at"], b["id"]))["id"] if complete else None
    used = {m["id"] for s in result["snapshots"].values() for m in s["content"]["media"]}
    result["media"] = {key: asset for key, asset in result["media"].items() if key in used}
    return result


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical(value))
    temporary.replace(path)


def ingest_local(source):
    source = Path(source).resolve()
    batch = load_json(source)
    validate(batch, config())
    assets = read_assets(batch, source.parent)
    archive_path = HOME / "data/archive.json"
    current = load_json(archive_path) if archive_path.exists() else empty_archive()
    result = merge(current, batch, assets)
    for asset in assets.values():
        path = HOME / asset["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(asset["bytes"])
    atomic_json(archive_path, result)
    return result
