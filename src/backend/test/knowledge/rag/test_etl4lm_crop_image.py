"""Unit tests for Etl4lmLoader.crop_image bbox handling.

Regression: a degenerate / out-of-bounds bbox produced an empty numpy slice,
and cv2.imwrite raised `(-215:Assertion failed) !_img.empty()`, which crashed
the entire knowledge-file parse (see file_id=93594 incident).
"""

import os
import tempfile
import unittest

import cv2
import numpy as np

from bisheng.knowledge.rag.pipeline.loader.etl4lm import Etl4lmLoader


class CropImageTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.loader = Etl4lmLoader(
            url="http://unused",
            ocr_sdk_url="http://unused",
            file_path=os.path.join(self.tmp_dir, "dummy.pdf"),
            file_metadata={},
            file_extension="pdf",
            tmp_dir=self.tmp_dir,
        )
        self.loader.ensure_local_image_dir()
        # A 100x100 page image to crop from.
        self.page_path = os.path.join(self.tmp_dir, "page.png")
        cv2.imwrite(self.page_path, np.full((100, 100, 3), 255, np.uint8))

    def test_degenerate_bbox_does_not_crash(self):
        # y1 == y2 -> empty slice -> previously crashed cv2.imwrite.
        url = self.loader.crop_image(self.page_path, {"element_id": "e1", "bboxes": [10, 50, 90, 50]})
        self.assertIsNone(url)

    def test_out_of_bounds_bbox_does_not_crash(self):
        url = self.loader.crop_image(self.page_path, {"element_id": "e2", "bboxes": [200, 200, 300, 300]})
        self.assertIsNone(url)

    def test_inverted_bbox_does_not_crash(self):
        url = self.loader.crop_image(self.page_path, {"element_id": "e3", "bboxes": [90, 90, 10, 10]})
        self.assertIsNotNone(url)
        self.assertTrue(os.path.exists(os.path.join(self.loader.local_image_dir, "e3.png")))

    def test_valid_bbox_writes_image(self):
        url = self.loader.crop_image(self.page_path, {"element_id": "e4", "bboxes": [10, 10, 60, 60]})
        self.assertIsNotNone(url)
        self.assertTrue(os.path.exists(os.path.join(self.loader.local_image_dir, "e4.png")))

    def test_unreadable_page_image_does_not_crash(self):
        url = self.loader.crop_image(
            os.path.join(self.tmp_dir, "missing.png"), {"element_id": "e5", "bboxes": [10, 10, 60, 60]}
        )
        self.assertIsNone(url)


if __name__ == "__main__":
    unittest.main()
