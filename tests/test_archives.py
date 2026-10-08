import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit
from backend import app


class ArchiveTransportTests(unittest.TestCase):
    def test_archive_transport_enforces_timeout_and_two_mb_read_cap(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        captured = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit):
                captured.append(limit)
                return b'x' * 2000001
        def open_fixture(request, timeout):
            self.assertEqual(timeout, 10)
            return Response()
        for cls in (app.ArcticShiftProvider, app.PullPushProvider):
            with patch.object(app, 'urlopen', open_fixture), self.assertRaisesRegex(app.ProviderError, 'size|cap'):
                cls().search('Example')
            self.assertEqual(captured[-1], 2000001)
            error = HTTPError(cls.endpoint, 403, 'Forbidden', {}, None)
            with patch.object(app, 'urlopen', side_effect=error), patch.object(error, 'close', wraps=error.close) as close, self.assertRaisesRegex(app.ProviderError, 'HTTP 403'):
                cls().search('Example')
            try:
                close.assert_called_once()
            finally:
                error.close()

    def test_archive_http_author_filter_encoding_and_page_limits(self):
        received = []
        payload = {'data': [
            {'id': 'abc123', 'author': 'Test_User-1', 'subreddit': 'test', 'title': 'Real post', 'selftext': 'archive body', 'created_utc': 1700000000, 'permalink': '/r/test/comments/abc123/real/'},
            {'id': 'bad123', 'author': 'Test_User-1Extra', 'subreddit': 'test', 'title': 'Wrong author'},
            {'id': 'bad456', 'subreddit': 'test', 'title': 'Missing author'},
            {'id': 'def456', 'author': 'test_user-1', 'subreddit': 'test', 'title': 'Case equivalent'},
        ]}
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())
            def log_message(self, *args): pass
        with HTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                endpoint = f'http://127.0.0.1:{server.server_port}/posts'
                for cls, limit_key in ((app.ArcticShiftProvider, 'limit'), (app.PullPushProvider, 'size')):
                    provider = cls(endpoint=endpoint)
                    self.assertEqual(provider.timeout, 10)
                    rows = provider.search('Test_User-1')
                    self.assertEqual([r['id'] for r in rows], ['abc123', 'def456'])
                    self.assertEqual(rows[0]['created_utc'], 1700000000)
                    self.assertEqual(rows[0]['source'], provider.name)
                    query = parse_qs(urlsplit(received[-1]).query)
                    self.assertEqual(query, {'author': ['Test_User-1'], limit_key: ['100'], 'sort': ['desc']})
                    before = len(received)
                    with self.assertRaises(ValueError): provider.search('Test&author=someone')
                    self.assertEqual(len(received), before)
            finally:
                server.shutdown()
                thread.join()


class ArchiveEvidenceTests(unittest.TestCase):
    def test_archive_permalink_must_match_its_real_post_id(self):
        row = {'url': 'https://reddit.com/r/test/comments/abc123/title/', 'id': 'different', 'author': 'Example', '_archive': True, 'source': 'archive'}
        self.assertEqual(app.normalize_results([row], 'Example', 'archive'), [])

    def test_malformed_urls_and_ports_are_excluded_without_losing_good_rows(self):
        good = {'url': 'https://reddit.com/r/test/comments/abc123/real/', 'snippet': 'Posted by u/Example'}
        bad_urls = ['https://reddit.com:bad/r/test/comments/def456/x/', 'https://reddit.com:99999/r/test/comments/def456/x/', 'https://[broken/r/test/comments/def456/x/', 'https://reddit.com:443/r/test/comments/def456/x/', 'https://user@reddit.com/r/test/comments/def456/x/']
        rows = [{**good, 'url': url} for url in bad_urls] + [good]
        self.assertEqual([r['id'] for r in app.normalize_results(rows, 'Example', 'exa')], ['abc123'])

    def test_archive_upgrades_evidence_and_preserves_unique_sources_and_dates(self):
        web = {'url': 'https://reddit.com/r/test/comments/abc123/real/', 'title': 'Web title', 'snippet': 'Someone mentioned u/Example', 'source': 'exa'}
        archive = {'url': web['url'], 'title': 'Archive title', 'snippet': '', 'author': 'EXAMPLE', '_archive': True, 'source': 'arctic-shift', 'created_utc': 1700000000}
        other = {**archive, 'source': 'pullpush', 'created_utc': None}
        for rows in ([web, archive, other, web], [archive, web, other, archive]):
            result = app.normalize_results(rows, 'Example', 'default')
            self.assertEqual(len(result), 1)
            item = result[0]
            self.assertEqual(item['classification'], 'authored')
            self.assertEqual(item['evidence_strength'], 'archive-author')
            self.assertEqual(set(item['sources']), {'exa', 'arctic-shift', 'pullpush'})
            self.assertEqual(len(item['sources']), 3)
            self.assertEqual(item['created_utc'], 1700000000)
            self.assertIn('archive', item['evidence'].lower())
        self.assertEqual(app.normalize_results([{**archive, 'author': 'ExampleExtra'}], 'Example', 'default'), [])


