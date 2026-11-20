import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from openai import APIConnectionError

from api_pool import POOL_ENV, resolve_pool_route
from pipeline import (
    Config,
    ContentBlockedError,
    UnifiedAgent,
    get_primary_provider_route,
    validate_final_review_provider_configuration,
    validate_provider_configuration,
)
from scripts.configure_api_pool import (
    _configure_embedding,
    activate,
    configure,
    main as configure_api_pool_main,
)
from api_pool_store import load_profile, migrate_v1_profile, save_profile
from pipeline import validate_provider_base_url
from windows_credentials import CredentialStoreError, delete_secret, read_secret, write_secret


def _write_v1_profile(path, vault):
    pool = {"main": {"base_url": "https://main.test/v1", "model": "model-a"}}
    assignments = {
        role: "main"
        for role in ("INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL")
    }
    grants = {"pool-main": ["source_text", "translation_text", "book_knowledge"]}
    profile = {
        "version": 1,
        "pool": {
            "main": {
                **pool["main"],
                "credential_ref": "TranslatorAI/API/" + uuid.uuid4().hex,
            }
        },
        "assignments": assignments,
        "fallback": "",
        "grants": grants,
    }
    digest = __import__("hashlib").sha256(
        json.dumps(
            profile,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    old_ref = profile["pool"]["main"]["credential_ref"]
    vault[old_ref] = json.dumps(
        {"profile_sha256": digest, "key": "legacy-synthetic-key"}
    )
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    return profile, old_ref, pool, assignments, grants


class PoolTests(unittest.IsolatedAsyncioTestCase):
    def test_rejects_missing_and_malformed_slots(self):
        with patch.dict(os.environ, {POOL_ENV: "{}"}, clear=True):
            for name in ("pool:missing", "pool:../bad", "pool:"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    resolve_pool_route(name)

    async def test_request_sends_real_model_id(self):
        pool = {"primary": {"base_url": "https://example.test/v1", "model": "vendor-model"}}
        response = MagicMock()
        response.choices[0].finish_reason = "stop"
        response.choices[0].message.content = "ok"
        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=response)
        with patch.dict(os.environ, {POOL_ENV: json.dumps(pool)}, clear=True):
            with patch("pipeline.get_openai_client", return_value=client):
                result = await UnifiedAgent("pool:primary", "instruction")._call_primary("x", "y")
        self.assertEqual(result, "ok")
        self.assertEqual(client.chat.completions.create.await_args.kwargs["model"], "vendor-model")

    def test_fallback_requires_its_own_authorization(self):
        pool = {
            "primary": {"base_url": "https://primary.test/v1", "model": "p"},
            "backup": {"base_url": "https://backup.test/v1", "model": "b"},
        }
        env = {
            POOL_ENV: json.dumps(pool),
            "TRANSLATORAI_POOL_FALLBACK": "pool:backup",
            "TRANSLATORAI_POOL_KEY_PRIMARY": "test",
            "TRANSLATORAI_POOL_KEY_BACKUP": "test",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(Config, "INITIAL_MODEL", "pool:primary"), \
                 patch.object(Config, "PROOFREAD_MODEL", "pool:primary"), \
                 patch.object(Config, "STYLE_MODEL", "pool:primary"), \
                 patch.object(Config, "JYQF_FALLBACK_ENABLED", False), \
                 patch.object(Config, "GEMINI_FALLBACK_ENABLED", False), \
                 patch.object(Config, "PROVIDER_DATA_POLICY", {
                     "pool-primary": frozenset({"source_text", "translation_text", "book_knowledge"})
                 }):
                with self.assertRaises(PermissionError):
                    validate_provider_configuration()

    async def test_temporary_error_falls_back_once_but_block_does_not(self):
        pool = {
            "primary": {"base_url": "https://primary.test/v1", "model": "p"},
            "backup": {"base_url": "https://backup.test/v1", "model": "b"},
        }
        env = {POOL_ENV: json.dumps(pool), "TRANSLATORAI_POOL_FALLBACK": "pool:backup"}
        agent = UnifiedAgent("pool:primary", "instruction")
        error = APIConnectionError(request=object())
        with patch.dict(os.environ, env, clear=True):
            with patch.object(agent, "_call_primary", new_callable=AsyncMock,
                              side_effect=[error, "recovered"]) as call:
                self.assertEqual(await agent.call("synthetic"), "recovered")
                self.assertEqual(call.await_count, 2)
                self.assertEqual(call.await_args.kwargs["route"].request_model, "b")
                self.assertEqual(call.await_args.kwargs["max_retries"], 0)
            with patch.object(agent, "_call_primary", new_callable=AsyncMock,
                              side_effect=ContentBlockedError("blocked")) as call:
                with self.assertRaises(ContentBlockedError):
                    await agent.call("synthetic")
                self.assertEqual(call.await_count, 1)

    def test_wizard_activates_only_assigned_slots_and_refreshes_runtime_config(self):
        config_fields = (
            "WORKSPACE_DIR", "RAW_DIR", "OUTPUT_DIR", "TRANSLATION_OUTPUT_MODE",
            "GLOSSARY_PATH", "GUIDELINES_PATH", "INFO_PATH", "STORY_SUMMARY_PATH",
            "TM_PATH", "TM_REVIEWED_PATH", "AI_EDITION_ROOT", "CHAPTER_MAP",
            "SOURCE_MANIFEST_PATH", "REQUIRE_REVIEWED_PUBLICATION",
            "TRANSLATION_RUN_ID", "REQUIRE_REVIEWED_STORY_SUMMARY",
            "EXPECTED_BOOK_BUNDLE", "REQUIRE_REVIEWED_CHAPTER_KNOWLEDGE",
            "REQUIRE_REVIEWED_GLOSSARY", "ALLOW_UNREVIEWED_TM",
            "INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL",
            "FINAL_REVIEW_MODEL",
            "JYQF_FALLBACK_ENABLED", "GEMINI_FALLBACK_ENABLED",
            "API_TIMEOUT", "PROVIDER_DATA_POLICY",
        )
        previous_config = {name: getattr(Config, name) for name in config_fields}
        def restore_config():
            for name, value in previous_config.items():
                setattr(Config, name, value)

        self.addCleanup(restore_config)
        answers = iter([
            "main", "https://main.test/v1", "model-a",
            "backup", "https://backup.test/v1", "model-b",
            "unused", "https://unused.test/v1", "model-unused", "",
            "main", "main", "main", "", "backup", "yes", "yes",
            "no",
        ])
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {
                 "TEST_WORKSPACE_DIR": directory,
                 "TRANSLATORAI_POOL_KEY_UNUSED": "stale",
                 "FINAL_REVIEW_MODEL": "pool:stale",
             }, clear=True), \
             patch("builtins.input", side_effect=lambda _: next(answers)), \
             patch("getpass.getpass", side_effect=["secret-a", "secret-b"]) as get_key:
            activate(*configure())
            Config.load_config()
            validate_provider_configuration()
            self.assertEqual(os.environ["INITIAL_MODEL"], "pool:main")
            self.assertEqual(Config.INITIAL_MODEL, "pool:main")
            self.assertEqual(Config.PROOFREAD_MODEL, "pool:main")
            self.assertEqual(Config.STYLE_MODEL, "pool:main")
            self.assertIsNone(Config.FINAL_REVIEW_MODEL)
            self.assertNotIn("FINAL_REVIEW_MODEL", os.environ)
            self.assertEqual(get_primary_provider_route("pool:main").request_model, "model-a")
            self.assertNotIn("secret", os.environ[POOL_ENV])
            self.assertEqual(os.environ["TRANSLATORAI_POOL_FALLBACK"], "pool:backup")
            self.assertNotIn("TRANSLATORAI_POOL_KEY_UNUSED", os.environ)
            self.assertEqual(get_key.call_count, 2)
            self.assertNotIn("unused", json.loads(os.environ[POOL_ENV]))

    def test_optional_reviewer_is_configured_and_receives_full_data_grant(self):
        answers = iter([
            "main", "https://main.test/v1", "translation-model",
            "review", "https://review.test/v1", "review-model", "",
            "main", "main", "main", "review", "",
            "yes", "yes", "no",
        ])
        with patch("builtins.input", side_effect=lambda _: next(answers)), \
             patch("getpass.getpass", side_effect=["translation-key", "review-key"]):
            _, assignments, fallback, grants, keys, embedding = configure()

        self.assertEqual(assignments["FINAL_REVIEW_MODEL"], "review")
        self.assertEqual(fallback, "")
        self.assertEqual(
            grants["pool-review"],
            ["book_knowledge", "source_text", "translation_text"],
        )
        self.assertEqual(set(keys), {"main", "review"})
        self.assertIsNone(embedding)

    def test_wizard_rejects_reviewer_route_shared_with_rework_model(self):
        answers = iter([
            "main", "https://main.test/v1", "translation-model",
            "writer", "https://writer.test/v1", "writer-model", "",
            "main", "writer", "main", "writer",
        ])
        with patch("builtins.input", side_effect=lambda _: next(answers)):
            with self.assertRaisesRegex(ValueError, "校对/返工模型"):
                configure()

    def test_v3_profile_round_trip_and_final_review_preflight(self):
        pool = {
            "translator": {
                "base_url": "https://translation.test/v1",
                "model": "translation-model",
            },
            "reviewer": {
                "base_url": "https://review.test/v1",
                "model": "review-model",
            },
        }
        assignments = {
            "INITIAL_MODEL": "translator",
            "PROOFREAD_MODEL": "translator",
            "STYLE_MODEL": "translator",
            "FINAL_REVIEW_MODEL": "reviewer",
        }
        grants = {
            "pool-translator": [
                "source_text",
                "translation_text",
                "book_knowledge",
            ],
            "pool-reviewer": [
                "source_text",
                "translation_text",
                "book_knowledge",
            ],
        }
        vault = {}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api-pool.json"
            with patch(
                "api_pool_store.write_secret",
                side_effect=lambda ref, value: vault.update({ref: value}),
            ), patch(
                "api_pool_store.read_secret",
                side_effect=lambda ref: vault[ref],
            ):
                save_profile(
                    pool,
                    assignments,
                    "",
                    grants,
                    {"translator": "translation-key", "reviewer": "review-key"},
                    validate_provider_base_url,
                    path=path,
                )
                profile = json.loads(path.read_text(encoding="utf-8"))
                settings = load_profile(validate_provider_base_url, path=path)

            self.assertEqual(profile["version"], 3)
            self.assertEqual(settings[1], assignments)
            self.assertNotIn("review-key", path.read_text(encoding="utf-8"))
            with patch.dict(os.environ, {}, clear=True):
                activate(*settings)
                self.assertEqual(
                    os.environ["FINAL_REVIEW_MODEL"],
                    "pool:reviewer",
                )
                self.assertEqual(
                    json.loads(os.environ["PROVIDER_DATA_POLICY"])["pool-reviewer"],
                    ["book_knowledge", "source_text", "translation_text"],
                )

        runtime_pool = {
            slot: {key: value for key, value in entry.items() if key != "credential_ref"}
            for slot, entry in profile["pool"].items()
        }
        policy = {provider: frozenset(values) for provider, values in grants.items()}
        with patch.dict(
            os.environ,
            {
                POOL_ENV: json.dumps(runtime_pool),
                "TRANSLATORAI_POOL_KEY_REVIEWER": "review-key",
            },
            clear=True,
        ), patch.object(Config, "INITIAL_MODEL", "pool:translator"), \
             patch.object(Config, "FINAL_REVIEW_MODEL", "pool:reviewer"), \
             patch.object(Config, "PROVIDER_DATA_POLICY", policy):
            validate_final_review_provider_configuration()

            with patch.object(
                Config,
                "PROVIDER_DATA_POLICY",
                {"pool-reviewer": frozenset({"source_text", "book_knowledge"})},
            ), self.assertRaises(PermissionError):
                validate_final_review_provider_configuration()

            with patch.object(Config, "INITIAL_MODEL", "pool:reviewer"), \
                 self.assertRaisesRegex(ValueError, "different endpoint"):
                validate_final_review_provider_configuration()

    def test_v3_profile_rejects_same_translator_and_reviewer_route(self):
        pool = {
            "translator": {
                "base_url": "https://same.test/v1",
                "model": "same-model",
            },
            "reviewer": {
                "base_url": "https://same.test:443/v1/",
                "model": "same-model",
            },
        }
        assignments = {
            "INITIAL_MODEL": "translator",
            "PROOFREAD_MODEL": "translator",
            "STYLE_MODEL": "translator",
            "FINAL_REVIEW_MODEL": "reviewer",
        }
        grants = {
            "pool-translator": ["source_text", "translation_text", "book_knowledge"],
            "pool-reviewer": ["source_text", "translation_text", "book_knowledge"],
        }
        with self.assertRaisesRegex(ValueError, "不同的端点和模型"):
            save_profile(
                pool,
                assignments,
                "",
                grants,
                {"translator": "synthetic-key", "reviewer": "synthetic-key"},
                validate_provider_base_url,
                path=Path("unused-profile.json"),
            )

    def test_saved_profile_keeps_secrets_in_credential_store(self):
        pool = {"main": {"base_url": "https://main.test/v1", "model": "model-a"}}
        assignments = {role: "main" for role in ("INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL")}
        grants = {"pool-main": ["source_text", "translation_text", "book_knowledge"]}
        vault = {}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            with patch("api_pool_store.write_secret", side_effect=lambda ref, key: vault.update({ref: key})), \
                 patch("api_pool_store.read_secret", side_effect=lambda ref: vault[ref]):
                save_profile(pool, assignments, "", grants, {"main": "secret-a"},
                             validate_provider_base_url, path=path)
                self.assertNotIn("secret-a", path.read_text(encoding="utf-8"))
                self.assertEqual(load_profile(validate_provider_base_url, path=path),
                                 (pool, assignments, "", grants, {"main": "secret-a"}, None))
                profile = json.loads(path.read_text(encoding="utf-8"))
                profile["pool"]["main"]["base_url"] = "https://other.test/v1"
                path.write_text(json.dumps(profile), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "绑定"):
                    load_profile(validate_provider_base_url, path=path)
                profile["pool"]["main"]["base_url"] = "http://remote.test/v1"
                path.write_text(json.dumps(profile), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_profile(validate_provider_base_url, path=path)

    def test_save_profile_rolls_back_new_secrets_if_credential_write_fails(self):
        pool = {
            "main": {"base_url": "https://main.test/v1", "model": "model-a"},
            "backup": {"base_url": "https://backup.test/v1", "model": "model-b"},
        }
        assignments = {role: "main" for role in ("INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL")}
        grants = {
            "pool-main": ["source_text", "translation_text", "book_knowledge"],
            "pool-backup": ["source_text", "translation_text", "book_knowledge"],
        }
        vault = {}

        def write_secret(ref, secret):
            if vault:
                raise OSError("synthetic credential write failure")
            vault[ref] = secret

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            with patch("api_pool_store.write_secret", side_effect=write_secret), \
                 patch("api_pool_store.delete_secret",
                       side_effect=lambda ref: vault.pop(ref, None)):
                with self.assertRaisesRegex(OSError, "synthetic"):
                    save_profile(pool, assignments, "backup", grants,
                                 {"main": "secret-a", "backup": "secret-b"},
                                 validate_provider_base_url, path=path)
            self.assertEqual(vault, {})
            self.assertFalse(path.exists())

    def test_save_profile_rolls_back_on_profile_replace_failure(self):
        pool = {"main": {"base_url": "https://main.test/v1", "model": "model-a"}}
        assignments = {role: "main" for role in ("INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL")}
        grants = {"pool-main": ["source_text", "translation_text", "book_knowledge"]}
        vault = {}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            path.write_bytes(b"existing-profile")
            with patch("api_pool_store.write_secret",
                       side_effect=lambda ref, secret: vault.update({ref: secret})), \
                 patch("api_pool_store.delete_secret",
                       side_effect=lambda ref: vault.pop(ref, None)), \
                 patch("api_pool_store.os.replace", side_effect=OSError("synthetic replace failure")):
                with self.assertRaisesRegex(OSError, "synthetic"):
                    save_profile(pool, assignments, "", grants, {"main": "secret-a"},
                                 validate_provider_base_url, path=path)
            self.assertEqual(vault, {})
            self.assertEqual(path.read_bytes(), b"existing-profile")
            self.assertEqual(list(Path(directory).glob(".api-pool-*")), [])

    def test_save_profile_reports_failed_credential_cleanup(self):
        pool = {"main": {"base_url": "https://main.test/v1", "model": "model-a"}}
        assignments = {role: "main" for role in ("INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL")}
        grants = {"pool-main": ["source_text", "translation_text", "book_knowledge"]}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            path.write_bytes(b"existing-profile")
            with patch("api_pool_store.write_secret"), \
                 patch("api_pool_store.delete_secret", side_effect=OSError("synthetic delete failure")), \
                 patch("api_pool_store.os.replace", side_effect=OSError("synthetic replace failure")):
                with self.assertRaisesRegex(CredentialStoreError, "未能清理"):
                    save_profile(pool, assignments, "", grants, {"main": "secret-a"},
                                 validate_provider_base_url, path=path)
            self.assertEqual(path.read_bytes(), b"existing-profile")
            self.assertEqual(list(Path(directory).glob(".api-pool-*")), [])

    def test_v2_save_rolls_back_generation_ref_if_embedding_credential_write_fails(self):
        pool = {"main": {"base_url": "https://main.test/v1", "model": "model-a"}}
        assignments = {
            role: "main"
            for role in ("INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL")
        }
        grants = {"pool-main": ["source_text", "translation_text", "book_knowledge"]}
        embedding = {
            "provider": "embedding",
            "protocol": "openai-compatible",
            "base_url": "https://embed.test/v1",
            "model": "embed-model",
            "grants": ["source_text"],
            "api_key": "synthetic-embedding-key",
        }
        vault = {}
        writes = 0

        def write_secret(ref, value):
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("synthetic embedding credential write failure")
            vault[ref] = value

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api-pool.json"
            old_bytes = b"existing-profile"
            path.write_bytes(old_bytes)
            with patch(
                "api_pool_store.write_secret",
                side_effect=write_secret,
            ), patch(
                "api_pool_store.delete_secret",
                side_effect=lambda ref: vault.pop(ref, None),
            ):
                with self.assertRaisesRegex(OSError, "embedding credential write failure"):
                    save_profile(
                        pool,
                        assignments,
                        "",
                        grants,
                        {"main": "synthetic-generation-key"},
                        validate_provider_base_url,
                        embedding=embedding,
                        path=path,
                    )

            self.assertEqual(vault, {})
            self.assertEqual(path.read_bytes(), old_bytes)
            self.assertEqual(list(Path(directory).glob(".api-pool-*")), [])

    def test_v1_migration_keeps_backup_old_credentials_and_equivalent_settings(self):
        vault = {}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api-pool.json"
            old_profile, old_ref, pool, assignments, grants = _write_v1_profile(
                path, vault
            )
            old_bytes = path.read_bytes()
            with patch(
                "api_pool_store.write_secret",
                side_effect=lambda ref, value: vault.update({ref: value}),
            ), patch("api_pool_store.read_secret", side_effect=lambda ref: vault[ref]), patch(
                "api_pool_store.delete_secret",
                side_effect=lambda ref: vault.pop(ref, None),
            ):
                settings, backup_path = migrate_v1_profile(
                    validate_provider_base_url,
                    path=path,
                )
                self.assertEqual(
                    settings,
                    (pool, assignments, "", grants, {"main": "legacy-synthetic-key"}, None),
                )
                self.assertIn(old_ref, vault)
                self.assertEqual(backup_path.read_bytes(), old_bytes)
                migrated = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(migrated["version"], 2)
                self.assertIsNone(migrated["embedding"])
                self.assertNotEqual(
                    migrated["pool"]["main"]["credential_ref"], old_ref
                )
                self.assertEqual(json.loads(backup_path.read_text()) , old_profile)
                self.assertNotIn("legacy-synthetic-key", path.read_text(encoding="utf-8"))
                self.assertNotIn(
                    "legacy-synthetic-key",
                    backup_path.read_text(encoding="utf-8"),
                )
                stored = json.loads(
                    vault[migrated["pool"]["main"]["credential_ref"]]
                )
                from api_pool_store import _profile_digest
                self.assertEqual(stored["profile_sha256"], _profile_digest(migrated))

    def test_v1_migration_replace_failure_preserves_old_profile_and_credentials(self):
        vault = {}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api-pool.json"
            old_profile, old_ref, _, _, _ = _write_v1_profile(path, vault)
            old_bytes = path.read_bytes()
            real_replace = os.replace

            def fail_profile_replace(source, destination):
                if Path(destination) == path:
                    raise OSError("synthetic migration replace failure")
                return real_replace(source, destination)

            with patch(
                "api_pool_store.write_secret",
                side_effect=lambda ref, value: vault.update({ref: value}),
            ), patch("api_pool_store.read_secret", side_effect=lambda ref: vault[ref]), patch(
                "api_pool_store.delete_secret",
                side_effect=lambda ref: vault.pop(ref, None),
            ), patch("api_pool_store.os.replace", side_effect=fail_profile_replace):
                with self.assertRaisesRegex(OSError, "migration replace failure"):
                    migrate_v1_profile(validate_provider_base_url, path=path)

            self.assertEqual(path.read_bytes(), old_bytes)
            self.assertEqual(json.loads(path.read_text()), old_profile)
            self.assertEqual(set(vault), {old_ref})
            backups = list(Path(directory).glob("api-pool.v1-*.backup.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text()), old_profile)

    def test_v2_embedding_profile_round_trip_and_activation(self):
        pool = {"main": {"base_url": "https://main.test/v1", "model": "model-a"}}
        assignments = {
            role: "main"
            for role in ("INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL")
        }
        grants = {"pool-main": ["source_text", "translation_text", "book_knowledge"]}
        embedding = {
            "provider": "embedding",
            "protocol": "openai-compatible",
            "base_url": "https://embed.test/v1",
            "model": "embed-model",
            "grants": ["source_text"],
            "api_key": "synthetic-embedding-key",
        }
        vault = {}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api-pool.json"
            with patch(
                "api_pool_store.write_secret",
                side_effect=lambda ref, value: vault.update({ref: value}),
            ), patch("api_pool_store.read_secret", side_effect=lambda ref: vault[ref]):
                save_profile(
                    pool,
                    assignments,
                    "",
                    grants,
                    {"main": "synthetic-generation-key"},
                    validate_provider_base_url,
                    embedding=embedding,
                    path=path,
                )
                serialized = path.read_text(encoding="utf-8")
                self.assertNotIn("synthetic-generation-key", serialized)
                self.assertNotIn("synthetic-embedding-key", serialized)
                settings = load_profile(validate_provider_base_url, path=path)

            self.assertEqual(settings[5], {
                "provider": "embedding",
                "protocol": "openai-compatible",
                "base_url": "https://embed.test/v1",
                "model": "embed-model",
                "grants": ["source_text"],
                "api_key": "synthetic-embedding-key",
            })
            with patch.dict(os.environ, {}, clear=True):
                activate(*settings)
                runtime = json.loads(os.environ["TRANSLATORAI_EMBEDDING_CONFIG"])
                self.assertNotIn("api_key", runtime)
                self.assertNotIn("synthetic-embedding-key", os.environ["TRANSLATORAI_EMBEDDING_CONFIG"])
                self.assertEqual(
                    json.loads(os.environ["PROVIDER_DATA_POLICY"]),
                    {
                        "pool-main": [
                            "book_knowledge",
                            "source_text",
                            "translation_text",
                        ],
                        "embedding": ["source_text"],
                    },
                )
                self.assertEqual(
                    os.environ["TRANSLATORAI_EMBEDDING_KEY"],
                    "synthetic-embedding-key",
                )

    def test_embedding_wizard_confirms_recipient_before_reading_key(self):
        with patch(
            "builtins.input",
            side_effect=[
                "yes",
                "2",
                "embed_primary",
                "https://embed.test/v1",
                "embed-model",
                "yes",
            ],
        ), patch("getpass.getpass", return_value="synthetic-embedding-key") as get_key:
            embedding = _configure_embedding()

        self.assertEqual(
            embedding,
            {
                "provider": "embed_primary",
                "protocol": "openai-compatible",
                "base_url": "https://embed.test/v1",
                "model": "embed-model",
                "grants": ["source_text"],
                "api_key": "synthetic-embedding-key",
            },
        )
        get_key.assert_called_once()

    def test_embedding_wizard_does_not_read_key_without_authorization(self):
        with patch(
            "builtins.input",
            side_effect=[
                "yes",
                "1",
                "gemini-embedding-2",
                "no",
            ],
        ), patch("getpass.getpass") as get_key:
            with self.assertRaises(PermissionError):
                _configure_embedding()
        get_key.assert_not_called()

    def test_embedding_profile_rejects_generation_pool_provider_collision(self):
        pool = {"main": {"base_url": "https://main.test/v1", "model": "model-a"}}
        assignments = {
            role: "main"
            for role in ("INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL")
        }
        grants = {"pool-main": ["source_text", "translation_text", "book_knowledge"]}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Provider ID"):
                save_profile(
                    pool,
                    assignments,
                    "",
                    grants,
                    {"main": "synthetic-generation-key"},
                    validate_provider_base_url,
                    embedding={
                        "provider": "pool-main",
                        "protocol": "openai-compatible",
                        "base_url": "https://embed.test/v1",
                        "model": "embed-model",
                        "grants": ["source_text"],
                        "api_key": "synthetic-embedding-key",
                    },
                    path=Path(directory) / "api-pool.json",
                )

    def test_api_pool_cli_dispatches_tm_rebuild_mode_after_activation(self):
        with (
            patch("scripts.configure_api_pool.default_profile_path", return_value=None),
            patch("scripts.configure_api_pool.configure", return_value=()),
            patch("scripts.configure_api_pool._ask", return_value="no"),
            patch("scripts.configure_api_pool.activate") as activate_pool,
            patch(
                "scripts.rebuild_tm_embeddings.main",
                return_value=0,
            ) as rebuild,
        ):
            result = configure_api_pool_main(
                [
                    "--rebuild-tm-embeddings",
                    "--",
                    "--project",
                    "synthetic-project",
                ]
            )

        self.assertEqual(result, 0)
        activate_pool.assert_called_once_with()
        rebuild.assert_called_once_with(
            ["--project", "synthetic-project"]
        )

    @unittest.skipUnless(os.name == "nt", "Windows Credential Manager required")
    def test_windows_credential_round_trip_with_synthetic_key(self):
        target = f"TranslatorAI/API/{uuid.uuid4().hex}"
        write_secret(target, "synthetic-test-key")
        try:
            self.assertEqual(read_secret(target), "synthetic-test-key")
        finally:
            delete_secret(target)

    @unittest.skipUnless(os.name == "nt", "Windows Credential Manager required")
    def test_persisted_profile_round_trip_with_windows_store(self):
        import ctypes
        from ctypes import wintypes

        pool = {"main": {"base_url": "https://main.test/v1", "model": "model-a"}}
        assignments = {role: "main" for role in ("INITIAL_MODEL", "PROOFREAD_MODEL", "STYLE_MODEL")}
        grants = {"pool-main": ["source_text", "translation_text", "book_knowledge"]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pool.json"
            save_profile(pool, assignments, "", grants, {"main": "synthetic-test-key"},
                         validate_provider_base_url, path=path)
            target = json.loads(path.read_text(encoding="utf-8"))["pool"]["main"]["credential_ref"]
            try:
                self.assertEqual(load_profile(validate_provider_base_url, path=path)[-1],
                                 None)
                self.assertEqual(load_profile(validate_provider_base_url, path=path)[4],
                                 {"main": "synthetic-test-key"})
                self.assertNotIn("synthetic-test-key", path.read_text(encoding="utf-8"))
            finally:
                advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
                advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
                advapi.CredDeleteW.restype = wintypes.BOOL
                self.assertTrue(advapi.CredDeleteW(target, 1, 0))


if __name__ == "__main__":
    unittest.main()
