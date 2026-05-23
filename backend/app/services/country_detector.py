"""Offline country detection using Natural Earth polygons and a Shapely STRtree."""
import json
import logging

from shapely.geometry import Point, shape
from shapely.strtree import STRtree

logger = logging.getLogger(__name__)


class CountryDetector:
    def __init__(self, geojson_path: str):
        self._geometries = []   # list of shapely shapes
        self._codes = []        # parallel list of ISO codes
        self._tree = None
        self._load(geojson_path)

    def _load(self, path: str):
        with open(path) as f:
            fc = json.load(f)
        for feat in fc["features"]:
            props = feat["properties"]
            # Natural Earth uses "ISO_A2" or "ADM0_A2"
            code = props.get("ISO_A2") or props.get("ADM0_A2") or "??"
            if code in ("-99", "??", ""):
                code = props.get("ADM0_ISO") or props.get("NAME_ZH") or "??"
            try:
                geom = shape(feat["geometry"])
                self._geometries.append(geom)
                self._codes.append(code)
            except Exception as e:
                logger.debug(f"Skipping country {code}: {e}")
        self._tree = STRtree(self._geometries)
        logger.info(f"Loaded {len(self._geometries)} country polygons")

    def lookup(self, lat: float, lon: float) -> str:
        pt = Point(lon, lat)   # shapely uses (x=lon, y=lat)
        candidates = self._tree.query(pt)
        for idx in candidates:
            if self._geometries[idx].contains(pt):
                return self._codes[idx]
        return "SEA"