class ArchiveServiceTests(unittest.TestCase):
    def test_archive_success_survives_web_failure_and_marks_coverage_cap(self):
        class Web:
            name = 'web-failed'
            def search(self, query): raise app.ProviderError('Web unavailable')
        class Archive:
            name = 'archive'
            def search(self, username):
                return [{'id': format(i, 'x'), 'url': f'https://reddit.com/r/test/comments/{i:x}/real/', 'author': username, '_archive': True} for i in range(100)]
        service = app.SearchService(Web(), archives=[Archive()])
        try:
            result = service.search('Example')
            self.assertEqual(len(result['results']), 100)
            self.assertEqual([(s['status'], s['count']) for s in result['sources']], [('error', 0), ('partial', 100)])
        finally:
            service.close()

    def test_partial_web_queries_are_reported_and_deadline_does_not_wait_for_archive(self):
        import time
        release = threading.Event()
        class Web:
            name = 'web'
            def search(self, query):
                if 'u/Example' in query: raise app.ProviderError('One query unavailable')
                return []
        class Archive:
            name = 'slow'
            def search(self, username):
                release.wait(2)
                return []
        service = app.SearchService(Web(), archives=[Archive()], search_timeout=0.05)
        try:
            started = time.monotonic()
            result = service.search('Example')
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual([s['status'] for s in result['sources']], ['partial', 'error'])
            self.assertIn('deadline', result['sources'][1]['message'])
            self.assertFalse(service.cache)
        finally:
            release.set()
            service.close()

    def test_all_source_failures_return_honest_http_502(self):
        import http.client
        class Broken:
            name = 'web'
            def search(self, query): raise app.ProviderError('HTTP 403 blocked')
        class Archive(Broken):
            name = 'archive'
        service = app.SearchService(Broken(), archives=[Archive()])
        server = app.make_server(('127.0.0.1', 0), service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection(*server.server_address, timeout=2)
        try:
            connection.request('GET', '/api/search?username=Example')
            response = connection.getresponse()
            self.assertEqual(response.status, 502)
            message = json.loads(response.read())['error']
            self.assertIn('All search sources failed', message)
            self.assertIn('403', message)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join()
            service.close()

    def test_production_cli_explicitly_enables_archives_but_injected_tests_do_not(self):
        from unittest.mock import patch
        service = app.SearchService()
        injected = app.SearchService(type('Web', (), {'name': 'fake'})())
        try:
            self.assertEqual([a.name for a in service.archives], ['arctic-shift', 'pullpush'])
            self.assertEqual(injected.archives, [])
        finally:
            service.close()
            injected.close()
        captured = []
        def capture_server(address, service):
            captured.append(service)
            raise RuntimeError('stop before serving')
        with patch('sys.argv', ['threadtrace']), patch.object(app, 'make_server', capture_server):
            with self.assertRaisesRegex(RuntimeError, 'stop before serving'):
                app.main()
        try:
            self.assertEqual([a.name for a in captured[0].archives], ['arctic-shift', 'pullpush'])
        finally:
            captured[0].close()

    def test_two_admitted_searches_have_enough_workers_for_all_sources(self):
        from concurrent.futures import ThreadPoolExecutor
        barrier = threading.Barrier(8, timeout=2)
        class Provider:
            name = 'test-web'
            def search(self, query):
                barrier.wait()
                return []
        class Archive(Provider):
            name = 'test-archive'
        class Archive2(Provider):
            name = 'test-archive2'
        service = app.SearchService(Provider(), archives=[Archive(), Archive2()])
        try:
            with ThreadPoolExecutor(max_workers=2) as clients:
                results = list(clients.map(service.search, ['Example', 'Another']))
            self.assertTrue(all(s['status'] == 'ok' for r in results for s in r['sources']))
        finally:
            service.close()

    def test_sources_run_concurrently_and_merge_without_extra_exa_quota(self):
        barrier = threading.Barrier(4, timeout=2)
        calls = []
        class Web:
            name = 'exa-test'
            def search(self, query):
                calls.append(query)
                barrier.wait()
                return [{'url': 'https://reddit.com/r/test/comments/abc123/real/', 'snippet': 'u/Example'}]
        class Archive:
            name = 'archive-test'
            def search(self, username):
                barrier.wait()
                return [{'url': 'https://reddit.com/r/test/comments/abc123/real/', 'author': username, '_archive': True, 'source': self.name, 'created_utc': 1700000000}]
        class Broken:
            name = 'archive-broken'
            def search(self, username):
                barrier.wait()
                raise app.ProviderError('Archive blocked or unavailable (HTTP 403).')
        service = app.SearchService(Web(), archives=[Archive(), Broken()])
        try:
            result = service.search('Example')
            self.assertEqual(sorted(calls), sorted(['site:reddit.com "Example"', 'site:reddit.com "u/Example"']))
            self.assertEqual(len(result['results']), 1)
            self.assertEqual(result['results'][0]['evidence_strength'], 'archive-author')
            sources = {s['name']: s for s in result['sources']}
            self.assertEqual(sources['exa-test']['status'], 'ok')
            self.assertEqual(sources['exa-test']['count'], 1)
            self.assertEqual(sources['archive-test']['count'], 1)
            self.assertEqual(sources['archive-broken']['status'], 'error')
            self.assertIn('403', sources['archive-broken']['message'])
            self.assertIn('100', sources['archive-test']['message'])
            self.assertIn('pagination', sources['archive-test']['message'])
            self.assertFalse(service.cache)
        finally:
            service.close()


if __name__ == '__main__':
    unittest.main()
