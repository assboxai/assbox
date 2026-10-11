# SPDX-License-Identifier: GPL-3.0-or-later
"""Execute CI orchestration with fake Nix/CLI effects; never claim signatures."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import release as publisher
import release_data as data
from test_release_data import lock
from test_release_lineage import manifest
from test_kernel_cache import publication_fixture

BOOT = "/nix/store/" + "a" * 32 + "-assbox-bootstrap"
CANDIDATE = "/nix/store/" + "b" * 32 + "-assbox-candidate"
SOURCE = "/nix/store/" + "c" * 32 + "-source"
DIRECTORY = Path("/var/lib/assbox-public-1-1-x86_64-linux")


class PublicVerifierTests(unittest.TestCase):
    def exercise(self, *, system="x86_64-linux", fail=None, change=None, same_binary=False):
        effects = []
        release_bytes = data.json_bytes(manifest())
        lock_bytes = data.json_bytes(lock())
        def run(*args, **kwargs):
            effects.append(args)
            if fail is not None and fail(args):
                raise subprocess.CalledProcessError(1, args)
            if change is not None:
                value = change(args)
                if value is not None:
                    return value
            if args[:2] == ("nix", "eval"):
                return system.encode()
            if args[:2] == ("nix", "build"):
                self.assertIn("--no-update-lock-file", args)
                self.assertIn("--no-write-lock-file", args)
                if args[-1] == f".#packages.{system}.assbox":
                    return (BOOT + "\n").encode()
                self.assertEqual(args[-1], f"path:{SOURCE}#packages.{system}.assbox")
                self.assertTrue(any("verify" in old and old[-1].endswith("-bootstrap") for old in effects[:-1]))
                return ((BOOT if same_binary else CANDIDATE) + "\n").encode()
            if args[:3] == ("sudo", "cat", "--"):
                name = Path(args[-1]).name
                return {"release.json": release_bytes, "flake.lock": lock_bytes, "verified-source-path": SOURCE.encode()}[name]
            if args[0] == "sudo" and args[2:4] == ("release", "verify"):
                self.assertEqual(args[4], "r-1")
                suffix = "bootstrap" if not any("verify" in previous for previous in effects[:-1]) else "candidate"
                self.assertTrue(args[-1].endswith("-" + suffix))
                expected = BOOT if suffix == "bootstrap" or same_binary else CANDIDATE
                self.assertEqual(args[1], f"{expected}/bin/assbox")
                return b"deliberately non-authoritative console output"
            if args[0] == "sudo" and args[2:4] == ("release", "verify-kernel"):
                self.assertEqual(args[4], "r-1")
                self.assertEqual(args[1], f"{BOOT if same_binary else CANDIDATE}/bin/assbox")
                self.assertTrue(args[-1].endswith("-kernel"))
                self.assertEqual(len([old for old in effects[:-1] if "verify" in old]), 2)
                return b"deliberately non-authoritative kernel console output"
            raise AssertionError(args)
        with patch.object(publisher, "API_TOKEN", None), patch.object(publisher, "run", side_effect=run), patch.object(publisher, "api") as api, patch("builtins.print"):
            try:
                publisher.live_verify("r-1", system, DIRECTORY)
            finally:
                api.assert_not_called()  # No discovery, mutation, or tokened fallback.
        return effects

    def test_both_native_architectures_build_the_authenticated_release_lock(self):
        for system in data.SYSTEMS:
            with self.subTest(system=system):
                calls = self.exercise(system=system)
                self.assertEqual(len([x for x in calls if x[:2] == ("nix", "build")]), 2)
                verifies = [x for x in calls if "verify" in x]
                self.assertEqual(len(verifies), 2)
                self.assertNotEqual(verifies[0][-1], verifies[1][-1])

    def test_unchanged_renewal_may_produce_the_same_binary(self):
        self.exercise(same_binary=True)

    def test_cold_kernel_failure_and_receipt_disagreement_are_fatal(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.exercise(fail=lambda args: "verify-kernel" in args)
        def change(args):
            if args[:3] == ("sudo", "cat", "--") and "-kernel/" in args[-1] and args[-1].endswith("verified-source-path"):
                return ("/nix/store/" + "d" * 32 + "-source").encode()
            return None
        with self.assertRaises(ValueError):
            self.exercise(change=change)
        calls=self.exercise()
        self.assertEqual(len([call for call in calls if "verify-kernel" in call]), 1)

    def test_bootstrap_failure_never_builds_or_executes_candidate(self):
        seen = []
        def fail(args):
            seen.append(args)
            return "verify" in args
        with self.assertRaises(subprocess.CalledProcessError): self.exercise(fail=fail)
        self.assertFalse(any(str(args[-1]).startswith("path:") for args in seen))
        self.assertEqual(len([x for x in seen if "verify" in x]), 1)

    def test_candidate_build_and_public_verification_failures_are_fatal(self):
        for fail in [lambda args: args[-1].startswith("path:"),
                     lambda args: "verify" in args and args[-1].endswith("-candidate")]:
            with self.subTest(fail=fail), self.assertRaises(subprocess.CalledProcessError): self.exercise(fail=fail)

    def test_output_manifest_lock_and_source_disagreement_are_fatal(self):
        for name, raw in [("release.json", b"{}\n"), ("flake.lock", b"{}\n"),
                          ("verified-source-path", ("/nix/store/" + "d" * 32 + "-source").encode())]:
            def change(args):
                if args[:3] == ("sudo", "cat", "--") and "-candidate/" in args[-1] and args[-1].endswith(name): return raw
                return None
            with self.subTest(name=name), self.assertRaises(ValueError): self.exercise(change=change)

    def test_malformed_or_mismatched_bootstrap_receipts_stop_before_candidate_build(self):
        for name, raw in [("release.json", b"{}\n"), ("flake.lock", b"{}\n"), ("verified-source-path", b"github:untrusted/source")]:
            seen = []
            def change(args):
                seen.append(args)
                if args[:3] == ("sudo", "cat", "--") and "-bootstrap/" in args[-1] and args[-1].endswith(name): return raw
                return None
            with self.subTest(name=name), self.assertRaises((ValueError, KeyError)): self.exercise(change=change)
            self.assertFalse(any(str(args[-1]).startswith("path:") for args in seen))

    def test_untrusted_refs_unsafe_paths_and_cross_architecture_fail(self):
        for tag, system, directory in [("latest", "x86_64-linux", DIRECTORY), ("r-1", "other", DIRECTORY),
                                        ("r-1", "x86_64-linux", Path("/tmp/public")), ("r-1", "x86_64-linux", Path("relative"))]:
            with patch.object(publisher, "API_TOKEN", None), patch.object(publisher, "run") as run:
                with self.assertRaises(ValueError): publisher.live_verify(tag, system, directory)
                run.assert_not_called()
        with patch.object(publisher, "API_TOKEN", None), patch.object(publisher, "run", return_value=b"aarch64-linux") as run:
            with self.assertRaises(ValueError): publisher.live_verify("r-1", "x86_64-linux", DIRECTORY)
            self.assertEqual(run.call_count, 1)

    def test_public_flow_refuses_to_hold_an_api_credential(self):
        with patch.object(publisher, "API_TOKEN", "fake-token"), patch.object(publisher, "run") as run:
            with self.assertRaises(ValueError): publisher.live_verify("r-1", "x86_64-linux", DIRECTORY)
            run.assert_not_called()

    def test_store_output_rejects_multiple_paths_options_and_path_escapes(self):
        self.assertEqual(publisher.store_path(SOURCE.encode()), SOURCE)
        self.assertEqual(publisher.store_path((SOURCE + "\n").encode()), SOURCE)
        for raw in [b"", b"--override-input", b"/nix/store/short-source", (SOURCE + "/subpath").encode(),
                    (SOURCE + "\n" + BOOT).encode(), (SOURCE + "\n\n").encode(), b"\xff"]:
            with self.assertRaises(ValueError): publisher.store_path(raw)


class PublicationRecheckTests(unittest.TestCase):
    def test_attestation_guard_requires_evidence_then_current_master(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            assets=Path(temp)/"assets"; assets.mkdir()
            reports=Path(temp)/"reports"; reports.mkdir()
            release_bytes=data.json_bytes(manifest())
            (assets/"release.json").write_bytes(release_bytes)
            for system in data.SYSTEMS:
                directory=reports/("kernel-"+system); directory.mkdir()
                publication_fixture(directory, release_bytes, system)
            with patch.object(publisher, "ready", side_effect=lambda *a: calls.append("evidence")), \
                 patch.object(publisher, "check_repository", side_effect=lambda **k: calls.append("head")):
                publisher.attestation_ready(assets, reports)
        self.assertEqual(calls, ["evidence", "head"])
        with patch.object(publisher, "ready", side_effect=ValueError("bad evidence")), patch.object(publisher, "check_repository") as head:
            with self.assertRaises(ValueError): publisher.attestation_ready(Path("assets"), Path("reports"))
            head.assert_not_called()

    def test_each_write_rechecks_master_before_the_effect(self):
        effects = []
        with patch.object(publisher, "check_repository", side_effect=lambda **k: effects.append("head")), \
             patch.object(publisher, "api", side_effect=lambda *a, **k: effects.append("write")):
            publisher.write_api("/repos/assboxai/assbox/git/refs", {})
            publisher.write_api("/repos/assboxai/assbox/releases/1", {}, method="PATCH")
        self.assertEqual(effects, ["head", "write", "head", "write"])
        with patch.object(publisher, "check_repository", side_effect=ValueError("master moved")), patch.object(publisher, "api") as api:
            with self.assertRaises(ValueError): publisher.write_api("/repos/assboxai/assbox/releases/1", {})
            api.assert_not_called()

    def test_current_head_check_refuses_stale_sha_even_on_same_named_branch(self):
        pol = {"repositoryId": 22, "ownerId": 33}
        repository = {"id": 22, "owner": {"id": 33}, "default_branch": "master", "private": False, "fork": False}
        with patch.object(publisher, "policy", return_value=pol), \
             patch.dict(os.environ, {"GITHUB_SHA": "a" * 40}), \
             patch.object(publisher, "api", side_effect=[repository, {"object": {"sha": "b" * 40}}]) as api:
            with self.assertRaisesRegex(ValueError, "master moved"): publisher.check_repository(privileged=True)
            self.assertTrue(all(call.kwargs.get("token") for call in api.call_args_list))

    def test_mid_publication_master_change_prevents_every_subsequent_effect(self):
        with tempfile.TemporaryDirectory() as temp:
            assets = Path(temp); (assets / "release.sigstore.json").write_bytes(b"{}")
            release_bytes=data.json_bytes(manifest())
            for name, raw in [("release.json", release_bytes), ("flake.lock", b"contract-only lock"),
                              ("assbox-source.tar.gz", b"contract-only archive")]:
                (assets/name).write_bytes(raw)
            for system in data.SYSTEMS:
                publication_fixture(assets, release_bytes, system)
            # Entry, tag, draft, upload, finalization. Refuse at every boundary.
            for boundary in range(1, 6):
                checks = 0; effects = []
                def head(**kwargs):
                    nonlocal checks
                    checks += 1
                    if checks == boundary: raise ValueError("master moved")
                def api(path, payload=None, **kwargs):
                    effects.append("write")
                    return {"id": 12, "immutable": True}
                def upload(*args, **kwargs): effects.append("upload")
                with patch.object(publisher, "ready", return_value=manifest()), patch.object(publisher, "check_parent_head"), \
                     patch.object(publisher, "check_repository", side_effect=head), patch.object(publisher, "api", side_effect=api), \
                     patch.object(publisher, "run", side_effect=upload), patch.object(publisher, "output") as output:
                    with self.assertRaisesRegex(ValueError, "master moved"): publisher.publish(assets, assets)
                    output.assert_not_called()
                self.assertEqual(len(effects), max(0, boundary - 2))


if __name__ == "__main__": unittest.main()
