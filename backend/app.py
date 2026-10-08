"""Unhideme: public search-index evidence, not Reddit verification."""
import re
import json
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote
import mimetypes
from backend.media import extract_images, clean_images


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, *args, **kwargs):
        self.connection_slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.connection_slots.acquire(False):
            body = b'{"error":"Server is busy. Please retry shortly."}'
            try:
                request.settimeout(1)
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nConnection: close\r\nRetry-After: 60\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connection_slots.release()


def make_server(address=('127.0.0.1', 8000), service=None, static_root=None, rate_limit=20):
    service = service or SearchService()
    root = Path(static_root or Path(__file__).resolve().parent.parent / 'static').resolve()
    rates, rate_lock = OrderedDict(), threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(10)
            super().setup()

        def log_message(self, *args):
            pass  # Do not retain searched usernames in request logs.

        def send_body(self, status, data, content_type='application/json; charset=utf-8'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://i.redd.it https://preview.redd.it https://external-preview.redd.it; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            if status in (429, 503):
                self.send_header('Retry-After', '60')
            self.end_headers()
            self.wfile.write(data)

        def json_response(self, status, payload):
            self.send_body(status, json.dumps(payload, ensure_ascii=False).encode())

        def do_GET(self):
            try:
                self.handle_get()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.json_response(500, {'error': 'Internal server error.'})

        def handle_get(self):
            parsed = urlsplit(self.path)
            if parsed.path == '/api/health':
                self.json_response(200, {'ok': True, 'provider': service.provider.name})
                return
            if parsed.path == '/api/search':
                try:
                    params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=5)
                    if set(params) != {'username'} or len(params['username']) != 1:
                        raise ValueError('Provide exactly one username parameter.')
                    username = validate_username(params['username'][0])
                except ValueError as exc:
                    self.json_response(400, {'error': str(exc)})
                    return
                now, client = time.monotonic(), self.client_address[0]
                with rate_lock:
                    stamps = [stamp for stamp in rates.pop(client, []) if now - stamp < 60]
                    allowed = len(stamps) < rate_limit
                    if allowed:
                        stamps.append(now)
                    rates[client] = stamps
                    while len(rates) > 1024:
                        rates.popitem(last=False)
                if not allowed:
                    self.json_response(429, {'error': 'Search rate limit reached. Try again in one minute.'})
                    return
                try:
                    self.json_response(200, service.search(username))
                except BusyError as exc:
                    self.json_response(503, {'error': str(exc)})
                except ProviderError as exc:
                    self.json_response(502, {'error': str(exc)})
                return
            if parsed.path.startswith('/api/'):
                self.json_response(404, {'error': 'Not found.'})
                return
            decoded = unquote(parsed.path)
            relative = decoded.removeprefix('/static/').lstrip('/')
            target = (root / ('index.html' if decoded == '/' else relative)).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                self.json_response(404, {'error': 'Not found.'})
                return
            self.send_body(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or 'application/octet-stream')

    server = AppServer(address, Handler)
    server.search_service = service
    return server


