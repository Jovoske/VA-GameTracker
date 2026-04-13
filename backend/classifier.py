"""
VA GameTracker - Species classification using iNaturalist Vision API

Uses iNaturalist's free computer vision API to identify species from
camera trap photos. Lightweight — no local ML models needed.
Filters results to mammals found in Spain.
"""
import requests

# Mammals found in Spain (common name → scientific name)
SPANISH_MAMMALS = {
    'Wild Boar': 'Sus scrofa',
    'Red Deer': 'Cervus elaphus',
    'Roe Deer': 'Capreolus capreolus',
    'Fallow Deer': 'Dama dama',
    'Red Fox': 'Vulpes vulpes',
    'European Rabbit': 'Oryctolagus cuniculus',
    'European Hare': 'Lepus europaeus',
    'Iberian Hare': 'Lepus granatensis',
    'European Badger': 'Meles meles',
    'Wildcat': 'Felis silvestris',
    'Common Genet': 'Genetta genetta',
    'Mouflon': 'Ovis aries musimon',
    'Iberian Ibex': 'Capra pyrenaica',
    'Iberian Lynx': 'Lynx pardinus',
    'Iberian Wolf': 'Canis lupus signatus',
    'Brown Bear': 'Ursus arctos',
    'European Otter': 'Lutra lutra',
    'Pine Marten': 'Martes martes',
    'Beech Marten': 'Martes foina',
    'Least Weasel': 'Mustela nivalis',
    'European Polecat': 'Mustela putorius',
    'Egyptian Mongoose': 'Herpestes ichneumon',
    'European Hedgehog': 'Erinaceus europaeus',
    'Garden Dormouse': 'Eliomys quercinus',
    'Red Squirrel': 'Sciurus vulgaris',
}

# Reverse lookup: scientific name → common name
SCIENTIFIC_TO_COMMON = {}
for common, sci in SPANISH_MAMMALS.items():
    SCIENTIFIC_TO_COMMON[sci.lower()] = common
    # Also map genus level
    genus = sci.split()[0].lower()
    if genus not in SCIENTIFIC_TO_COMMON:
        SCIENTIFIC_TO_COMMON[genus] = common

# Species we track as priority
PRIORITY_SPECIES = {v: k for k, v in SPANISH_MAMMALS.items()}

BOAR_CATEGORIES = ['Big Boar', 'Sow', 'Juvenile', 'Piglet']


def classify_from_url(image_url):
    """
    Classify an image using iNaturalist's computer vision API.
    Returns: (species_name, confidence) or ('Unknown', 0.0)
    """
    if not image_url or not image_url.startswith('http'):
        return 'Unknown', 0.0

    try:
        resp = requests.get(
            'https://api.inaturalist.org/v1/computervision/score_image',
            params={'image_url': image_url},
            timeout=15
        )
        if resp.status_code != 200:
            return 'Unknown', 0.0

        data = resp.json()
        results = data.get('results', [])

        for result in results:
            taxon = result.get('taxon', {})
            score = result.get('combined_score', 0)
            sci_name = (taxon.get('name', '') or '').lower()
            ancestors = taxon.get('ancestor_ids', [])
            iconic = taxon.get('iconic_taxon_name', '')

            # Only consider mammals (iconic_taxon_name or class Mammalia id=40151)
            if iconic != 'Mammalia' and 40151 not in ancestors:
                continue

            # Check if it matches a Spanish mammal
            for key, common in SCIENTIFIC_TO_COMMON.items():
                if key in sci_name or sci_name.startswith(key):
                    return common, score / 100.0

            # If it's a mammal but not in our list, use the common name
            common_name = taxon.get('preferred_common_name') or taxon.get('name', 'Unknown Mammal')
            if score > 20:
                return common_name, score / 100.0

        return 'Unknown', 0.0

    except Exception as e:
        print(f"[classifier] iNaturalist API error: {e}")
        return 'Unknown', 0.0


def classify_from_spypoint_tags(photo_data):
    """Extract species from Spypoint photo tags as fallback."""
    tags = photo_data.get('tags', [])
    tag = photo_data.get('tag')
    if isinstance(tag, str) and tag:
        tags = [tag] + (tags if isinstance(tags, list) else [])
    if isinstance(tags, str):
        tags = [tags]

    tag_map = {
        'wild-boar': 'Wild Boar', 'boar': 'Wild Boar',
        'deer': 'Red Deer', 'red-deer': 'Red Deer',
        'roe-deer': 'Roe Deer', 'fox': 'Red Fox',
        'rabbit': 'European Rabbit', 'hare': 'European Hare',
        'badger': 'European Badger', 'cat': 'Wildcat',
    }
    for t in tags:
        t_lower = t.lower().strip()
        if t_lower in tag_map:
            return tag_map[t_lower]
    return None


def classify_image(image_path):
    """Fallback for local images (no ML models available)."""
    return [{'species': 'unknown', 'common_name': 'Unknown',
             'confidence': 0.0, 'boar_category': None, 'bbox': None}]
