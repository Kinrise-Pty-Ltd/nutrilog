"""Azure AI Vision food-photo recognition: tags + caption, fuzzy-matched
against the existing food_items catalog. This is a suggestion aid, not an
auto-logger — Azure AI Vision isn't food-specialized, so results are shown
to the user to confirm/pick from, same as a manual search would be.

Two Vision resources are used, in two different regions:
  - AZURE_VISION_ENDPOINT/KEY (australiaeast) — 'tags' only.
  - AZURE_VISION_CAPTION_ENDPOINT/KEY (southeastasia) — 'caption' only.
The 'caption' feature (Image Analysis 4.0) only runs in a handful of
GPU-backed regions and is NOT available in australiaeast — requesting it
there fails the whole call with a 400, which is why it's split out to a
second resource in a supported region instead of just adding it to the
first one. The caption resource is optional: if unset, analyze_image()
falls back to tags-only (same as before), it just degrades gracefully.
"""
import difflib
import os

import requests

VISION_ENDPOINT = os.environ.get('AZURE_VISION_ENDPOINT', '').rstrip('/')
VISION_KEY = os.environ.get('AZURE_VISION_KEY')
VISION_CAPTION_ENDPOINT = os.environ.get('AZURE_VISION_CAPTION_ENDPOINT', '').rstrip('/')
VISION_CAPTION_KEY = os.environ.get('AZURE_VISION_CAPTION_KEY')
VISION_API_VERSION = os.environ.get('AZURE_VISION_API_VERSION', '2024-02-01')


def is_configured():
    return bool(VISION_ENDPOINT and VISION_KEY)


def analyze_image(image_bytes):
    """Returns {'caption': str, 'tags': [str]} from Azure AI Vision Image Analysis."""
    url = f'{VISION_ENDPOINT}/computervision/imageanalysis:analyze'
    params = {'api-version': VISION_API_VERSION, 'features': 'tags'}
    headers = {
        'Ocp-Apim-Subscription-Key': VISION_KEY,
        'Content-Type': 'application/octet-stream',
    }
    resp = requests.post(url, params=params, headers=headers, data=image_bytes, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    tags = [
        t['name'] for t in (data.get('tagsResult') or {}).get('values', [])
        if t.get('confidence', 0) > 0.5
    ]

    caption = ''
    if VISION_CAPTION_ENDPOINT and VISION_CAPTION_KEY:
        try:
            cap_url = f'{VISION_CAPTION_ENDPOINT}/computervision/imageanalysis:analyze'
            cap_resp = requests.post(
                cap_url, params={'api-version': VISION_API_VERSION, 'features': 'caption'},
                headers={'Ocp-Apim-Subscription-Key': VISION_CAPTION_KEY, 'Content-Type': 'application/octet-stream'},
                data=image_bytes, timeout=15,
            )
            cap_resp.raise_for_status()
            caption = (cap_resp.json().get('captionResult') or {}).get('text', '')
        except requests.RequestException:
            pass  # caption is a nice-to-have; tags alone still work

    return {'caption': caption, 'tags': tags}


def _normalize(text):
    return set(text.lower().replace('(', ' ').replace(')', ' ').replace('/', ' ').split())


def match_foods(caption, tags, food_items, limit=5):
    """Ranks food_items (list of dicts with 'name') against the recognized caption/tags."""
    search_terms = [caption] + list(tags)
    scored = []
    for item in food_items:
        name_words = _normalize(item['name'])
        best = 0.0
        for term in search_terms:
            if not term:
                continue
            ratio = difflib.SequenceMatcher(None, term.lower(), item['name'].lower()).ratio()
            overlap = len(_normalize(term) & name_words)
            if overlap:
                ratio = max(ratio, 0.5 + 0.15 * overlap)
            best = max(best, ratio)
        if best > 0.3:
            scored.append((best, item))
    scored.sort(key=lambda pair: -pair[0])
    return [item for _, item in scored[:limit]]