class SearchService:
    def __init__(self, provider=None, clock=time.monotonic, cache_size=128, archives=None, search_timeout=28):
        self.provider = provider if provider is not None else SearchProvider()
        self.archives = list(archives) if archives is not None else ([] if provider is not None else [ArcticShiftProvider(), PullPushProvider()])
        self.search_timeout = min(max(search_timeout, 0), 28)
        self.clock, self.cache_size = clock, cache_size
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(2)
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix='search')

    def search(self, username):
        validate_username(username)
        if not self.slots.acquire(False):
            raise BusyError('Two searches are already running. Please retry shortly.')
        try:
            return self._search(username)
        finally:
            self.slots.release()

    def _search(self, username):
        validate_username(username)
        key = username.lower()
        with self.lock:
            for old in list(self.cache):
                if self.clock() - self.cache[old][0] >= 600:
                    del self.cache[old]
            if key in self.cache:
                self.cache.move_to_end(key)
                return {**self.cache[key][1], 'username': username, 'cached': True}
        # Two established queries only: conserve the uncertain keyless quota.
        queries = [f'site:reddit.com "{username}"', f'site:reddit.com "u/{username}"']
        jobs = [(self.provider.name, False, self.pool.submit(self.provider.search, query)) for query in queries]
        jobs += [(archive.name, True, self.pool.submit(archive.search, username)) for archive in self.archives]
        done, pending = wait([future for _, _, future in jobs], timeout=self.search_timeout)
        rows, errors, successes = [], [], 0
        states = OrderedDict()
        for name, archived, future in jobs:
            state = states.setdefault(name, {'name': name, 'status': 'ok', 'count': 0, 'message': '', 'successes': 0, 'errors': [], 'rows': [], 'archived': archived})
            if future not in done:
                future.cancel()
                state['errors'].append('Source exceeded the total search deadline.')
                continue
            try:
                batch = future.result()
                if not isinstance(batch, list):
                    raise ProviderError('Source returned an unreadable response.')
                # The configured source, not an arbitrary upstream field, owns attribution.
                batch = [{**row, 'source': name} for row in batch if isinstance(row, dict)]
                if archived:
                    batch = [{**row, '_archive': True} for row in batch]
                rows.extend(batch)
                state['rows'].extend(batch)
                state['successes'] += 1
                successes += 1
            except Exception as exc:
                state['errors'].append(str(exc) if isinstance(exc, ProviderError) else 'Source unavailable or returned an invalid response.')
        sources = []
        for state in states.values():
            state['count'] = len(normalize_results(state['rows'], username, state['name']))
            if state['errors']:
                state['status'] = 'partial' if state['successes'] else 'error'
                errors.extend(f"{state['name']}: {message}" for message in state['errors'])
            elif state['archived'] and len(state['rows']) >= 100:
                state['status'] = 'partial'
            coverage = ('One page, up to 100 posts; no pagination performed. Archive coverage may be incomplete or stale; this is not exhaustive history.' if state['archived'] else 'Two public web-index queries; not live Reddit verification or exhaustive history.')
            state['message'] = ' '.join(state['errors'] + [coverage])
            sources.append({key: state[key] for key in ('name', 'status', 'count', 'message')})
        if not successes:
            raise ProviderError('All search sources failed or timed out. ' + ' '.join(errors))
        result = {'username': username, 'results': normalize_results(rows, username, self.provider.name), 'warnings': ['Public index and archive evidence, not direct Reddit verification. Results may be incomplete, stale, or removed from Reddit. No results does not prove no activity.'] + [s['message'] for s in sources if s['name'] != self.provider.name] + errors, 'cached': False, 'searched_at': datetime.now(timezone.utc).isoformat(), 'provider': self.provider.name, 'sources': sources}
        if not errors:
            with self.lock:
                self.cache[key] = (self.clock(), result)
                while len(self.cache) > self.cache_size:
                    self.cache.popitem(last=False)
        return result

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)


class BusyError(RuntimeError):
    pass


class ProviderError(RuntimeError):
    pass


def parse_mcp(body):
    candidates = [body] if body.lstrip().startswith('{') else [line[5:].strip() for line in body.split('\n') if line.startswith('data:')]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        result = data.get('result', {})
        if data.get('error') or result.get('isError'):
            raise ProviderError('Search provider rejected the request (possibly free-tier quota).')
        texts = [c['text'] for c in result.get('content', []) if c.get('type') == 'text' and c.get('text')]
        if texts:
            return '\n'.join(texts)
    raise ProviderError('Search provider returned an unreadable response.')


def parse_exa(text):
    rows = []
    for block in re.split(r'\n\s*---\s*\n', text):
        row, snippets, collecting = {}, [], False
        for line in block.split('\n'):
            label = re.match(r'^(Title|URL|Published|Author|Highlights):\s*(.*)$', line)
            if label:
                key, value = label.groups()
                collecting = key == 'Highlights'
                if key in ('Title', 'URL'):
                    row[key.lower()] = value
                elif collecting and value:
                    snippets.append(value)
            elif collecting:
                snippets.append(line)
        if row.get('url'):
            row['snippet'] = '\n'.join(snippets).strip()
            rows.append(row)
    return rows
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import URLError


