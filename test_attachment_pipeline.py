import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import app


TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9Y9Z4WQAAAAASUVORK5CYII="
)


class AttachmentPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.upload_dir = Path(self.temp_dir.name)
        self.patch = patch.object(app, "CHAT_UPLOAD_DIR", self.upload_dir)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp_dir.cleanup()

    def create_attachment(self, user_id, attachment_id, name, kind, mime, content):
        user_dir = self.upload_dir / str(user_id)
        user_dir.mkdir(parents=True)
        suffix = Path(name).suffix
        stored_name = f"{attachment_id}{suffix}"
        (user_dir / stored_name).write_bytes(content)
        (user_dir / f"{attachment_id}.json").write_text(
            json.dumps({
                "id": attachment_id,
                "name": name,
                "type": kind,
                "mime": mime,
                "size": len(content),
                "stored_name": stored_name,
            }),
            encoding="utf-8",
        )

    def test_document_content_is_added_to_user_message(self):
        attachment_id = "4a9f0f89-9088-44f6-a217-f9a997d669b1"
        self.create_attachment(
            7,
            attachment_id,
            "notes.txt",
            "file",
            "text/plain",
            b"alpha beta gamma",
        )

        content, requires_vision = app._build_user_message_content(
            "Summarize this file",
            [{"id": attachment_id, "type": "file", "name": "notes.txt"}],
            7,
        )

        self.assertFalse(requires_vision)
        self.assertIn("Summarize this file", content)
        self.assertIn("alpha beta gamma", content)

    def test_image_is_converted_to_multimodal_content(self):
        attachment_id = "a32cc452-b4c2-40d5-ae1c-8ba7ce2b43f9"
        self.create_attachment(
            7,
            attachment_id,
            "pixel.png",
            "image",
            "image/png",
            TINY_PNG,
        )

        content, requires_vision = app._build_user_message_content(
            "Describe this image",
            [{"id": attachment_id, "type": "image", "name": "pixel.png"}],
            7,
        )

        self.assertTrue(requires_vision)
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_image_uses_ocr_when_vision_model_is_not_configured(self):
        attachment_id = "4c1772c2-e7c7-4e94-8e8a-1f50345c20b7"
        self.create_attachment(
            7,
            attachment_id,
            "text.png",
            "image",
            "image/png",
            TINY_PNG,
        )

        with patch.object(app, "_extract_image_text_windows", return_value="invoice total 42"):
            content, requires_vision = app._build_user_message_content(
                "Read this image",
                [{"id": attachment_id, "type": "image", "name": "text.png"}],
                7,
                use_vision=False,
            )

        self.assertFalse(requires_vision)
        self.assertIn("invoice total 42", content)

    def test_user_cannot_reference_another_users_attachment(self):
        attachment_id = "652a6de4-a18a-4395-98d8-8cf7a81f2cb4"
        self.create_attachment(
            8,
            attachment_id,
            "private.txt",
            "file",
            "text/plain",
            b"private",
        )

        with self.assertRaises(HTTPException) as raised:
            app._build_user_message_content(
                "Read it",
                [{"id": attachment_id, "type": "file", "name": "private.txt"}],
                7,
            )

        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
