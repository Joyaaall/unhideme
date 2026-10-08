import unittest
from backend import app


class ValidationTests(unittest.TestCase):
    def test_username_validation(self):
        self.assertEqual(app.validate_username('Tutyfruiity'), 'Tutyfruiity')
        for value in ('', '../secret', 'a b', 'a'*21, 'ab', 'üser', 'user\n', 'u/example'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.validate_username(value)


class EvidenceTests(unittest.TestCase):
    def test_exact_author_evidence_and_post_deduplication(self):
        rows = [
            {'url': 'https://www.reddit.com/r/test/comments/abc123/title/', 'title': 'A', 'snippet': 'Posted by **u/Tutyfruiity** in r/test'},
            {'url': 'https://old.reddit.com/r/test/comments/abc123/title/?x=1', 'title': 'duplicate', 'snippet': 'Tutyfruiity'},
            {'url': 'https://www.reddit.com/r/test/comments/def456/title/', 'title': 'B', 'snippet': 'Posted by u/TutyfruiityExtra'},
            {'url': 'https://evilreddit.com/r/test/comments/ghi789/title/', 'title': 'C', 'snippet': 'Tutyfruiity'},
            {'url': 'https://www.reddit.com/r/test/comments/jkl123/title/comment42/', 'title': 'D', 'snippet': 'Posted by u/Tutyfruiity'},
            {'url': 'https://www.reddit.com/r/test/comments/mno123/title/', 'title': 'E', 'snippet': 'Someone said u/TUTYFRUIITY is helpful'},
            {'url': 'https://www.reddit.com/r/test/comments/pqr123/title/', 'title': 'Tutyfruiity discussion', 'snippet': 'No attribution'},
        ]
        found = app.normalize_results(rows, 'Tutyfruiity', 'test')
        self.assertEqual([r['id'] for r in found], ['abc123', 'jkl123', 'mno123', 'pqr123'])
        self.assertEqual([r['classification'] for r in found], ['authored', 'mention', 'mention', 'uncertain'])
        self.assertIn('index', found[0]['evidence'].lower())


class ProviderTests(unittest.TestCase):
    def test_mcp_exa_parse_and_errors(self):
        import json
        text = 'Title: Hello\nURL: https://www.reddit.com/r/test/comments/abc123/hello/\nAuthor: u/Test\nHighlights:\nPosted by **u/Test**\n\n---\n\nTitle: Other\nURL: https://reddit.com/r/test/comments/def456/other/\nHighlights: inline text'
        envelope = {'result': {'content': [{'type': 'text', 'text': text}]}}
        body = 'event: message\ndata: ' + json.dumps(envelope) + '\n\n'
        rows = app.parse_exa(app.parse_mcp(body))
        self.assertEqual(len(rows), 2)
        self.assertIn('Posted by', rows[0]['snippet'])
        self.assertEqual(rows[1]['snippet'], 'inline text')
        for bad in ('no json', '{"error":{"message":"bad"}}', '{"result":{"isError":true,"content":[]}}'):
            with self.assertRaises(app.ProviderError):
                app.parse_mcp(bad)


    def test_provider_uses_bounded_http_transport(self):
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import threading, json
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                data = json.dumps({'result': {'content': [{'type': 'text', 'text': 'Title: Test\nURL: https://reddit.com/r/test/comments/abc123/test/\nHighlights:\nPosted by u/Test'}]}}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *args): pass
        with HTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                provider = app.SearchProvider(endpoint='http://127.0.0.1:%s' % server.server_port)
                rows = provider.search('site:reddit.com "Test"')
                self.assertEqual(rows[0]['title'], 'Test')
                self.assertEqual(received[0]['params']['name'], 'web_search_exa')
            finally:
                server.shutdown()
                thread.join()


    def test_optional_api_key_transport(self):
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import threading, json
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                captured.append((self.headers.get('x-api-key'), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"results":[{"url":"https://reddit.com/r/test/comments/abc123/test/","title":"Test","highlights":["Posted by u/Test"]}]}')
            def log_message(self, *args): pass
        with HTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                provider = app.SearchProvider(endpoint='http://127.0.0.1:%s' % server.server_port, api_key='test-only-not-a-secret')
                rows = provider.search('Test')
                self.assertEqual(provider.name, 'exa-api')
                self.assertEqual(rows[0]['snippet'], 'Posted by u/Test')
                self.assertEqual(captured[0][0], 'test-only-not-a-secret')
                self.assertEqual(captured[0][1]['query'], 'Test')
            finally:
                server.shutdown()
                thread.join()


class ServiceTests(unittest.TestCase):
    def test_search_contract_parallel_queries_and_bounded_cache(self):
        import threading
        class Provider:
            name = 'test'
            def __init__(self): self.calls = []
            def search(self, query):
                self.calls.append((query, threading.current_thread().name))
                return [{'url': 'https://reddit.com/r/test/comments/abc123/title/', 'title': 'A', 'snippet': 'Posted by u/Tutyfruiity'}]
        provider = Provider()
        now = [0]
        service = app.SearchService(provider, clock=lambda: now[0], cache_size=1)
        result = service.search('Tutyfruiity')
        self.assertEqual(len(result['results']), 1)
        self.assertFalse(result['cached'])
        self.assertEqual(result['provider'], 'test')
        self.assertTrue(result['warnings'])
        self.assertTrue(result['searched_at'])
        self.assertEqual(len(provider.calls), 2)
        self.assertTrue(all('search' in thread for _, thread in provider.calls))
        self.assertTrue(service.search('tutyfruiity')['cached'])
        now[0] = 601
        self.assertFalse(service.search('Tutyfruiity')['cached'])
        service.search('other')
        self.assertEqual(len(service.cache), 1)
        service.close()


    def test_failed_search_is_not_cached_and_concurrency_is_bounded(self):
        class Provider:
            name = 'broken'
            def search(self, query): raise app.ProviderError('failure')
        service = app.SearchService(Provider())
        try:
            with self.assertRaises(app.ProviderError): service.search('Example')
            self.assertFalse(service.cache)
            self.assertTrue(service.slots.acquire(False))
            self.assertTrue(service.slots.acquire(False))
            with self.assertRaises(app.BusyError): service.search('Example')
            service.slots.release()
            service.slots.release()
        finally:
            service.close()


class HTTPTests(unittest.TestCase):
    def test_http_contract_static_security_and_rate_limit(self):
        import tempfile, pathlib, threading, http.client, json
        class Provider:
            name = 'test'
            def search(self, query): return []
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder) / 'static'
            root.mkdir()
            (root / 'index.html').write_text('frontend')
            (root / 'app.js').write_text('javascript')
            (pathlib.Path(folder) / 'secret').write_text('secret')
            (root / 'link').symlink_to(pathlib.Path(folder) / 'secret')
            service = app.SearchService(Provider())
            server = app.make_server(('127.0.0.1', 0), service, root, rate_limit=3)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def get(path):
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                connection.request('GET', path)
                response = connection.getresponse()
                status, data = response.status, response.read()
                connection.close()
                return status, data
            try:
                status, data = get('/api/health')
                self.assertEqual((status, json.loads(data)), (200, {'ok': True, 'provider': 'test'}))
                self.assertEqual(get('/'), (200, b'frontend'))
                self.assertEqual(get('/static/app.js'), (200, b'javascript'))
                for path in ('/%2e%2e/secret', '/link', '/missing', '/api/missing'):
                    self.assertEqual(get(path)[0], 404)
                self.assertEqual(get('/api/search?username=bad%20name')[0], 400)
                self.assertEqual(get('/api/search?username=abc&username=def')[0], 400)
                for _ in range(2): service.slots.acquire(False)
                self.assertEqual(get('/api/search?username=Busy')[0], 503)
                for _ in range(2): service.slots.release()
                status, data = get('/api/search?username=Example')
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(data)['results'], [])
                self.assertTrue(json.loads(get('/api/search?username=Example')[1])['cached'])
                self.assertEqual(get('/api/search?username=Example')[0], 429)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                service.close()


    def test_http_connection_threads_are_bounded(self):
        import threading, http.client
        server = app.make_server(('127.0.0.1', 0))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        acquired = []
        try:
            while server.connection_slots.acquire(False): acquired.append(True)
            self.assertEqual(len(acquired), 16)
            connection = http.client.HTTPConnection(*server.server_address, timeout=5)
            connection.request('GET', '/api/health')
            response = connection.getresponse()
            self.assertEqual(response.status, 503)
            self.assertIn(b'error', response.read())
            connection.close()
        finally:
            for _ in acquired: server.connection_slots.release()
            server.shutdown()
            server.server_close()
            server.search_service.close()
            thread.join()


class CLITests(unittest.TestCase):
    def test_cli_has_localhost_default(self):
        import subprocess, sys
        result = subprocess.run([sys.executable, '-m', 'backend.app', '--help'], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertIn('127.0.0.1', result.stdout)
        self.assertIn('--port', result.stdout)


if __name__ == '__main__':
    unittest.main()
