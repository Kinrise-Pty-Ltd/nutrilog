"""Barcode lookup via Open Food Facts (openfoodfacts.org) — free, open,
no API key needed. Reliable for packaged/branded food where photo-based
recognition is too vague to identify the specific product; not useful for
home-cooked or unpackaged meals, which don't have a barcode at all.
"""
import re

import requests

API_BASE = 'https://world.openfoodfacts.org/api/v2/product'
USER_AGENT = 'NutriLog/1.0 (+https://nutrilog-app.azurewebsites.net)'


def _num(nutriments, key):
    val = nutriments.get(key)
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def lookup(code):
    """Looks up a barcode. Returns a normalized product dict, or None if not found."""
    code = re.sub(r'\D', '', code or '')
    if not code:
        return None

    resp = requests.get(
        f'{API_BASE}/{code}.json',
        params={'fields': 'product_name,brands,serving_size,serving_quantity,nutriments'},
        headers={'User-Agent': USER_AGENT},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get('status') != 1:
        return None

    product = data.get('product') or {}
    nutriments = product.get('nutriments') or {}
    name = product.get('product_name')
    if not name:
        return None
    brand = (product.get('brands') or '').split(',')[0].strip()

    has_serving = _num(nutriments, 'energy-kcal_serving') is not None
    if has_serving:
        serving_qty = product.get('serving_quantity')
        serving_size = str(round(float(serving_qty))) if serving_qty else (product.get('serving_size') or '1')
        calories = _num(nutriments, 'energy-kcal_serving')
        protein = _num(nutriments, 'proteins_serving') or 0
        carbs = _num(nutriments, 'carbohydrates_serving') or 0
        fat = _num(nutriments, 'fat_serving') or 0
    else:
        serving_size = '100'
        calories = _num(nutriments, 'energy-kcal_100g')
        protein = _num(nutriments, 'proteins_100g') or 0
        carbs = _num(nutriments, 'carbohydrates_100g') or 0
        fat = _num(nutriments, 'fat_100g') or 0

    if calories is None:
        return None  # no usable nutrition data — not worth surfacing

    return {
        'barcode': code,
        'name': f'{brand} {name}'.strip() if brand and brand.lower() not in name.lower() else name,
        'serving_size': serving_size,
        'serving_unit': 'g',
        'calories': round(calories),
        'protein_g': round(protein, 1),
        'carbs_g': round(carbs, 1),
        'fat_g': round(fat, 1),
    }
