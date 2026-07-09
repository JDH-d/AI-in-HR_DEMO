import os
import unittest
from unittest.mock import patch

import streamlit.testing.v1.app_test as streamlit_app_test
from streamlit.testing.v1 import AppTest


class DummyResponse:
    def __init__(self, content: str = "stubbed answer", sources: list[dict] | None = None) -> None:
        self.status_code = 200
        self.text = ""
        self._payload = {
            "message": {"role": "assistant", "content": content},
            "sources": sources or [],
        }

    def json(self) -> dict:
        return self._payload


class StreamlitComposerInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if hasattr(streamlit_app_test.TMP_DIR, "_finalizer"):
            streamlit_app_test.TMP_DIR._finalizer.detach()

    def _build_app(self, response: DummyResponse | None = None) -> AppTest:
        chat_patcher = patch(
            "web_ui.api_client.DemoAPIClient.chat",
            return_value=response or DummyResponse(),
        )
        chat_patcher.start()
        self.addCleanup(chat_patcher.stop)

        app = AppTest.from_file(os.path.join("web_ui", "streamlit_app.py"))
        app.run(timeout=10)
        return app

    def _assert_single_composer(self, app: AppTest, *, disabled: bool) -> None:
        composer_inputs = [item for item in app.text_input if item.key == "composer_draft"]
        composer_toggle_buttons = [item for item in app.button if item.key == "composer_toggle"]
        composer_send_buttons = [item for item in app.button if item.key == "composer_send"]

        self.assertEqual(len(composer_inputs), 1)
        self.assertEqual(len(composer_toggle_buttons), 1)
        self.assertEqual(len(composer_send_buttons), 1)
        self.assertEqual(composer_inputs[0].disabled, disabled)
        self.assertEqual(composer_toggle_buttons[0].disabled, disabled)
        self.assertEqual(composer_send_buttons[0].disabled, disabled)

    def test_initial_empty_state_renders_single_enabled_composer(self) -> None:
        app = self._build_app()

        self._assert_single_composer(app, disabled=False)

    def test_first_in_flight_render_keeps_single_disabled_composer(self) -> None:
        with (
            patch("web_ui.api_client.DemoAPIClient.chat", return_value=DummyResponse()),
            patch(
                "web_ui.streamlit_app._stream_assistant_response",
                return_value=None,
            ),
            patch("web_ui.streamlit_app.st.rerun", return_value=None),
        ):
            app = AppTest.from_file(os.path.join("web_ui", "streamlit_app.py"))
            app.session_state["messages"] = []
            app.session_state["composer_draft"] = "stale draft"
            app.session_state["drawer_open"] = False
            app.session_state["request_in_flight"] = True
            app.session_state["queued_prompt"] = "How often are salaries paid?"
            app.run(timeout=10)

        self._assert_single_composer(app, disabled=True)
        self.assertEqual(app.session_state["composer_draft"], "")

    def test_demo_prompt_toggle_opens_drawer_without_submitting_draft(self) -> None:
        app = self._build_app()

        app.text_input(key="composer_draft").input("draft message")
        app.button(key="composer_toggle").click().run(timeout=10)

        self.assertTrue(app.session_state["drawer_open"])
        self.assertEqual(app.session_state["composer_draft"], "draft message")
        self.assertEqual(app.session_state["messages"], [])
        self.assertEqual(app.session_state["queued_prompt"], "")

    def test_composer_form_submit_sends_current_prompt(self) -> None:
        app = self._build_app(DummyResponse(content="Payroll answer"))

        app.text_input(key="composer_draft").input("How often are salaries paid?")
        app.button(key="composer_send").click().run(timeout=10)

        self.assertEqual(
            app.session_state["messages"],
            [
                {"role": "user", "content": "How often are salaries paid?"},
                {"role": "assistant", "content": "Payroll answer", "sources": []},
            ],
        )
        self.assertEqual(app.session_state["composer_draft"], "")
        self.assertFalse(app.session_state["drawer_open"])
        self.assertFalse(app.session_state["request_in_flight"])
        self.assertEqual(app.session_state["queued_prompt"], "")

    def test_demo_prompt_submission_ignores_stale_draft(self) -> None:
        app = self._build_app()

        app.text_input(key="composer_draft").input("stale draft")
        app.button(key="composer_toggle").click().run(timeout=10)
        app.button(key="demo_prompt_0_0").click().run(timeout=10)

        self.assertEqual(
            app.session_state["messages"],
            [
                {"role": "user", "content": "What can you help with?"},
                {"role": "assistant", "content": "stubbed answer", "sources": []},
            ],
        )
        self.assertEqual(app.session_state["composer_draft"], "")
        self.assertFalse(app.session_state["drawer_open"])
        self.assertFalse(app.session_state["request_in_flight"])
        self.assertEqual(app.session_state["queued_prompt"], "")


if __name__ == "__main__":
    unittest.main()
