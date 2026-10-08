"""Read image metadata without fetching images or arbitrary upstream URLs."""
import html
import re
from urllib.parse import urlsplit

IMAGE_HOSTS = {'i.redd.it', 'preview.redd.it', 'external-preview.redd.it'}


def safe_image_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        return None
    value = html.unescape(value)
    try:
        parts = urlsplit(value)
        if (parts.scheme != 'https' or parts.hostname not in IMAGE_HOSTS
                or parts.username or parts.password or parts.port is not None
                or not re.search(r'\.(?:png|jpe?g|webp|gif|avif)$', parts.path, re.I)):
            return None
    except ValueError:
        return None
    return value


def clean_images(images):
    found = {}
    if not isinstance(images, list):
        return []
    for image in images[:40]:
        if not isinstance(image, dict):
            continue
        url = safe_image_url(image.get('url'))
        if url and url not in found:
            found[url] = {'url': url, 'preview_url': safe_image_url(image.get('preview_url')) or url,
                          'caption': str(image.get('caption') or '')[:500]}
        if len(found) >= 20:
            break
    return list(found.values())


def _preview(source, resolutions):
    if not isinstance(resolutions, list):
        resolutions = []
    candidates = []
    for item in resolutions:
        if not isinstance(item, dict):
            continue
        width = item.get('width', item.get('x', 0))
        url = safe_image_url(item.get('url', item.get('u')))
        if url and isinstance(width, (int, float)) and width > 0:
            candidates.append((width, url))
    if candidates:
        adequate = sorted(pair for pair in candidates if pair[0] >= 640)
        return adequate[0][1] if adequate else max(candidates)[1]
    return safe_image_url(source)


def extract_images(row):
    if not isinstance(row, dict) or row.get('is_video') is True:
        return []
    gallery = row.get('gallery_data')
    metadata = row.get('media_metadata')
    if isinstance(gallery, dict) and isinstance(gallery.get('items'), list) and isinstance(metadata, dict):
        images = []
        for item in gallery['items'][:40]:
            if not isinstance(item, dict):
                continue
            media = metadata.get(item.get('media_id'))
            if not isinstance(media, dict) or media.get('e') not in ('Image', 'AnimatedImage'):
                continue
            source = media.get('s')
            if not isinstance(source, dict):
                continue
            url = safe_image_url(source.get('u') or source.get('gif'))
            if url:
                images.append({'url': url, 'preview_url': _preview(url, media.get('p')),
                               'caption': item.get('caption') or ''})
        if images:
            return clean_images(images)
    direct = safe_image_url(row.get('url_overridden_by_dest')) or safe_image_url(row.get('url'))
    previews = row.get('preview')
    previews = previews.get('images', []) if isinstance(previews, dict) else []
    previews = previews if isinstance(previews, list) else []
    images = []
    for item in previews[:20]:
        if not isinstance(item, dict) or not isinstance(item.get('source'), dict):
            continue
        url = safe_image_url(item['source'].get('url'))
        if url:
            images.append({'url': direct or url, 'preview_url': _preview(url, item.get('resolutions'))})
            if direct:
                break
    if direct and not images:
        images.append({'url': direct, 'preview_url': direct})
    return clean_images(images)
