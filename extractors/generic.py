"""Generic extractor that hashes normalized page content. Use for any site without a dedicated extractor."""
import urllib.request
import hashlib
import re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# Tags whose content changes dynamically and would cause false positives
_STRIP_TAGS = re.compile(
    r'<(script|style|noscript)[^>]*>.*?</\1>', flags=re.S | re.I
)
_STRIP_COMMENTS = re.compile(r'<!--.*?-->', re.S)
# Session/CSRF/nonce values embedded as attributes
_STRIP_DYNAMIC_ATTRS = re.compile(
    r'\b(nonce|csrf|token|timestamp|session)[=:]["\'][^"\']*["\']', re.I
)


def extract(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode('utf-8')

    cleaned = _STRIP_TAGS.sub('', html)
    cleaned = _STRIP_COMMENTS.sub('', cleaned)
    cleaned = _STRIP_DYNAMIC_ATTRS.sub('', cleaned)

    content_hash = hashlib.sha256(cleaned.encode()).hexdigest()
    return {'page': {'hash': content_hash}}
