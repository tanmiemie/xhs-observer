import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core


def batch(end="2026-10-24", capture="2026-10-24T23:00:00Z"):
    return {"date": end, "period_start": end, "period_end": end, "mode": "weekly-backfill", "posts": [{"id": f"{i:024x}", "title": "测试标题", "author": "测试作者", "author_id": f"{i+100:024x}", "summary": "测试摘要", "body": "测试正文", "url": f"https://www.xiaohongshu.com/explore/{i:024x}", "published_date": end, "publication_basis": "detail-page", "capturedAt": capture, "keywords": ["信用卡"], "likes": i, "saves": 2, "comments": 3, "media_refs": []} for i in range(1, 6)]}


class LibraryTests(unittest.TestCase):
    def test_idempotent_batch(self):
        first = core.merge(core.empty_archive(), batch(), {})
        self.assertEqual(first, core.merge(first, batch(), {}))

    def test_backfill_does_not_replace_newer_week(self):
        newer = core.merge(core.empty_archive(), batch(), {})
        result = core.merge(newer, batch("2026-10-10", "2026-10-25T01:00:00Z"), {})
        self.assertEqual(len(result["snapshots"]), 10)
        self.assertEqual(result["latest_batch_id"], newer["latest_batch_id"])

    def test_excluded_publisher_requires_replacement(self):
        value = batch()
        value["posts"][0]["author_id"] = "6211936c00000000100056ae"
        with self.assertRaisesRegex(ValueError, "Excluded publisher"):
            core.merge(core.empty_archive(), value, {})

    def test_publication_window_and_capture_are_distinct(self):
        value = batch("2026-10-10", "2026-10-25T01:00:00Z")
        self.assertTrue(core.validate(value, core.config()))
        value["posts"][0]["published_date"] = "2026-10-24"
        with self.assertRaisesRegex(ValueError, "publication date"):
            core.validate(value, core.config())

    def test_missing_metrics_not_zero(self):
        value = batch()
        value["posts"][0]["likes"] = None
        with self.assertRaisesRegex(ValueError, "do not substitute zero"):
            core.validate(value, core.config())

    def test_rejected_batch_preserves_local_file(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            source = home / "batch.json"
            source.write_text(json.dumps(batch()))
            with patch.object(core, "HOME", home):
                core.ingest_local(source)
                archive = home / "data/archive.json"
                previous = archive.read_bytes()
                invalid = batch()
                invalid["posts"].pop()
                source.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    core.ingest_local(source)
                self.assertEqual(previous, archive.read_bytes())

    def test_media_path_cannot_escape_batch_folder(self):
        value = batch()
        value["posts"][0]["files"] = ["../private.webp"]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unsafe media"):
                core.read_assets(value, directory)

    def test_two_topics_cannot_repeat_the_same_post(self):
        first = core.merge(core.empty_archive(), batch(), {})
        second = batch()
        second["topic"] = "north-america-life"
        with self.assertRaisesRegex(ValueError, "must not repeat"):
            core.merge(first, second, {})

    def test_two_distinct_topics_keep_ten_posts(self):
        first = core.merge(core.empty_archive(), batch(), {})
        second = batch()
        second["topic"] = "north-america-life"
        for i, post in enumerate(second["posts"], 10):
            post["id"] = f"{i:024x}"
            post["url"] = "https://www.xiaohongshu.com/explore/" + post["id"]
        result = core.merge(first, second, {})
        self.assertEqual(len(result["posts"]), 10)
        self.assertEqual(len(result["batches"]), 2)

    def test_missing_media_reference_is_rejected(self):
        value = batch()
        value["posts"][0]["media_refs"] = [{"id": "missing", "role": "cover", "order": 0}]
        with self.assertRaisesRegex(ValueError, "not present"):
            core.merge(core.empty_archive(), value, {})


if __name__ == "__main__":
    unittest.main()
