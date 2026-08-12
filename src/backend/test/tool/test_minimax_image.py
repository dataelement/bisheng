import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[2] / "bisheng_langchain" / "gpts" / "tools" / "api_tools" / "minimax_image_core.py"
SPEC = importlib.util.spec_from_file_location("minimax_image_core", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
build_image_generation_payload = MODULE.build_image_generation_payload
parse_image_generation_response = MODULE.parse_image_generation_response


class TestMiniMaxImagePayload(unittest.TestCase):
    def test_builds_supported_request_fields(self):
        payload = build_image_generation_payload(
            prompt="A small robot reading a book",
            model="image-01-live",
            aspect_ratio=None,
            width=1024,
            height=768,
            response_format="base64",
            seed=7,
            n=2,
            prompt_optimizer=True,
        )

        self.assertEqual(
            payload,
            {
                "model": "image-01-live",
                "prompt": "A small robot reading a book",
                "width": 1024,
                "height": 768,
                "response_format": "base64",
                "seed": 7,
                "n": 2,
                "prompt_optimizer": True,
            },
        )

    def test_parses_url_response_and_metadata(self):
        result = parse_image_generation_response(
            {
                "data": {"image_urls": ["https://example.test/image.png"]},
                "metadata": {"success_count": 1, "failed_count": 0},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
            "url",
        )

        self.assertEqual(result["images"], ["https://example.test/image.png"])
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["failed_count"], 0)

    def test_parses_base64_response(self):
        result = parse_image_generation_response(
            {
                "data": {"image_base64": ["aW1hZ2U="]},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
            "base64",
        )

        self.assertEqual(result["images"], ["aW1hZ2U="])

    def test_rejects_provider_error(self):
        with self.assertRaisesRegex(ValueError, "invalid request"):
            parse_image_generation_response(
                {"base_resp": {"status_code": 2013, "status_msg": "invalid request"}},
                "url",
            )


if __name__ == "__main__":
    unittest.main()