class ArchiveProvider:
    """One bounded author-filtered page; an archive is not a complete history."""
    timeout = 10
    read_limit = 2000000
    limit_key = 'limit'

    def __init__(self, endpoint=None):
        self.endpoint = endpoint or self.endpoint

    def search(self, username):
        from urllib.parse import urlencode
        validate_username(username)
        query = urlencode({'author': username, self.limit_key: 100, 'sort': 'desc'})
        request = Request(self.endpoint + '?' + query, headers={'Accept': 'application/json', 'User-Agent': 'Unhideme/1.0'})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read(self.read_limit + 1)
            if len(body) > self.read_limit:
                raise ProviderError('Archive response exceeded the 2 MB read cap.')
            data = json.loads(body)
            if not isinstance(data, dict) or not isinstance(data.get('data'), list):
                raise ProviderError('Archive returned an unreadable response.')
            rows = []
            for row in data['data'][:100]:
                if not isinstance(row, dict) or not isinstance(row.get('author'), str) or row['author'].lower() != username.lower():
                    continue
                post_id = str(row.get('id', '')).removeprefix('t3_')
                subreddit = str(row.get('subreddit', ''))
                if not re.fullmatch(r'[a-z0-9]+', post_id, re.I) or not re.fullmatch(r'[A-Za-z0-9_]+', subreddit):
                    continue
                permalink = row.get('permalink')
                url = ('https://www.reddit.com' + permalink if isinstance(permalink, str) and permalink.startswith('/r/') else permalink) if permalink else f'https://www.reddit.com/r/{subreddit}/comments/{post_id}/_/'
                rows.append({'id': post_id.lower(), 'url': url, 'title': row.get('title', ''), 'snippet': row.get('selftext', ''), 'author': row['author'], '_archive': True, 'source': self.name, 'created_utc': row.get('created_utc'), 'images': extract_images(row), 'over_18': row.get('over_18') is True, 'spoiler': row.get('spoiler') is True})
            return rows
        except (URLError, OSError, ValueError) as exc:
            from urllib.error import HTTPError
            message = f'Archive blocked or unavailable (HTTP {exc.code}).' if isinstance(exc, HTTPError) else 'Archive unavailable or timed out.'
            if isinstance(exc, HTTPError):
                exc.close()
            raise ProviderError(message) from exc


class ArcticShiftProvider(ArchiveProvider):
    name = 'arctic-shift'
    endpoint = 'https://arctic-shift.photon-reddit.com/api/posts/search'


class PullPushProvider(ArchiveProvider):
    name = 'pullpush'
    endpoint = 'https://api.pullpush.io/reddit/search/submission/'
    limit_key = 'size'


