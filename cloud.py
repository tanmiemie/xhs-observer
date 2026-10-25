"""Private GCS ingestion, optimistic release publication, and local synchronization.

Authentication uses Application Default Credentials. No keys are shipped with the app.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

from core import HOME, atomic_json, canonical, config, empty_archive, load_json, merge, read_assets, validate


def bucket():
    from google.cloud import storage
    settings = config()["google_cloud"]
    name = os.environ.get("XHS_GCS_BUCKET") or settings["bucket"]
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or settings["project_id"]
    if not name or not project:
        raise ValueError("Set google_cloud.project_id and bucket in config.json, or GOOGLE_CLOUD_PROJECT / XHS_GCS_BUCKET.")
    return storage.Client(project=project).bucket(name)


def put_immutable(target, name, data, content_type="application/json"):
    from google.api_core.exceptions import PreconditionFailed
    blob = target.blob(name)
    try:
        blob.upload_from_string(data, content_type=content_type, if_generation_match=0)
    except PreconditionFailed:
        if blob.download_as_bytes() != data:
            raise ValueError("Immutable object collision: " + name)
    return name


def upload(source, target=None):
    """Upload all media first and the ready manifest last."""
    source = Path(source).resolve()
    batch = load_json(source)
    validate(batch, config())
    assets = read_assets(batch, source.parent)
    target = target or bucket()
    for asset in assets.values():
        put_immutable(target, asset["path"], asset["bytes"], asset["content_type"])
    manifest = {"batch": batch, "assets": {key: {k: v for k, v in value.items() if k != "bytes"} for key, value in assets.items()}}
    raw = canonical(manifest)
    name = "incoming/" + hashlib.sha256(raw).hexdigest() + ".json"
    put_immutable(target, name, raw)
    return name


def read_release(target):
    from google.api_core.exceptions import NotFound
    pointer = target.blob("latest.json")
    try:
        pointer.reload()
        generation = int(pointer.generation)
        state = json.loads(pointer.download_as_bytes(if_generation_match=generation))
    except NotFound:
        return empty_archive(), 0
    if not state["archive_object"].startswith("releases/"):
        raise ValueError("Invalid cloud release pointer.")
    raw = target.blob(state["archive_object"]).download_as_bytes()
    if hashlib.sha256(raw).hexdigest() != state["sha256"]:
        raise ValueError("Cloud archive checksum mismatch.")
    return json.loads(raw), generation


def process(target=None, retries=4):
    """Cloud Run job entrypoint. Repeated and concurrent execution is safe."""
    from google.api_core.exceptions import PreconditionFailed
    target = target or bucket()
    # A manifest only exists after all images have been uploaded successfully.
    manifests = [json.loads(blob.download_as_bytes()) for blob in target.list_blobs(prefix="incoming/") if blob.name.endswith(".json")]
    for attempt in range(retries):
        try:
            archive, generation = read_release(target)
            updated = copy.deepcopy(archive)
            for manifest in manifests:
                for key, asset in manifest["assets"].items():
                    if asset["path"] != "assets/" + key + ".webp" or not target.blob(asset["path"]).exists():
                        raise ValueError("Manifest references missing or unsafe cloud media.")
                updated = merge(updated, manifest["batch"], manifest["assets"])
            raw = canonical(updated)
            digest = hashlib.sha256(raw).hexdigest()
            name = put_immutable(target, "releases/" + digest + "/archive.json", raw)
            target.blob("latest.json").upload_from_string(canonical({"schema": 1, "archive_object": name, "sha256": digest}), content_type="application/json", if_generation_match=generation)
            return {"posts": len(updated["posts"]), "batches": len(updated["batches"]), "release": digest}
        except PreconditionFailed:
            if attempt + 1 == retries:
                raise
    raise RuntimeError("Unable to publish a consistent release.")


def pull(target=None):
    """Download assets before replacing local state; failures preserve the cache."""
    target = target or bucket()
    archive, generation = read_release(target)
    if not generation:
        raise ValueError("No completed cloud release yet. Run the processing job first.")
    for key, media in archive["media"].items():
        if media["path"] != "assets/" + key + ".webp":
            raise ValueError("Unsafe asset path in cloud release.")
        path = HOME / media["path"]
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != key:
            data = target.blob(media["path"]).download_as_bytes()
            if hashlib.sha256(data).hexdigest() != key:
                raise ValueError("Downloaded media checksum mismatch.")
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
    atomic_json(HOME / "data/archive.json", archive)
    atomic_json(HOME / "data/sync.json", {"source": "gcs", "generation": generation})
    return {"posts": len(archive["posts"]), "batches": len(archive["batches"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["upload", "process", "pull"])
    parser.add_argument("source", type=Path, nargs="?")
    args = parser.parse_args()
    if args.command == "upload" and args.source is None:
        parser.error("upload requires a batch JSON file")
    result = upload(args.source) if args.command == "upload" else process() if args.command == "process" else pull()
    print(json.dumps(result, ensure_ascii=False))
