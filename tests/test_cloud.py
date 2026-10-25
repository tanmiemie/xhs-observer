import json
import unittest
from unittest.mock import patch

from google.api_core.exceptions import NotFound, PreconditionFailed

import cloud
import core
from tests.test_pipeline import batch


class Blob:
    def __init__(self, target, name):
        self.target, self.name = target, name
        self.generation = None

    def upload_from_string(self, raw, content_type=None, if_generation_match=None):
        current = self.target.data.get(self.name)
        generation = current[0] if current else 0
        if self.name == "latest.json" and self.target.conflicts:
            self.target.conflicts -= 1
            raise PreconditionFailed("simulated concurrent update")
        if if_generation_match is not None and if_generation_match != generation:
            raise PreconditionFailed("generation mismatch")
        self.target.counter += 1
        self.target.data[self.name] = (self.target.counter, raw)

    def download_as_bytes(self, if_generation_match=None):
        if self.name not in self.target.data:
            raise NotFound("missing")
        generation, raw = self.target.data[self.name]
        if if_generation_match is not None and generation != if_generation_match:
            raise PreconditionFailed("read generation changed")
        return raw

    def reload(self):
        if self.name not in self.target.data:
            raise NotFound("missing")
        self.generation = self.target.data[self.name][0]

    def exists(self):
        return self.name in self.target.data


class Bucket:
    def __init__(self):
        self.data, self.counter, self.conflicts = {}, 0, 0

    def blob(self, name):
        return Blob(self, name)

    def list_blobs(self, prefix):
        return [self.blob(name) for name in sorted(self.data) if name.startswith(prefix)]


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.bucket = Bucket()
        cloud.put_immutable(self.bucket, "incoming/test.json", core.canonical({"batch": batch(), "assets": {}}))

    def test_repeated_processing_is_idempotent(self):
        cloud.process(self.bucket)
        cloud.process(self.bucket)
        archive, _ = cloud.read_release(self.bucket)
        self.assertEqual(len(archive["posts"]), 5)
        self.assertEqual(len(archive["batches"]), 1)

    def test_concurrent_release_retry(self):
        self.bucket.conflicts = 1
        cloud.process(self.bucket)
        archive, _ = cloud.read_release(self.bucket)
        self.assertEqual(len(archive["posts"]), 5)

    def test_corrupt_input_does_not_advance_release_pointer(self):
        cloud.process(self.bucket)
        before = self.bucket.blob("latest.json").download_as_bytes()
        bad = batch()
        bad["posts"].pop()
        cloud.put_immutable(self.bucket, "incoming/bad.json", core.canonical({"batch": bad, "assets": {}}))
        with self.assertRaises(ValueError):
            cloud.process(self.bucket)
        self.assertEqual(before, self.bucket.blob("latest.json").download_as_bytes())

    def test_immutable_collision_is_rejected(self):
        cloud.put_immutable(self.bucket, "same", b"first")
        with self.assertRaisesRegex(ValueError, "collision"):
            cloud.put_immutable(self.bucket, "same", b"second")


if __name__ == "__main__":
    unittest.main()