class SearchProvider:
    name = 'exa-keyless'

    def __init__(self, endpoint=None, timeout=20, api_key=''):
        self.api_key = api_key
        self.name = 'exa-api' if api_key else 'exa-keyless'
        self.endpoint = endpoint or ('https://api.exa.ai/search' if api_key else 'https://mcp.exa.ai/mcp')
        self.timeout = timeout

    def search(self, query):
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'web_search_exa', 'arguments': {'query': query, 'numResults': 10}}}
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream', 'User-Agent': 'hermes-agent'}
        if self.api_key:
            payload = {'query': query, 'numResults': 10, 'type': 'auto', 'contents': {'highlights': True}}
            headers['x-api-key'] = self.api_key
        request = Request(self.endpoint, data=json.dumps(payload).encode(), headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read(2000001)
            if len(body) > 2000000:
                raise ProviderError('Search response exceeded size limit.')
            if self.api_key:
                data = json.loads(body)
                if not isinstance(data.get('results'), list):
                    raise ProviderError('Search provider returned an unreadable response.')
                return [{'url': row.get('url', ''), 'title': row.get('title', ''), 'snippet': '\n'.join(row.get('highlights') or [])} for row in data['results']]
            return parse_exa(parse_mcp(body.decode('utf-8')))
        except (URLError, OSError, ValueError) as exc:
            raise ProviderError('Public search provider unavailable or timed out. Free-tier availability is not guaranteed.') from exc


def normalize_results(rows, username, source):
    exact = r'(?<![A-Za-z0-9_-])' + re.escape(username) + r'(?![A-Za-z0-9_-])'
    author = re.compile(r'^(?:Posted|Submitted) by\s+(?:\*\*)?u/' + re.escape(username) + r'(?![A-Za-z0-9_-])', re.I | re.M)
    found = {}
    ranks = {'archive-author': 3, 'index-author': 2, 'mention': 1, 'uncertain': 0}
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = str(row.get('url', ''))
        try:
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or parsed.hostname not in ('reddit.com', 'www.reddit.com', 'old.reddit.com', 'np.reddit.com') or parsed.username or parsed.port is not None:
                continue
        except ValueError:
            continue
        match = re.fullmatch(r'/r/([A-Za-z0-9_]+)/comments/([a-z0-9]+)/([^/]*)(?:/([^/]+))?/?', parsed.path, re.I)
        if not match:
            continue
        snippet = str(row.get('snippet') or row.get('description') or '')[:12000]
        title = str(row.get('title') or '')[:500]
        archived = row.get('_archive') is True
        if archived and (not isinstance(row.get('author'), str) or row['author'].lower() != username.lower() or match[4] or ('id' in row and str(row['id']).removeprefix('t3_').lower() != match[2].lower())):
            continue
        if not archived and not re.search(exact, title + '\n' + snippet, re.I):
            continue
        hit = author.search(snippet)
        if archived:
            classification, strength, evidence = 'authored', 'archive-author', 'Archive author field exactly matches the requested username; not independently verified on live Reddit.'
        elif hit and not match[4]:
            classification, strength, evidence = 'authored', 'index-author', 'Search index attribution: ' + hit[0] + ' (not independently verified on Reddit).'
        elif re.search(r'(?<![A-Za-z0-9_/-])u/' + re.escape(username) + r'(?![A-Za-z0-9_-])', snippet, re.I):
            classification, strength, evidence = 'mention', 'mention', 'Exact u/username appears in indexed text; this does not establish post authorship.'
        else:
            classification, strength, evidence = 'uncertain', 'uncertain', 'Exact username appears in indexed text without clear author attribution.'
        origin = row.get('source') or source
        item = {'id': match[2].lower(), 'title': title, 'url': 'https://www.reddit.com' + parsed.path, 'subreddit': match[1], 'snippet': snippet[:2400], 'classification': classification, 'evidence_strength': strength, 'evidence': evidence, 'source': origin, 'sources': [origin]}
        item['images'] = clean_images(row.get('images'))
        item['over_18'] = row.get('over_18') is True
        item['spoiler'] = row.get('spoiler') is True
        timestamp = row.get('created_utc')
        if archived and isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool) and 0 <= timestamp <= 253402300799:
            item['created_utc'] = timestamp
        previous = found.get(item['id'])
        if previous:
            sources = list(dict.fromkeys(previous['sources'] + item['sources']))
            winner = item if ranks[strength] > ranks[previous['evidence_strength']] else previous
            winner['sources'] = sources
            winner['images'] = clean_images(previous.get('images', []) + item.get('images', []))
            winner['over_18'] = previous.get('over_18', False) or item.get('over_18', False)
            winner['spoiler'] = previous.get('spoiler', False) or item.get('spoiler', False)
            if 'created_utc' not in winner:
                dated = item if 'created_utc' in item else previous
                if 'created_utc' in dated:
                    winner['created_utc'] = dated['created_utc']
            found[item['id']] = winner
        else:
            found[item['id']] = item
    return list(found.values())


def validate_username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{3,20}', value):
        raise ValueError('Username must be 3–20 ASCII letters, digits, underscores or hyphens (without u/).')
    return value


def main():
    import argparse
    import os
    parser = argparse.ArgumentParser(description='Unhideme public Reddit search-index explorer (localhost 127.0.0.1 by default).')
    parser.add_argument('--host', default='127.0.0.1', help='Bind address; use a non-loopback address only behind appropriate access controls.')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    provider = SearchProvider(api_key=os.environ.get('EXA_API_KEY', ''))
    service = SearchService(provider, archives=[ArcticShiftProvider(), PullPushProvider()])
    server = make_server((args.host, args.port), service)
    print(f'Unhideme listening on http://{args.host}:{server.server_port} ({provider.name})', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.close()


if __name__ == '__main__':
    main()
