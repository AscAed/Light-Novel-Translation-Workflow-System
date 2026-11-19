import argparse
import hashlib
import http.client
import io
import json
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from kakuyomu_page_source import (
    KakuyomuEpisodePage,
    KakuyomuPageAdapter,
    USER_AGENT,
    discover_kakuyomu_work_catalog,
)
from scripts.ingest_kakuyomu_pages import (
    _load_catalog,
    _minimum_delay as _ingest_minimum_delay,
    _record_project_ingestion_freshness,
    main,
)
from scripts.run_kakuyomu_workflow import (
    _minimum_delay as _workflow_minimum_delay,
)
from source_ingestion import (
    CatalogPage,
    EpisodeMetadata,
    FetchedEpisode,
    SourceAccessDenied,
    SourceRateLimited,
    collect_source,
)
from source_manifest import load_manifest


WORK_ID = "1234567890123456789"
EPISODE_ID = "9876543210987654321"
PAGE_URL = (
    f"https://kakuyomu.jp/works/{WORK_ID}/episodes/{EPISODE_ID}"
)
ROBOTS = (
    "User-agent: *\n"
    "Disallow: /works/*/episodes/*/read$\n"
    "Disallow: /login?\n"
)
PAGE_HTML = (
    '<html><div class="widget-episodeTitle">第1話 はじまり</div>'
    '<div class="widget-episodeBody js-episode-body">'
    "<p>太郎は<ruby><rb>東京</rb><rp>(</rp><rt>とうきょう</rt>"
    "<rp>)</rp></ruby>へ行った。</p>"
    '<p id="p2">　次の段落<br>続き。'
    '<em class="emphasisDots"><span>大</span><span>切</span></em></p>'
    "<script>must not enter source</script>"
    "</div></html>"
)
EXPECTED_TEXT = (
    "太郎は｜東京《とうきょう》へ行った。\n\n"
    "　次の段落\n続き。｜大切《・・・》"
)
WORK_URL = f"https://kakuyomu.jp/works/{WORK_ID}"


def make_work_page_html(
    work_id,
    episodes,
    *,
    group_sizes=None,
    public_count=None,
    chapterless_groups=(),
    metadata_overrides=None,
):
    group_sizes = group_sizes or [len(episodes)]
    chapterless_groups = set(chapterless_groups)
    work = {
        "__typename": "Work",
        "id": work_id,
        "title": "Synthetic work",
        "author": {"__ref": "UserAccount:synthetic-author"},
        "catchphrase": "Synthetic catchphrase",
        "introduction": "Synthetic introduction",
        "genre": "Fantasy",
        "tagLabels": ["synthetic", "fixture"],
        "serialStatus": "COMPLETED",
        "publishedAt": "2026-01-01T00:00:00Z",
        "lastEpisodePublishedAt": "2026-01-02T00:00:00Z",
        "publicEpisodeCount": (
            len(episodes) if public_count is None else public_count
        ),
        "tableOfContentsV2": [],
    }
    work.update(metadata_overrides or {})
    state = {
        f"Work:{work_id}": work,
        "UserAccount:synthetic-author": {
            "__typename": "UserAccount",
            "id": "synthetic-author",
            "name": "Synthetic Author",
            "screenName": "synthetic-author",
        }
    }
    episode_index = 0
    for group_index, group_size in enumerate(group_sizes):
        group_id = f"synthetic-group-{group_index}"
        references = []
        for episode_id, title in episodes[
            episode_index : episode_index + group_size
        ]:
            references.append({"__ref": f"Episode:{episode_id}"})
            state[f"Episode:{episode_id}"] = {
                "__typename": "Episode",
                "id": episode_id,
                "title": title,
            }
            episode_index += 1
        state[f"TableOfContentsChapter:{group_id}"] = {
            "__typename": "TableOfContentsChapter",
            "id": group_id,
            "chapter": (
                None
                if group_index in chapterless_groups
                else {"__ref": f"Chapter:synthetic-chapter-{group_index}"}
            ),
            "episodeUnions": references,
        }
        if group_index not in chapterless_groups:
            state[f"Chapter:synthetic-chapter-{group_index}"] = {
                "__typename": "Chapter",
                "id": f"synthetic-chapter-{group_index}",
                "title": f"synthetic section {group_index + 1}",
                "level": group_index,
            }
        state[f"Work:{work_id}"]["tableOfContentsV2"].append(
            {"__ref": f"TableOfContentsChapter:{group_id}"}
        )
    next_data = {"props": {"pageProps": {"__APOLLO_STATE__": state}}}
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data, ensure_ascii=False)
        + "</script></html>"
    )


class FakeResponse(io.BytesIO):
    def __init__(self, payload, url, content_type):
        super().__init__(payload)
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(payload))

    def getcode(self):
        return 200

    def geturl(self):
        return self._url


class TimeoutBodyResponse(FakeResponse):
    def read(self, size=-1):
        raise TimeoutError("synthetic response body timeout")


class IncompleteBodyResponse(FakeResponse):
    def read(self, size=-1):
        raise http.client.IncompleteRead(b"partial response body")


class FakeOpener:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    def open(self, request, timeout):
        url = request.full_url
        self.requests.append((url, timeout, request.get_header("User-agent")))
        response = self.responses.get(url)
        if isinstance(response, Exception):
            raise response
        if response is None:
            raise AssertionError(f"Unexpected request: {url}")
        if isinstance(response, FakeResponse):
            return response
        payload, content_type = response
        return FakeResponse(payload, url, content_type)


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


def make_adapter(
    *,
    robots=ROBOTS,
    page=PAGE_HTML,
    page_content_type="text/html; charset=utf-8",
    episodes=None,
    max_page_bytes=4096,
    max_episode_bytes=4096,
    max_catalog_bytes=8192,
):
    episodes = episodes or (
        KakuyomuEpisodePage(
            EpisodeMetadata(EPISODE_ID, "第1話 はじまり", 1),
            PAGE_URL,
        ),
    )
    responses = {
        "https://kakuyomu.jp/robots.txt": (
            robots.encode("utf-8"),
            "text/plain; charset=utf-8",
        ),
    }
    for item in episodes:
        responses[item.page_url] = (
            page.encode("utf-8") if isinstance(page, str) else page,
            page_content_type,
        )
    opener = FakeOpener(responses)
    clock = FakeClock()
    adapter = KakuyomuPageAdapter(
        WORK_ID,
        episodes,
        page_size=1,
        max_page_bytes=max_page_bytes,
        max_episode_bytes=max_episode_bytes,
        max_catalog_bytes=max_catalog_bytes,
        request_delay_seconds=2,
        opener=opener,
        sleep=clock.sleep,
        clock=clock.now,
    )
    return adapter, opener, clock


