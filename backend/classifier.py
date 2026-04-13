"""
VA GameTracker - Species classification via HuggingFace Inference API

Uses HuggingFace's free inference API with google/vit-base-patch16-224
to classify camera trap photos. Maps ImageNet labels to Spanish mammals.
No API key needed for public models.
"""
import requests

# ImageNet labels → Spanish mammal mapping
# vit-base-patch16-224 uses ImageNet-1k labels
IMAGENET_TO_SPANISH = {
    'wild boar': 'Wild Boar',
    'boar': 'Wild Boar',
    'hog': 'Wild Boar',
    'warthog': 'Wild Boar',
    'sus scrofa': 'Wild Boar',
    'red fox': 'Red Fox',
    'fox': 'Red Fox',
    'grey fox': 'Red Fox',
    'kit fox': 'Red Fox',
    'arctic fox': 'Red Fox',
    'rabbit': 'European Rabbit',
    'hare': 'European Hare',
    'wood rabbit': 'European Rabbit',
    'cottontail': 'European Rabbit',
    'angora': 'European Rabbit',
    'badger': 'European Badger',
    'lynx': 'Iberian Lynx',
    'tabby': 'Wildcat',
    'tiger cat': 'Wildcat',
    'egyptian cat': 'Wildcat',
    'persian cat': 'Wildcat',
    'weasel': 'Least Weasel',
    'mink': 'European Polecat',
    'polecat': 'European Polecat',
    'ferret': 'European Polecat',
    'black-footed ferret': 'European Polecat',
    'otter': 'European Otter',
    'mongoose': 'Egyptian Mongoose',
    'meerkat': 'Egyptian Mongoose',
    'brown bear': 'Brown Bear',
    'ice bear': 'Brown Bear',
    'american black bear': 'Brown Bear',
    'sloth bear': 'Brown Bear',
    'wolf': 'Iberian Wolf',
    'timber wolf': 'Iberian Wolf',
    'red wolf': 'Iberian Wolf',
    'coyote': 'Iberian Wolf',
    'dingo': 'Iberian Wolf',
    'german shepherd': 'Dog',
    'golden retriever': 'Dog',
    'labrador retriever': 'Dog',
    'ibex': 'Iberian Ibex',
    'bighorn': 'Iberian Ibex',
    'ram': 'Mouflon',
    'impala': 'Red Deer',
    'hartebeest': 'Red Deer',
    'gazelle': 'Roe Deer',
    'ox': 'Cattle',
    'water buffalo': 'Cattle',
    'bison': 'Cattle',
    'sorrel': 'Horse',
    'hedgehog': 'European Hedgehog',
    'porcupine': 'European Hedgehog',
    'squirrel': 'Red Squirrel',
    'hamster': 'Small Mammal',
    'guinea pig': 'Small Mammal',
    'mouse': 'Small Mammal',
    'jay': 'Bird',
    'magpie': 'Bird',
    'chickadee': 'Bird',
    'robin': 'Bird',
    'vulture': 'Raptor',
    'bald eagle': 'Golden Eagle',
    'kite': 'Raptor',
    'hen': 'Bird',
    'cock': 'Bird',
    'ostrich': 'Bird',
    'peacock': 'Bird',
}

# Non-animal labels to skip
SKIP_LABELS = {
    'fence', 'chain link fence', 'picket fence', 'stone wall', 'cliff',
    'valley', 'lakeside', 'seashore', 'promontory', 'sandbar',
    'hay', 'corn', 'mushroom', 'acorn', 'hip', 'buckeye',
    'caldron', 'chainlink fence', 'barbwire', 'spider web',
}

# Species we track as priority
PRIORITY_SPECIES = {
    'Wild Boar': 'sus_scrofa',
    'Red Deer': 'cervus_elaphus',
    'Roe Deer': 'capreolus_capreolus',
    'Red Fox': 'vulpes_vulpes',
    'European Rabbit': 'oryctolagus_cuniculus',
    'European Badger': 'meles_meles',
    'Wildcat': 'felis_silvestris',
    'Common Genet': 'genetta_genetta',
    'European Hare': 'lepus_europaeus',
    'Mouflon': 'ovis_aries_musimon',
    'Iberian Ibex': 'capra_pyrenaica',
}

BOAR_CATEGORIES = ['Big Boar', 'Sow', 'Juvenile', 'Piglet']

HF_API_URL = 'https://api-inference.huggingface.co/models/google/vit-base-patch16-224'


def classify_from_url(image_url, min_confidence=0.10):
    """
    Download image and classify via HuggingFace Inference API.
    Returns: (species_name, confidence) or ('Unknown', 0.0)
    """
    if not image_url or not image_url.startswith('http'):
        return 'Unknown', 0.0

    try:
        # Download image from Spypoint CDN
        img_resp = requests.get(image_url, timeout=15)
        if img_resp.status_code != 200:
            print(f"[classifier] Image download failed: {img_resp.status_code}")
            return 'Unknown', 0.0

        img_data = img_resp.content
        if len(img_data) < 1000:
            return 'Unknown', 0.0

        # Send to HuggingFace
        resp = requests.post(HF_API_URL, data=img_data, timeout=30)

        if resp.status_code == 503:
            # Model is loading, retry after delay
            print("[classifier] HF model loading, will retry next sync")
            return 'Unknown', 0.0
        if resp.status_code != 200:
            print(f"[classifier] HF API error: {resp.status_code}")
            return 'Unknown', 0.0

        results = resp.json()
        if isinstance(results, dict) and 'error' in results:
            print(f"[classifier] HF error: {results['error']}")
            return 'Unknown', 0.0

        # Find best matching mammal
        for r in results:
            label = r.get('label', '').lower()
            score = r.get('score', 0)

            if score < min_confidence:
                continue
            if label in SKIP_LABELS:
                continue

            # Check direct mapping
            for key, species in IMAGENET_TO_SPANISH.items():
                if key in label or label in key:
                    return species, score

        return 'Unknown', 0.0

    except Exception as e:
        print(f"[classifier] Classification error: {e}")
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
    """Fallback for local images."""
    return [{'species': 'unknown', 'common_name': 'Unknown',
             'confidence': 0.0, 'boar_category': None, 'bbox': None}]
