import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gh_ui_cli.profile import (
    load_profile,
    profile_path,
    resolve_access_token,
    resolve_api_token,
    resolve_server,
    save_profile,
)


class ProfileTest(unittest.TestCase):
    def test_profile_file_path_can_be_overridden_for_cross_platform_agents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            with patch.dict(os.environ, {"GH_UI_CLI_PROFILE": str(path)}, clear=True):
                self.assertEqual(profile_path(), path)

    def test_profile_round_trips_tokens_and_prefers_environment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile.json"
            with patch.dict(os.environ, {"GH_UI_CLI_PROFILE": str(path)}, clear=True):
                save_profile(
                    {
                        "api_token": "profile-api",
                        "access_token": "profile-access",
                        "server": "secondary",
                        "username": "agent",
                    }
                )

                self.assertEqual(load_profile()["username"], "agent")
                self.assertEqual(resolve_api_token(None), "profile-api")
                self.assertEqual(resolve_access_token(None), "profile-access")
                self.assertEqual(resolve_server(None), "secondary")

                with patch.dict(
                    os.environ,
                    {
                        "GH_UI_CLI_PROFILE": str(path),
                        "GH_API_TOKEN": "env-api",
                        "GH_ACCESS_TOKEN": "env-access",
                    },
                    clear=True,
                ):
                    self.assertEqual(resolve_api_token(None), "env-api")
                    self.assertEqual(resolve_access_token(None), "env-access")


if __name__ == "__main__":
    unittest.main()
