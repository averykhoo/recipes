"""Regenerate the constellation figures embedded in static/3d-moon-widget.html.

The widget draws the constellation lines as ribbons connecting stars it is
already rendering, so the line data is stored as INDICES into the star
catalogue rather than as coordinates. That keeps it tiny (about 5 KB) and,
more usefully, guarantees the lines terminate exactly on the drawn stars --
there is no way for the two to drift apart.

    python scripts/make_constellation_data.py            # regenerate and re-embed
    python scripts/make_constellation_data.py --check    # verify the embedded copy

Run make_star_data.py first if the star catalogue has changed; the indices are
positions in ITS output ordering (sorted by right ascension, magnitude <= 6.5).

Source: d3-celestial (https://github.com/ofrohn/d3-celestial), BSD-3-Clause.
The figures themselves are the ones developed for the IAU by Alan MacRobert of
Sky & Telescope. Every vertex in that file is a real star: snapping them to the
Yale catalogue moves them by 0.0001 deg at the median and 0.0084 deg at worst.
"""
import argparse
import json
import math
import os
import re
import sys
import urllib.request

import make_star_data as stars_module

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'constellations.lines.json')
WIDGET = os.path.join(HERE, os.pardir, '.jekyll-build', 'static', '3d-moon-widget.html')
SOURCE_URL = ('https://raw.githubusercontent.com/ofrohn/d3-celestial/'
              'master/data/constellations.lines.json')

# A vertex further than this from any catalogue star means the two data sets have
# drifted apart and the figures would be drawn between the wrong stars.
MAX_SNAP_DEGREES = 0.05


def fetch_lines():
    if not os.path.exists(CACHE):
        print('downloading %s' % SOURCE_URL)
        with urllib.request.urlopen(SOURCE_URL) as r, open(CACHE, 'wb') as f:
            f.write(r.read())
    return json.load(open(CACHE, encoding='utf-8'))


def angular_separation(ra1, dec1, ra2, dec2):
    """Small-angle separation in degrees; fine at the scales we snap over."""
    dra = ((ra1 - ra2 + 180) % 360 - 180) * math.cos(math.radians(dec1))
    return math.hypot(dra, dec1 - dec2)


def build(features, stars):
    """Snap every vertex to its catalogue star and emit index polylines."""
    # bucket the stars by whole degree of RA so the snap is not O(vertices * stars)
    buckets = {}
    for i, (ra, dec, _, _) in enumerate(stars):
        buckets.setdefault(int(ra), []).append(i)

    ids, lines, snaps = [], [], []
    for feature in sorted(features, key=lambda f: f['id']):
        cid = len(ids)
        ids.append(feature['id'])
        geometry = feature['geometry']
        polylines = (geometry['coordinates'] if geometry['type'] == 'MultiLineString'
                     else [geometry['coordinates']])
        for polyline in polylines:
            indices = []
            for lon, lat in polyline:
                ra = lon % 360.0
                candidates = []
                for d in (-1, 0, 1):
                    candidates += buckets.get(int(ra) + d, [])
                    candidates += buckets.get((int(ra) + d) % 360, [])
                best = min(candidates,
                           key=lambda i: angular_separation(ra, lat, stars[i][0], stars[i][1]))
                sep = angular_separation(ra, lat, stars[best][0], stars[best][1])
                if sep > MAX_SNAP_DEGREES:
                    raise SystemExit(
                        'vertex (%.3f, %.3f) in %s is %.3f deg from the nearest catalogue '
                        'star -- the two data sets disagree' % (ra, lat, feature['id'], sep))
                snaps.append(sep)
                if not indices or indices[-1] != best:      # drop repeated vertices
                    indices.append(best)
            if len(indices) >= 2:
                lines.append([cid] + indices)
    return {'format': 'constellation-lines-1', 'ids': ids, 'lines': lines}, snaps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()

    stars = stars_module.read_stars(stars_module.fetch_catalogue())
    payload, snaps = build(fetch_lines()['features'], stars)
    encoded = json.dumps(payload, separators=(',', ':'))
    assert "'" not in encoded and '\\' not in encoded and '\n' not in encoded

    segments = sum(len(l) - 2 for l in payload['lines'])
    snaps.sort()
    print('%d constellations, %d polylines, %d segments, %.1f KB of JSON'
          % (len(payload['ids']), len(payload['lines']), segments, len(encoded) / 1024))
    print('snap distance: median %.4f deg, max %.4f deg'
          % (snaps[len(snaps) // 2], snaps[-1]))

    html = open(WIDGET, encoding='utf-8').read()
    pattern = re.compile(r"(const CONSTELLATION_LINES_JSON = ')[^']*(';)")
    if not pattern.search(html):
        raise SystemExit('could not find CONSTELLATION_LINES_JSON in %s' % WIDGET)
    current = pattern.search(html).group(0)[len("const CONSTELLATION_LINES_JSON = '"):-2]

    if args.check:
        if current != encoded:
            print('EMBEDDED DATA IS STALE: re-run without --check')
            return 1
        print('embedded data is current')
        return 0

    if current == encoded:
        print('embedded data already current, nothing to do')
        return 0
    open(WIDGET, 'w', encoding='utf-8', newline='').write(
        pattern.sub(lambda m: m.group(1) + encoded + m.group(2), html))
    print('re-embedded into %s' % os.path.normpath(WIDGET))
    return 0


if __name__ == '__main__':
    sys.exit(main())
