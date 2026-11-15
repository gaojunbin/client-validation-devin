import unittest

import helpers
from client_validation_devin import gitops
from client_validation_devin.errors import GitError


class SlugTest(unittest.TestCase):
    def test_remote_forms(self):
        cases = {
            "git@github.com:acme/notes.git": "acme/notes",
            "https://github.com/acme/notes.git": "acme/notes",
            "https://token@github.com/acme/notes": "acme/notes",
            "ssh://git@gitlab.com/group/sub/app.git": "group/sub/app",
        }
        for url, slug in cases.items():
            with self.subTest(url=url):
                self.assertEqual(gitops.repo_slug(url), slug)

    def test_unparseable(self):
        with self.assertRaises(GitError):
            gitops.repo_slug("/local/path/remote.git")

    def test_safe_name_is_one_harmless_component(self):
        self.assertEqual(gitops.safe_name(".."), "unnamed")
        self.assertEqual(gitops.safe_name("../../etc/passwd"), "etc-passwd")
        self.assertEqual(gitops.safe_name("feature/login ui"), "feature-login-ui")
        self.assertEqual(gitops.safe_name("r1-ios__launch__01.png"), "r1-ios__launch__01.png")


class StateHomeTest(unittest.TestCase):
    def test_state_root_is_private(self):
        import os
        import stat
        import tempfile
        from unittest import mock

        from client_validation_devin.state import home

        with tempfile.TemporaryDirectory() as tmp:
            target = f"{tmp}/client-validation-devin"
            with mock.patch.dict(os.environ, {"CLIENT_VALIDATION_DEVIN_HOME": target}):
                home()
            self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o700)


class RepoTest(unittest.TestCase):
    def setUp(self):
        self.repo = helpers.ProductRepo()

    def tearDown(self):
        self.repo.cleanup()

    def test_branch_base_and_changes(self):
        root = self.repo.path
        self.assertEqual(gitops.current_branch(root), "feature-x")
        self.assertEqual(gitops.default_branch(root, "origin"), "main")
        base = gitops.merge_base(root, "origin")
        self.assertEqual(gitops.changed_files(root, base), ["lib/editor/editor.dart"])
        self.assertIn("editor.dart", gitops.diff_stat(root, base))

    def test_push_scratch_ref_and_bundle(self):
        root = self.repo.path
        gitops.push_scratch_ref(root, "origin", "client-validation-devin/feature-x")
        remote_sha = helpers.git(self.repo.remote, "rev-parse", "refs/heads/client-validation-devin/feature-x")
        self.assertEqual(remote_sha, gitops.head_sha(root))
        bundle = gitops.create_bundle(root, self.repo.state / "x.bundle")
        self.assertIn("HEAD", helpers.git(root, "bundle", "list-heads", str(bundle)))

    def test_dirty_detection(self):
        self.assertFalse(gitops.is_dirty(self.repo.path))
        (self.repo.path / "README.md").write_text("changed\n")
        self.assertTrue(gitops.is_dirty(self.repo.path))


if __name__ == "__main__":
    unittest.main()