class KakuyomuPageAdapterTests(unittest.TestCase):
    def test_incomplete_response_and_timeout_pause_collection_and_can_resume(self):
        for response_type in (TimeoutBodyResponse, IncompleteBodyResponse):
            with self.subTest(response_type=response_type.__name__):
                responses = {
                    "https://kakuyomu.jp/robots.txt": (
                        ROBOTS.encode("utf-8"),
                        "text/plain; charset=utf-8",
                    ),
                    PAGE_URL: response_type(
                        b"", PAGE_URL, "text/html; charset=utf-8"
                    ),
                }
                opener = FakeOpener(responses)
                clock = FakeClock()

                def create_adapter():
                    return KakuyomuPageAdapter(
                        WORK_ID,
                        (
                            KakuyomuEpisodePage(
                                EpisodeMetadata(EPISODE_ID, "第1話 はじまり", 1),
                                PAGE_URL,
                            ),
                        ),
                        opener=opener,
                        sleep=clock.sleep,
                        clock=clock.now,
                    )

                with tempfile.TemporaryDirectory() as temporary:
                    paused = collect_source(
                        create_adapter(),
                        root=temporary,
                        work_id=WORK_ID,
                    )
                    responses[PAGE_URL] = (
                        PAGE_HTML.encode("utf-8"),
                        "text/html; charset=utf-8",
                    )
                    resumed = collect_source(
                        create_adapter(),
                        root=temporary,
                        work_id=WORK_ID,
                    )

                self.assertEqual(paused["status"], "paused")
                self.assertEqual(paused["reason"], "unavailable")
                self.assertEqual(resumed["status"], "complete")
                self.assertEqual(resumed["completed_count"], 1)
                self.assertEqual(
                    [
                        request[0]
                        for request in opener.requests
                        if "/episodes/" in request[0]
                    ],
                    [PAGE_URL, PAGE_URL],
                )

    def test_request_delay_is_bounded_for_adapter_and_both_clis(self):
        for parser in (_ingest_minimum_delay, _workflow_minimum_delay):
            with self.subTest(parser=parser.__module__):
                self.assertEqual(parser("1.5"), 1.5)
                self.assertEqual(parser("2"), 2.0)
                self.assertEqual(parser("3"), 3.0)
                for value in ("1.49", "3.01", "nan", "inf"):
                    with self.subTest(value=value):
                        with self.assertRaises(argparse.ArgumentTypeError):
                            parser(value)

        for value in (1.49, 3.01, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "between 1.5 and 3"):
                    KakuyomuPageAdapter(
                        WORK_ID,
                        (
                            KakuyomuEpisodePage(
                                EpisodeMetadata(EPISODE_ID, "第1話 はじまり", 1),
                                PAGE_URL,
                            ),
                        ),
                        request_delay_seconds=value,
                        opener=FakeOpener({}),
                    )

    def test_fetches_only_explicit_pages_and_extracts_visible_text(self):
        adapter, opener, clock = make_adapter()

        self.assertEqual(
            [request[0] for request in opener.requests],
            ["https://kakuyomu.jp/robots.txt"],
        )
        fetched = adapter.fetch_episode(EPISODE_ID)
        self.assertIsInstance(fetched, FetchedEpisode)
        self.assertEqual(fetched.content, EXPECTED_TEXT.encode("utf-8"))
        self.assertEqual(fetched.page_html, PAGE_HTML.encode("utf-8"))
        self.assertEqual(fetched.metadata.title, "第1話 はじまり")
        self.assertEqual(
            [request[0] for request in opener.requests],
            ["https://kakuyomu.jp/robots.txt", PAGE_URL],
        )
        self.assertTrue(all(request[2] == USER_AGENT for request in opener.requests))
        self.assertEqual(clock.sleeps, [2])
        self.assertEqual(adapter.source_fingerprint, hashlib.sha256(
            json.dumps(
                {
                    "adapter": "kakuyomu-visible-text-v4",
                    "work_id": WORK_ID,
                    "robots_sha256": hashlib.sha256(ROBOTS.encode("utf-8")).hexdigest(),
                    "work_catalog_fingerprint": None,
                    "episodes": [
                        {
                            "episode_id": EPISODE_ID,
                            "title": "第1話 はじまり",
                            "position": 1,
                            "page_url": PAGE_URL,
                        }
                    ],
                    "limits": {
                        "max_page_bytes": 4096,
                        "max_episode_bytes": 4096,
                        "max_catalog_bytes": 8192,
                        "max_episodes": 1000,
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest())
        first_page = adapter.list_episodes(None)
        self.assertEqual(first_page, CatalogPage((first_page.episodes[0],), None))

    def test_accepts_either_episode_body_class_and_preserves_fullwidth_indent(self):
        widget_only = PAGE_HTML.replace(
            'class="widget-episodeBody js-episode-body"',
            'class="widget-episodeBody"',
        )
        adapter, _, _ = make_adapter(page=widget_only)

        fetched = adapter.fetch_episode(EPISODE_ID)

        self.assertEqual(fetched.content, EXPECTED_TEXT.encode("utf-8"))
        self.assertTrue(fetched.content.startswith("太郎は｜東京".encode("utf-8")))
        self.assertIn("　次の段落".encode("utf-8"), fetched.content)

    def test_preserves_nbsp_entity_and_fullwidth_space(self):
        page = (
            '<div class="widget-episodeTitle">第1話 はじまり</div>'
            '<div class="widget-episodeBody">'
            "<p>A&nbsp;B</p><p>&#x3000;次の段落</p></div>"
        )
        adapter, _, _ = make_adapter(page=page)

        fetched = adapter.fetch_episode(EPISODE_ID)

        self.assertEqual(
            fetched.content,
            "A\u00a0B\n\n\u3000次の段落".encode("utf-8"),
        )

    def test_preserves_paragraph_id_and_initial_fullwidth_indent(self):
        page = (
            '<div class="widget-episodeTitle">第1話 はじまり</div>'
            '<div class="widget-episodeBody">'
            '<p id="p1">&#x3000;冒頭。</p></div>'
        )
        adapter, _, _ = make_adapter(page=page)

        fetched = adapter.fetch_episode(EPISODE_ID)

        self.assertEqual(fetched.content, "\u3000冒頭。".encode("utf-8"))

    def test_robots_denial_stops_before_requesting_episode_page(self):
        adapter_episodes = (
            KakuyomuEpisodePage(
                EpisodeMetadata(EPISODE_ID, "第1話 はじまり", 1),
                PAGE_URL,
            ),
        )
        opener = FakeOpener(
            {
                "https://kakuyomu.jp/robots.txt": (
                    b"User-agent: *\nDisallow: /works/1234567890123456789/\n",
                    "text/plain; charset=utf-8",
                )
            }
        )

        with self.assertRaises(SourceAccessDenied):
            KakuyomuPageAdapter(
                WORK_ID,
                adapter_episodes,
                opener=opener,
                sleep=lambda _: None,
                clock=lambda: 0,
            )

        self.assertEqual(
            [request[0] for request in opener.requests],
            ["https://kakuyomu.jp/robots.txt"],
        )

    def test_decodes_and_retains_declared_non_utf8_page_charset(self):
        page_bytes = PAGE_HTML.encode("shift_jis")
        adapter, _, _ = make_adapter(
            page=page_bytes,
            page_content_type='text/html; charset="Shift_JIS"',
        )

        fetched = adapter.fetch_episode(EPISODE_ID)

        self.assertEqual(fetched.content, EXPECTED_TEXT.encode("utf-8"))
        self.assertEqual(fetched.page_html, page_bytes)
        self.assertEqual(fetched.page_charset, "shift_jis")

    def test_empty_robots_response_fails_closed(self):
        opener = FakeOpener(
            {
                "https://kakuyomu.jp/robots.txt": (
                    b"",
                    "text/plain; charset=utf-8",
                )
            }
        )
        with self.assertRaises(SourceAccessDenied):
            KakuyomuPageAdapter(
                WORK_ID,
                (
                    KakuyomuEpisodePage(
                        EpisodeMetadata(EPISODE_ID, "", 1),
                        PAGE_URL,
                    ),
                ),
                opener=opener,
                sleep=lambda _: None,
                clock=lambda: 0,
            )
        self.assertEqual(len(opener.requests), 1)

    def test_rejects_read_route_and_mismatched_identity_before_network(self):
        invalid_urls = (
            PAGE_URL + "/read",
            PAGE_URL + "?page=2",
            PAGE_URL.replace("kakuyomu.jp", "example.com"),
            PAGE_URL.replace(EPISODE_ID, "1111111111111111111"),
        )
        for page_url in invalid_urls:
            with self.subTest(page_url=page_url):
                opener = FakeOpener({})
                with self.assertRaises(ValueError):
                    KakuyomuPageAdapter(
                        WORK_ID,
                        (
                            KakuyomuEpisodePage(
                                EpisodeMetadata(
                                    EPISODE_ID,
                                    "第1話 はじまり",
                                    1,
                                ),
                                page_url,
                            ),
                        ),
                        opener=opener,
                    )
                self.assertEqual(opener.requests, [])

    def test_rejects_title_or_body_mismatch(self):
        wrong_title = PAGE_HTML.replace("第1話 はじまり", "別の話")
        adapter, _, _ = make_adapter(page=wrong_title)
        with self.assertRaisesRegex(ValueError, "title does not match"):
            adapter.fetch_episode(EPISODE_ID)

        missing_body = PAGE_HTML.replace(
            'class="widget-episodeBody js-episode-body"',
            'class="episode-body-missing"',
        )
        adapter, _, _ = make_adapter(page=missing_body)
        with self.assertRaisesRegex(ValueError, "missing its unique"):
            adapter.fetch_episode(EPISODE_ID)

    def test_rejects_page_and_extracted_text_over_limits(self):
        adapter, _, _ = make_adapter(max_page_bytes=30)
        with self.assertRaisesRegex(ValueError, "response exceeds"):
            adapter.fetch_episode(EPISODE_ID)

        adapter, _, _ = make_adapter(max_episode_bytes=8)
        with self.assertRaisesRegex(ValueError, "episode exceeds"):
            adapter.fetch_episode(EPISODE_ID)

    def test_reads_title_from_page_when_catalog_omits_title(self):
        adapter, _, _ = make_adapter(
            episodes=(
                KakuyomuEpisodePage(
                    EpisodeMetadata(EPISODE_ID, "", 1),
                    PAGE_URL,
                ),
            )
        )

        self.assertEqual(adapter.list_episodes(None).episodes[0].title, "")
        fetched = adapter.fetch_episode(EPISODE_ID)
        self.assertEqual(fetched.metadata.title, "第1話 はじまり")

    def test_rate_limit_and_redirect_errors_stop_without_fallback(self):
        episode = KakuyomuEpisodePage(
            EpisodeMetadata(EPISODE_ID, "第1話 はじまり", 1),
            PAGE_URL,
        )
        for status, expected in (
            (429, SourceRateLimited),
            (302, SourceAccessDenied),
        ):
            with self.subTest(status=status):
                error = urllib.error.HTTPError(
                    PAGE_URL,
                    status,
                    "synthetic response",
                    Message(),
                    None,
                )
                opener = FakeOpener(
                    {
                        "https://kakuyomu.jp/robots.txt": (
                            ROBOTS.encode("utf-8"),
                            "text/plain; charset=utf-8",
                        ),
                        PAGE_URL: error,
                    }
                )
                adapter = KakuyomuPageAdapter(
                        WORK_ID,
                        (episode,),
                        opener=opener,
                        sleep=lambda _: None,
                        clock=lambda: 0,
                    )
                with self.assertRaises(expected):
                    adapter.fetch_episode(EPISODE_ID)
                self.assertEqual(
                    [request[0] for request in opener.requests],
                    ["https://kakuyomu.jp/robots.txt", PAGE_URL],
                )

    def test_catalog_limit_includes_previously_completed_episodes_on_resume(self):
        episodes = (
            KakuyomuEpisodePage(
                EpisodeMetadata("1111111111111111111", "第1話 はじまり", 1),
                f"https://kakuyomu.jp/works/{WORK_ID}/episodes/1111111111111111111",
            ),
            KakuyomuEpisodePage(
                EpisodeMetadata("2222222222222222222", "第2話 はじまり", 2),
                f"https://kakuyomu.jp/works/{WORK_ID}/episodes/2222222222222222222",
            ),
        )
        unavailable = urllib.error.HTTPError(
            episodes[1].page_url,
            503,
            "temporary failure",
            Message(),
            None,
        )
        responses = {
            "https://kakuyomu.jp/robots.txt": (
                ROBOTS.encode("utf-8"),
                "text/plain; charset=utf-8",
            ),
            episodes[0].page_url: (
                PAGE_HTML.encode("utf-8"),
                "text/html; charset=utf-8",
            ),
            episodes[1].page_url: unavailable,
        }
        opener = FakeOpener(responses)
        clock = FakeClock()
        limit = len(EXPECTED_TEXT.encode("utf-8")) + 1

        def create_adapter():
            return KakuyomuPageAdapter(
                WORK_ID,
                episodes,
                max_catalog_bytes=limit,
                opener=opener,
                sleep=clock.sleep,
                clock=clock.now,
            )

        with tempfile.TemporaryDirectory() as temporary:
            first_report = collect_source(
                create_adapter(),
                root=temporary,
                work_id=WORK_ID,
            )
            responses[episodes[1].page_url] = (
                PAGE_HTML.replace("第1話", "第2話").encode("utf-8"),
                "text/html; charset=utf-8",
            )
            final_report = collect_source(
                create_adapter(),
                root=temporary,
                work_id=WORK_ID,
            )

        requested_pages = [
            request[0]
            for request in opener.requests
            if "/episodes/" in request[0]
        ]
        self.assertEqual(first_report["status"], "paused")
        self.assertEqual(first_report["reason"], "unavailable")
        self.assertEqual(final_report["status"], "paused")
        self.assertEqual(final_report["reason"], "archive_limit")
        self.assertEqual(final_report["completed_count"], 1)
        self.assertEqual(
            requested_pages,
            [episodes[0].page_url, episodes[1].page_url, episodes[1].page_url],
        )

    def test_failed_episode_resumes_without_refetching_completed_pages(self):
        episodes = (
            KakuyomuEpisodePage(
                EpisodeMetadata("1111111111111111111", "第1話 はじまり", 1),
                f"https://kakuyomu.jp/works/{WORK_ID}/episodes/1111111111111111111",
            ),
            KakuyomuEpisodePage(
                EpisodeMetadata("2222222222222222222", "第2話 はじまり", 2),
                f"https://kakuyomu.jp/works/{WORK_ID}/episodes/2222222222222222222",
            ),
            KakuyomuEpisodePage(
                EpisodeMetadata("3333333333333333333", "第3話 はじまり", 3),
                f"https://kakuyomu.jp/works/{WORK_ID}/episodes/3333333333333333333",
            ),
        )
        unavailable = urllib.error.HTTPError(
            episodes[1].page_url,
            503,
            "temporary failure",
            Message(),
            None,
        )
        responses = {
            "https://kakuyomu.jp/robots.txt": (
                ROBOTS.encode("utf-8"),
                "text/plain; charset=utf-8",
            ),
            episodes[0].page_url: (
                PAGE_HTML.encode("utf-8"),
                "text/html; charset=utf-8",
            ),
            episodes[1].page_url: unavailable,
            episodes[2].page_url: (
                PAGE_HTML.replace("第1話", "第3話").encode("utf-8"),
                "text/html; charset=utf-8",
            ),
        }
        opener = FakeOpener(responses)
        clock = FakeClock()

        def create_adapter():
            return KakuyomuPageAdapter(
                WORK_ID,
                episodes,
                opener=opener,
                sleep=clock.sleep,
                clock=clock.now,
            )

        with tempfile.TemporaryDirectory() as temporary:
            first_adapter = create_adapter()
            first_fingerprint = first_adapter.source_fingerprint
            first_report = collect_source(
                first_adapter,
                root=temporary,
                work_id=WORK_ID,
            )
            responses[episodes[1].page_url] = (
                PAGE_HTML.replace("第1話", "第2話").encode("utf-8"),
                "text/html; charset=utf-8",
            )
            retry_adapter = create_adapter()
            self.assertEqual(retry_adapter.source_fingerprint, first_fingerprint)
            final_report = collect_source(
                retry_adapter,
                root=temporary,
                work_id=WORK_ID,
            )

        requested_pages = [
            request[0]
            for request in opener.requests
            if "/episodes/" in request[0]
        ]
        self.assertEqual(first_report["status"], "paused")
        self.assertEqual(first_report["completed_count"], 1)
        self.assertEqual(final_report["status"], "complete")
        self.assertEqual(
            requested_pages,
            [
                episodes[0].page_url,
                episodes[1].page_url,
                episodes[1].page_url,
                episodes[2].page_url,
            ],
        )

    def test_collects_snapshot_through_existing_manifest_core(self):
        adapter, _, _ = make_adapter()
        with tempfile.TemporaryDirectory() as temporary:
            report = collect_source(
                adapter,
                root=temporary,
                work_id=WORK_ID,
            )
            manifest = load_manifest(Path(temporary) / "source_manifest.json")

            self.assertEqual(report["status"], "complete")
            raw_artifact = next(
                artifact
                for artifact in manifest["artifacts"]
                if artifact["kind"] == "raw_source"
            )
            self.assertEqual(
                (Path(temporary) / raw_artifact["relative_path"]).read_bytes(),
                EXPECTED_TEXT.encode("utf-8"),
            )
            self.assertEqual(
                raw_artifact["content_sha256"],
                hashlib.sha256(EXPECTED_TEXT.encode("utf-8")).hexdigest(),
            )


class KakuyomuWorkCatalogDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.episode_rows = (
            ("1111111111111111111", "第1話 はじまり"),
            ("2222222222222222222", "第2話 はじまり"),
            ("3333333333333333333", "第3話 はじまり"),
        )
        self.work_html = make_work_page_html(
            WORK_ID,
            self.episode_rows,
            group_sizes=[2, 1],
        )
        self.responses = {
            "https://kakuyomu.jp/robots.txt": (
                ROBOTS.encode("utf-8"),
                "text/plain; charset=utf-8",
            ),
            WORK_URL: (
                self.work_html.encode("utf-8"),
                "text/html; charset=utf-8",
            ),
        }
        for episode_id, title in self.episode_rows:
            page_url = f"https://kakuyomu.jp/works/{WORK_ID}/episodes/{episode_id}"
            self.responses[page_url] = (
                PAGE_HTML.replace("第1話 はじまり", title).encode("utf-8"),
                "text/html; charset=utf-8",
            )
        self.opener = FakeOpener(self.responses)
        self.clock = FakeClock()

    def _discover(self, **options):
        return discover_kakuyomu_work_catalog(
            WORK_URL,
            opener=self.opener,
            sleep=self.clock.sleep,
            clock=self.clock.now,
            **options,
        )

    def test_discovers_all_groups_then_fetches_every_episode_in_order(self):
        discovered = self._discover()

        self.assertEqual(
            [item.metadata.episode_id for item in discovered.episodes],
            [item[0] for item in self.episode_rows],
        )
        self.assertEqual(
            [item.metadata.position for item in discovered.episodes],
            [1, 2, 3],
        )
        self.assertEqual(
            discovered.work_metadata.to_catalog_record(),
            {
                "source_url": WORK_URL,
                "title": "Synthetic work",
                "author_name": "Synthetic Author",
                "author_screen_name": "synthetic-author",
                "catchphrase": "Synthetic catchphrase",
                "introduction": "Synthetic introduction",
                "genre": "Fantasy",
                "tags": ["synthetic", "fixture"],
                "serial_status": "COMPLETED",
                "published_at": "2026-01-01T00:00:00Z",
                "last_episode_published_at": "2026-01-02T00:00:00Z",
                "public_episode_count": 3,
            },
        )
        self.assertEqual(
            [
                (
                    group.group_id,
                    group.chapter_id,
                    group.title,
                    group.level,
                    group.position_start,
                    group.position_end,
                    group.episode_ids,
                )
                for group in discovered.chapters
            ],
            [
                (
                    "synthetic-group-0",
                    "synthetic-chapter-0",
                    "synthetic section 1",
                    0,
                    1,
                    2,
                    ("1111111111111111111", "2222222222222222222"),
                ),
                (
                    "synthetic-group-1",
                    "synthetic-chapter-1",
                    "synthetic section 2",
                    1,
                    3,
                    3,
                    ("3333333333333333333",),
                ),
            ],
        )
        self.assertEqual(
            [request[0] for request in self.opener.requests],
            ["https://kakuyomu.jp/robots.txt", WORK_URL],
        )

        adapter = discovered.create_page_adapter(page_size=2)
        self.assertTrue(
            all(
                adapter.fetch_episode(item.metadata.episode_id).content
                == EXPECTED_TEXT.encode("utf-8")
                for item in discovered.episodes
            )
        )
        self.assertEqual(
            [request[0] for request in self.opener.requests],
            [
                "https://kakuyomu.jp/robots.txt",
                WORK_URL,
                *[f"https://kakuyomu.jp/works/{WORK_ID}/episodes/{row[0]}"
                  for row in self.episode_rows],
            ],
        )
        self.assertEqual(self.clock.sleeps, [2, 2, 2, 2])
        self.assertEqual(len(discovered.source_fingerprint), 64)

    def test_catalog_count_mismatch_stops_before_episode_requests(self):
        self.responses[WORK_URL] = (
            make_work_page_html(
                WORK_ID,
                self.episode_rows,
                group_sizes=[3],
                public_count=4,
            ).encode("utf-8"),
            "text/html; charset=utf-8",
        )

        with self.assertRaisesRegex(ValueError, "does not match"):
            self._discover()

        self.assertEqual(
            [request[0] for request in self.opener.requests],
            ["https://kakuyomu.jp/robots.txt", WORK_URL],
        )

    def test_metadata_only_change_does_not_change_episode_source_fingerprint(self):
        first = self._discover()
        self.responses[WORK_URL] = (
            make_work_page_html(
                WORK_ID,
                self.episode_rows,
                group_sizes=[2, 1],
                metadata_overrides={"introduction": "Revised introduction"},
            ).encode("utf-8"),
            "text/html; charset=utf-8",
        )

        current = self._discover()

        self.assertNotEqual(
            first.work_metadata.introduction,
            current.work_metadata.introduction,
        )
        self.assertEqual(first.source_fingerprint, current.source_fingerprint)

    def test_discovers_empty_and_chapterless_groups(self):
        html = make_work_page_html(
            WORK_ID,
            [self.episode_rows[0]],
            group_sizes=[0, 1],
            chapterless_groups=[1],
        )
        self.responses[WORK_URL] = (
            html.encode("utf-8"),
            "text/html; charset=utf-8",
        )

        discovered = self._discover()

        self.assertEqual(len(discovered.episodes), 1)
        self.assertEqual(
            [
                (
                    group.chapter_id,
                    group.title,
                    group.position_start,
                    group.position_end,
                    group.episode_ids,
                )
                for group in discovered.chapters
            ],
            [
                (
                    "synthetic-chapter-0",
                    "synthetic section 1",
                    None,
                    None,
                    (),
                ),
                (None, None, 1, 1, ("1111111111111111111",)),
            ],
        )

    def test_missing_chapter_reference_target_fails_closed(self):
        malformed = self.work_html.replace(
            "Chapter:synthetic-chapter-0",
            "Chapter:missing-chapter",
            1,
        )
        self.responses[WORK_URL] = (
            malformed.encode("utf-8"),
            "text/html; charset=utf-8",
        )

        with self.assertRaisesRegex(ValueError, "missing entity"):
            self._discover()

    def test_work_page_robots_denial_stops_before_homepage_request(self):
        self.responses["https://kakuyomu.jp/robots.txt"] = (
            f"User-agent: *\nDisallow: /works/{WORK_ID}\n".encode("utf-8"),
            "text/plain; charset=utf-8",
        )

        with self.assertRaises(SourceAccessDenied):
            self._discover()

        self.assertEqual(
            [request[0] for request in self.opener.requests],
            ["https://kakuyomu.jp/robots.txt"],
        )

    def test_max_episode_limit_stops_before_episode_requests(self):
        with self.assertRaisesRegex(ValueError, "episode limit"):
            self._discover(max_episodes=2)

        self.assertEqual(
            [request[0] for request in self.opener.requests],
            ["https://kakuyomu.jp/robots.txt", WORK_URL],
        )


class KakuyomuIngestionCLITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source_root = self.root / "input"
        self.output_root = self.root / "output"
        self.source_root.mkdir()
        self.output_root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def _write_catalog(self):
        catalog = {
            "schema_version": 1,
            "work_id": WORK_ID,
            "episodes": [
                {
                    "episode_id": EPISODE_ID,
                    "position": 1,
                    "page_url": PAGE_URL,
                }
            ],
        }
        (self.source_root / "catalog.json").write_text(
            json.dumps(catalog, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_cli_archives_explicit_catalog_and_never_echoes_episode_text(self):
        self._write_catalog()
        adapter, _, _ = make_adapter()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch(
            "scripts.ingest_kakuyomu_pages.KakuyomuPageAdapter",
            return_value=adapter,
        ), patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            result = main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    "catalog.json",
                    "--output-root",
                    str(self.output_root),
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("太郎", stdout.getvalue())
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["completed_count"], 1)

    def test_project_mode_records_source_and_ai_edition_freshness(self):
        projects_root = self.root / "projects"
        project_root = projects_root / "synthetic"
        source_root = project_root / "SourceArchive"
        translation_root = project_root / "熟肉"
        source_root.mkdir(parents=True)
        translation_root.mkdir()
        catalog = {
            "schema_version": 1,
            "work_id": WORK_ID,
            "episodes": [
                {
                    "episode_id": EPISODE_ID,
                    "position": 1,
                    "page_url": PAGE_URL,
                }
            ],
        }
        (source_root / "catalog.json").write_text(
            json.dumps(catalog, ensure_ascii=False),
            encoding="utf-8",
        )
        adapter, _, _ = make_adapter()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch(
                "scripts.ingest_kakuyomu_pages._PROJECTS_ROOT",
                projects_root,
            ),
            patch(
                "scripts.ingest_kakuyomu_pages.KakuyomuPageAdapter",
                return_value=adapter,
            ),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            result = main(
                [
                    "--project",
                    "synthetic",
                    "--source-root",
                    str(source_root),
                    "--catalog",
                    "catalog.json",
                    "--output-root",
                    str(source_root),
                ]
            )

        report = json.loads(stdout.getvalue())
        freshness = report["project_freshness_snapshot"]
        snapshot_path = source_root / freshness["path"]
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("太郎", stdout.getvalue())
        self.assertEqual(report["status"], "complete")
        self.assertEqual(freshness["status"], "persisted")
        self.assertEqual(
            freshness["consumers"]["ai_edition_index"]["unverified"],
            1,
        )
        self.assertTrue((source_root / "source_editions_manifest.json").is_file())
        self.assertEqual(
            snapshot["consumers"]["ai_edition_index"]["findings"][0]["status"],
            "unverified",
        )
        self.assertEqual(
            snapshot["source_manifest"]["relative_path"],
            "source_editions_manifest.json",
        )

    def test_project_freshness_passes_ai_source_map_to_downstream_audit(self):
        source_root = self.root / "freshness-source"
        ai_root = self.root / "freshness-ai"
        translation_root = self.root / "freshness-translation"
        source_root.mkdir()
        ai_root.mkdir()
        translation_root.mkdir()
        summary_path = source_root / "STORY_SUMMARY_reviewed.json"
        summary_path.write_text("{}", encoding="utf-8")
        context = {
            "source_root": source_root,
            "ai_root": ai_root,
            "translation_root": translation_root,
            "tm_path": source_root / "translation_memory.json",
            "knowledge_path": source_root / "KNOWLEDGE_PROVENANCE.json",
            "story_summary_path": summary_path,
        }
        expected_sources = [
            {
                "filename": "editions/ai-v1/episode.md",
                "source_version_id": "ai-version-1",
                "source_input_file": "chapters/episode.md",
                "source_sha256": "a" * 64,
            }
        ]
        snapshot = {"consumers": {}}

        with (
            patch(
                "source_editions.synchronize_edition_manifest_with_source_history",
                return_value={"status": "unchanged"},
            ),
            patch(
                "scripts.ingest_kakuyomu_pages._ai_edition_index_freshness",
                return_value=(
                    {
                        "identity": "ai_edition_index",
                        "status": "verified",
                        "detail": "verified fixture",
                    },
                    expected_sources,
                ),
            ),
            patch(
                "scripts.snapshot_downstream_freshness.build_downstream_freshness_snapshot",
                return_value=snapshot,
            ) as build_snapshot,
            patch(
                "scripts.snapshot_downstream_freshness.persist_downstream_freshness_snapshot",
                return_value={
                    "path": "Workflow/Freshness/test.json",
                    "snapshot_id": "snapshot",
                    "created": True,
                },
            ),
        ):
            _record_project_ingestion_freshness(
                context=context,
                catalog_relative_path="catalog.json",
                manifest_relative_path="source_manifest.json",
            )

        kwargs = build_snapshot.call_args.kwargs
        self.assertEqual(kwargs["source_input_root"], str(ai_root))
        self.assertEqual(
            kwargs["source_input_map"],
            {
                "editions/ai-v1/episode.md": {
                    "source_version_id": "ai-version-1",
                    "source_input_file": "chapters/episode.md",
                    "source_sha256": "a" * 64,
                }
            },
        )
        self.assertEqual(kwargs["expected_sources"], expected_sources)

    def test_project_mode_rejects_roots_outside_project_archive_before_fetch(self):
        projects_root = self.root / "projects"
        source_root = projects_root / "synthetic" / "SourceArchive"
        source_root.mkdir(parents=True)
        with (
            patch(
                "scripts.ingest_kakuyomu_pages._PROJECTS_ROOT",
                projects_root,
            ),
            patch(
                "scripts.ingest_kakuyomu_pages.KakuyomuPageAdapter"
            ) as adapter_class,
            patch("sys.stderr", io.StringIO()) as stderr,
        ):
            result = main(
                [
                    "--project",
                    "synthetic",
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    "catalog.json",
                    "--output-root",
                    str(self.output_root),
                ]
            )

        self.assertEqual(result, 1)
        self.assertIn("ERROR: ValueError", stderr.getvalue())
        adapter_class.assert_not_called()

    def test_cli_discovers_homepage_catalog_and_archives_all_listed_pages(self):
        work_html = make_work_page_html(
            WORK_ID,
            [(EPISODE_ID, "第1話 はじまり")],
        )
        opener = FakeOpener(
            {
                "https://kakuyomu.jp/robots.txt": (
                    ROBOTS.encode("utf-8"),
                    "text/plain; charset=utf-8",
                ),
                WORK_URL: (
                    work_html.encode("utf-8"),
                    "text/html; charset=utf-8",
                ),
                PAGE_URL: (
                    PAGE_HTML.encode("utf-8"),
                    "text/html; charset=utf-8",
                ),
            }
        )
        clock = FakeClock()
        stdout = io.StringIO()
        stderr = io.StringIO()

        def discover_test_work(work_url, **options):
            return discover_kakuyomu_work_catalog(
                work_url,
                opener=opener,
                sleep=clock.sleep,
                clock=clock.now,
                **options,
            )

        with (
            patch(
                "scripts.ingest_kakuyomu_pages.discover_kakuyomu_work_catalog",
                side_effect=discover_test_work,
            ),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            result = main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--work-url",
                    WORK_URL,
                    "--discovered-catalog",
                    "discovered.json",
                    "--output-root",
                    str(self.output_root),
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["discovered_catalog"], "discovered.json")
        self.assertNotIn("太郎", stdout.getvalue())
        discovered = json.loads(
            (self.source_root / "discovered.json").read_text(encoding="utf-8")
        )
        manifest = load_manifest(self.output_root / "source_manifest.json")
        work_artifacts = [
            artifact
            for artifact in manifest["artifacts"]
            if artifact["kind"] == "work"
        ]
        self.assertEqual(len(work_artifacts), 1)
        work_record = json.loads(
            (self.output_root / work_artifacts[0]["relative_path"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(work_record["metadata"], discovered["work_metadata"])
        html_artifacts = [
            artifact
            for artifact in manifest["artifacts"]
            if artifact["kind"] == "raw_page_html"
        ]
        raw_artifact = next(
            artifact
            for artifact in manifest["artifacts"]
            if artifact["kind"] == "raw_source"
        )
        self.assertEqual(len(html_artifacts), 1)
        self.assertEqual(
            (self.output_root / html_artifacts[0]["relative_path"]).read_bytes(),
            PAGE_HTML.encode("utf-8"),
        )
        self.assertIn(
            raw_artifact["version_id"],
            html_artifacts[0]["parent_version_ids"],
        )
        self.assertEqual(discovered["schema_version"], 3)
        self.assertEqual(
            discovered["work_metadata"],
            {
                "source_url": WORK_URL,
                "title": "Synthetic work",
                "author_name": "Synthetic Author",
                "author_screen_name": "synthetic-author",
                "catchphrase": "Synthetic catchphrase",
                "introduction": "Synthetic introduction",
                "genre": "Fantasy",
                "tags": ["synthetic", "fixture"],
                "serial_status": "COMPLETED",
                "published_at": "2026-01-01T00:00:00Z",
                "last_episode_published_at": "2026-01-02T00:00:00Z",
                "public_episode_count": 1,
            },
        )
        self.assertEqual(discovered["episodes"][0]["page_url"], PAGE_URL)
        self.assertEqual(
            discovered["chapters"],
            [
                {
                    "group_id": "synthetic-group-0",
                    "chapter_id": "synthetic-chapter-0",
                    "title": "synthetic section 1",
                    "level": 0,
                    "position_start": 1,
                    "position_end": 1,
                    "episode_ids": [EPISODE_ID],
                }
            ],
        )
        loaded_work_id, loaded_episodes, _ = _load_catalog(
            str(self.source_root), "discovered.json"
        )
        self.assertEqual(loaded_work_id, WORK_ID)
        self.assertEqual(
            [item.metadata.episode_id for item in loaded_episodes],
            [EPISODE_ID],
        )
        self.assertEqual(
            [request[0] for request in opener.requests],
            ["https://kakuyomu.jp/robots.txt", WORK_URL, PAGE_URL],
        )
        self.assertEqual(clock.sleeps, [2, 2])

    def test_cli_append_only_update_fetches_only_new_episode(self):
        first = (EPISODE_ID, "第1話 はじまり")
        second_id = "1111111111111111111"
        second_url = f"https://kakuyomu.jp/works/{WORK_ID}/episodes/{second_id}"
        baseline_opener = FakeOpener(
            {
                "https://kakuyomu.jp/robots.txt": (
                    ROBOTS.encode("utf-8"),
                    "text/plain; charset=utf-8",
                ),
                WORK_URL: (
                    make_work_page_html(WORK_ID, [first]).encode("utf-8"),
                    "text/html; charset=utf-8",
                ),
                PAGE_URL: (
                    PAGE_HTML.encode("utf-8"),
                    "text/html; charset=utf-8",
                ),
            }
        )
        baseline_stdout = io.StringIO()

        def run_discovery(opener, arguments, stdout):
            clock = FakeClock()
            stderr = io.StringIO()

            def discover_test_work(work_url, **options):
                return discover_kakuyomu_work_catalog(
                    work_url,
                    opener=opener,
                    sleep=clock.sleep,
                    clock=clock.now,
                    **options,
                )

            with (
                patch(
                    "scripts.ingest_kakuyomu_pages."
                    "discover_kakuyomu_work_catalog",
                    side_effect=discover_test_work,
                ),
                patch("sys.stdout", stdout),
                patch("sys.stderr", stderr),
            ):
                result = main(arguments)
            return result, stderr.getvalue()

        baseline_result, baseline_stderr = run_discovery(
            baseline_opener,
            [
                "--source-root",
                str(self.source_root),
                "--work-url",
                WORK_URL,
                "--discovered-catalog",
                "catalog.v1.json",
                "--output-root",
                str(self.output_root),
                "--checkpoint",
                "checkpoint.v1.json",
            ],
            baseline_stdout,
        )
        self.assertEqual(baseline_result, 0)
        self.assertEqual(baseline_stderr, "")

        current_opener = FakeOpener(
            {
                "https://kakuyomu.jp/robots.txt": (
                    ROBOTS.encode("utf-8"),
                    "text/plain; charset=utf-8",
                ),
                WORK_URL: (
                    make_work_page_html(WORK_ID, [first, (second_id, "第2話 続き")])
                    .encode("utf-8"),
                    "text/html; charset=utf-8",
                ),
                second_url: (
                    (
                        '<html><div class="widget-episodeTitle">第2話 続き</div>'
                        '<div class="widget-episodeBody"><p>新しい話。</p></div></html>'
                    ).encode("utf-8"),
                    "text/html; charset=utf-8",
                ),
            }
        )
        current_stdout = io.StringIO()
        current_result, current_stderr = run_discovery(
            current_opener,
            [
                "--source-root",
                str(self.source_root),
                "--work-url",
                WORK_URL,
                "--discovered-catalog",
                "catalog.v2.json",
                "--output-root",
                str(self.output_root),
                "--incremental-from-catalog",
                "catalog.v1.json",
                "--incremental-from-checkpoint",
                "checkpoint.v1.json",
                "--checkpoint",
                "checkpoint.v2.json",
            ],
            current_stdout,
        )

        self.assertEqual(current_result, 0, current_stderr)
        report = json.loads(current_stdout.getvalue())
        self.assertEqual(report["status"], "complete")
        self.assertEqual(
            report["incremental_update"]["added_count"],
            1,
        )
        self.assertEqual(report["incremental_update"]["reused_count"], 1)
        self.assertEqual(
            [request[0] for request in current_opener.requests],
            ["https://kakuyomu.jp/robots.txt", WORK_URL, second_url],
        )
        baseline_checkpoint = json.loads(
            (self.output_root / "checkpoint.v1.json").read_text(encoding="utf-8")
        )
        updated_checkpoint = json.loads(
            (self.output_root / "checkpoint.v2.json").read_text(encoding="utf-8")
        )
        self.assertEqual(baseline_checkpoint["discovered_episode_ids"], [EPISODE_ID])
        self.assertEqual(
            updated_checkpoint["discovered_episode_ids"], [EPISODE_ID, second_id]
        )
        self.assertEqual(
            updated_checkpoint["completed_episode_ids"], [EPISODE_ID, second_id]
        )

    def test_cli_full_refresh_rechecks_all_episodes_and_reports_hash_changes(self):
        first = (EPISODE_ID, "第1話 はじまり")
        second_id = "1111111111111111111"
        second_url = f"https://kakuyomu.jp/works/{WORK_ID}/episodes/{second_id}"
        second = (second_id, "第2話 続き")

        def episode_html(title, body):
            return (
                f'<html><div class="widget-episodeTitle">{title}</div>'
                f'<div class="widget-episodeBody"><p>{body}</p></div></html>'
            ).encode("utf-8")

        def work_responses(opener):
            clock = FakeClock()
            stderr = io.StringIO()

            def discover_test_work(work_url, **options):
                return discover_kakuyomu_work_catalog(
                    work_url,
                    opener=opener,
                    sleep=clock.sleep,
                    clock=clock.now,
                    **options,
                )

            def run(arguments, stdout):
                with (
                    patch(
                        "scripts.ingest_kakuyomu_pages."
                        "discover_kakuyomu_work_catalog",
                        side_effect=discover_test_work,
                    ),
                    patch("sys.stdout", stdout),
                    patch("sys.stderr", stderr),
                ):
                    result = main(arguments)
                return result

            return run, stderr

        baseline_opener = FakeOpener(
            {
                "https://kakuyomu.jp/robots.txt": (
                    ROBOTS.encode("utf-8"),
                    "text/plain; charset=utf-8",
                ),
                WORK_URL: (
                    make_work_page_html(WORK_ID, [first, second]).encode("utf-8"),
                    "text/html; charset=utf-8",
                ),
                PAGE_URL: (
                    episode_html(first[1], "同じ本文。"),
                    "text/html; charset=utf-8",
                ),
                second_url: (
                    episode_html(second[1], "更新前の本文。"),
                    "text/html; charset=utf-8",
                ),
            }
        )
        baseline_run, baseline_stderr = work_responses(baseline_opener)
        baseline_stdout = io.StringIO()
        baseline_result = baseline_run(
            [
                "--source-root",
                str(self.source_root),
                "--work-url",
                WORK_URL,
                "--discovered-catalog",
                "catalog.before.json",
                "--output-root",
                str(self.output_root),
                "--checkpoint",
                "checkpoint.before.json",
            ],
            baseline_stdout,
        )
        self.assertEqual(baseline_result, 0, baseline_stderr.getvalue())
        baseline_checkpoint_bytes = (
            self.output_root / "checkpoint.before.json"
        ).read_bytes()
        baseline_checkpoint = json.loads(baseline_checkpoint_bytes)
        baseline_raw_versions = baseline_checkpoint["completed_raw_versions"]

        refresh_opener = FakeOpener(
            {
                "https://kakuyomu.jp/robots.txt": (
                    ROBOTS.encode("utf-8"),
                    "text/plain; charset=utf-8",
                ),
                WORK_URL: (
                    make_work_page_html(
                        WORK_ID,
                        [first, second],
                        metadata_overrides={
                            "introduction": "Updated work description"
                        },
                    ).encode("utf-8"),
                    "text/html; charset=utf-8",
                ),
                PAGE_URL: (
                    episode_html(first[1], "同じ本文。"),
                    "text/html; charset=utf-8",
                ),
                second_url: (
                    episode_html(second[1], "更新後の本文。"),
                    "text/html; charset=utf-8",
                ),
            }
        )
        refresh_run, refresh_stderr = work_responses(refresh_opener)
        refresh_stdout = io.StringIO()
        refresh_result = refresh_run(
            [
                "--source-root",
                str(self.source_root),
                "--work-url",
                WORK_URL,
                "--discovered-catalog",
                "catalog.after.json",
                "--output-root",
                str(self.output_root),
                "--refresh-from-catalog",
                "catalog.before.json",
                "--refresh-from-checkpoint",
                "checkpoint.before.json",
                "--checkpoint",
                "checkpoint.refresh.json",
            ],
            refresh_stdout,
        )

        self.assertEqual(refresh_result, 0, refresh_stderr.getvalue())
        report = json.loads(refresh_stdout.getvalue())
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["content_refresh"]["episode_count"], 2)
        self.assertEqual(report["content_refresh"]["unchanged_count"], 1)
        self.assertEqual(report["content_refresh"]["changed_count"], 1)
        self.assertEqual(
            [
                item["episode_id"]
                for item in report["content_refresh"]["changed_episodes"]
            ],
            [second_id],
        )
        self.assertTrue(report["content_refresh"]["downstream_review_required"])
        self.assertEqual(
            [request[0] for request in refresh_opener.requests],
            [
                "https://kakuyomu.jp/robots.txt",
                WORK_URL,
                PAGE_URL,
                second_url,
            ],
        )
        self.assertEqual(
            (self.output_root / "checkpoint.before.json").read_bytes(),
            baseline_checkpoint_bytes,
        )
        refreshed_checkpoint = json.loads(
            (self.output_root / "checkpoint.refresh.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            refreshed_checkpoint["completed_raw_versions"][EPISODE_ID],
            baseline_raw_versions[EPISODE_ID],
        )
        self.assertNotEqual(
            refreshed_checkpoint["completed_raw_versions"][second_id],
            baseline_raw_versions[second_id],
        )

    def test_catalog_rejects_non_kakuyomu_or_read_url(self):
        self._write_catalog()
        catalog_path = self.source_root / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["episodes"][0]["page_url"] = PAGE_URL + "/read"
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

        work_id, episodes, _ = _load_catalog(str(self.source_root), "catalog.json")
        opener = FakeOpener({})
        with self.assertRaises(ValueError):
            KakuyomuPageAdapter(work_id, episodes, opener=opener)
        self.assertEqual(opener.requests, [])

    def test_catalog_v2_rejects_incomplete_chapter_mapping(self):
        self._write_catalog()
        catalog_path = self.source_root / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["schema_version"] = 2
        catalog["chapters"] = []
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "chapter groups"):
            _load_catalog(str(self.source_root), "catalog.json")

    def test_catalog_v2_rejects_reordered_group_episode_ids(self):
        self._write_catalog()
        catalog_path = self.source_root / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        second_episode_id = "7777777777777777777"
        catalog["schema_version"] = 2
        catalog["episodes"].append(
            {
                "episode_id": second_episode_id,
                "position": 2,
                "page_url": (
                    f"https://kakuyomu.jp/works/{WORK_ID}/episodes/"
                    f"{second_episode_id}"
                ),
            }
        )
        catalog["chapters"] = [
            {
                "group_id": "synthetic-group",
                "chapter_id": "synthetic-chapter",
                "title": "synthetic section",
                "level": 0,
                "position_start": 1,
                "position_end": 2,
                "episode_ids": [second_episode_id, EPISODE_ID],
            }
        ]
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "positions are inconsistent"):
            _load_catalog(str(self.source_root), "catalog.json")

    def test_cli_rejects_output_alias_with_catalog_before_network_or_writes(self):
        self._write_catalog()
        catalog_path = self.source_root / "catalog.json"
        original = catalog_path.read_bytes()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch(
            "scripts.ingest_kakuyomu_pages.KakuyomuPageAdapter"
        ) as adapter_class, patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            result = main(
                [
                    "--source-root",
                    str(self.source_root),
                    "--catalog",
                    "catalog.json",
                    "--output-root",
                    str(self.source_root),
                    "--manifest",
                    "catalog.json",
                ]
            )

        self.assertEqual(result, 1)
        self.assertEqual(stderr.getvalue(), "ERROR: ValueError\n")
        adapter_class.assert_not_called()
        self.assertEqual(catalog_path.read_bytes(), original)
        self.assertFalse((self.source_root / "source_checkpoint.json").exists())


if __name__ == "__main__":
    unittest.main()
