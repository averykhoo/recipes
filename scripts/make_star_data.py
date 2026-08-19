"""Regenerate the star catalogue embedded in static/3d-moon-widget.html.

The widget draws the real naked-eye sky. The star data is produced here and
spliced into the widget as a single JSON string; the format is documented in
the widget itself, above parseStarCatalogue(). This script is the only
producer, so if the layout changes, change it in both places.

    python scripts/make_star_data.py            # regenerate and re-embed
    python scripts/make_star_data.py --check    # verify the embedded data matches

Source: Yale Bright Star Catalog, 5th ed. (BSC5 binary form), from
http://tdc-www.harvard.edu/catalogs/bsc5.html -- public domain. A copy is
cached next to this script so the build does not depend on the network.
"""
import argparse
import json
import math
import os
import re
import struct
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'BSC5')
WIDGET = os.path.join(HERE, os.pardir, '.jekyll-build', 'static', '3d-moon-widget.html')
SOURCE_URL = 'http://tdc-www.harvard.edu/catalogs/BSC5'

MAG_LIMIT = 6.5      # the naked-eye limit under a dark sky

# Spectral class -> the seven buckets the widget knows how to colour. Anything
# exotic folds onto its nearest temperature neighbour so the renderer never has
# to handle a surprise letter.
SPECTRAL_FOLD = {'O': 'O', 'W': 'O', 'B': 'B', 'A': 'A', 'F': 'F', 'G': 'G',
                 'K': 'K', 'M': 'M', 'C': 'M', 'S': 'M', 'N': 'M', 'R': 'M'}


def fetch_catalogue():
    if not os.path.exists(CACHE):
        print('downloading %s' % SOURCE_URL)
        with urllib.request.urlopen(SOURCE_URL) as r, open(CACHE, 'wb') as f:
            f.write(r.read())
    return open(CACHE, 'rb').read()


def read_stars(raw):
    """Parse the BSC5 binary form: a 28-byte header then fixed-size entries."""
    star0, star1, starn, stnum, mprop, nmag, nbent = struct.unpack('<7i', raw[:28])
    if 28 + abs(starn) * nbent != len(raw):
        raise SystemExit('BSC5 is not the size its header claims; delete %s and retry' % CACHE)

    stars = []
    for i in range(abs(starn)):
        off = 28 + i * nbent
        xno, ra_rad, dec_rad = struct.unpack('<fdd', raw[off:off + 20])
        spectral = raw[off + 20:off + 22].decode('latin1')
        mag = struct.unpack('<h', raw[off + 22:off + 24])[0] / 100.0
        if mag == 0 and ra_rad == 0:       # blanked entries (novae removed from the catalogue)
            continue
        if mag > MAG_LIMIT:
            continue
        stars.append((math.degrees(ra_rad) % 360.0, math.degrees(dec_rad), mag,
                      SPECTRAL_FOLD.get(spectral[0].upper(), 'A')))
    stars.sort()                            # by RA, so the deltas below stay small
    return stars


def build_payload(stars):
    """Columnar, integer-scaled, RA-delta-encoded. See the widget for why."""
    deltas, previous = [], 0
    for ra, _, _, _ in stars:
        scaled = int(round(ra * 100))
        deltas.append(scaled - previous)
        previous = scaled
    return {
        'format': 'bsc5-columnar-1',
        'epoch': 'J2000',
        'count': len(stars),
        'magLimit': MAG_LIMIT,
        'dra': deltas,
        'dec': [int(round(d * 100)) for _, d, _, _ in stars],
        'mag': [int(round((m + 2) * 20)) for _, _, m, _ in stars],
        'cls': ''.join(c for _, _, _, c in stars),
    }


def verify(payload, stars):
    """Decode exactly as the widget does and confirm we get the catalogue back."""
    ra, worst = 0, [0.0, 0.0, 0.0]
    for i in range(payload['count']):
        ra += payload['dra'][i]
        worst[0] = max(worst[0], abs(ra / 100.0 - stars[i][0]))
        worst[1] = max(worst[1], abs(payload['dec'][i] / 100.0 - stars[i][1]))
        worst[2] = max(worst[2], abs(payload['mag'][i] / 20.0 - 2 - stars[i][2]))
    # One pixel is ~0.04 deg at a 60 deg field, so 0.01 deg of quantisation is invisible.
    assert worst[0] <= 0.006 and worst[1] <= 0.006, 'round trip lost position: %s' % worst
    assert worst[2] <= 0.03, 'round trip lost magnitude: %s' % worst
    return worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true',
                    help='verify the embedded data is current instead of rewriting it')
    args = ap.parse_args()

    stars = read_stars(fetch_catalogue())
    payload = build_payload(stars)
    worst = verify(payload, stars)
    encoded = json.dumps(payload, separators=(',', ':'))
    # It is embedded in a single-quoted JS string literal, so it must not contain
    # anything needing escapes. Digits, commas, brackets, double quotes, OBAFGKM.
    assert "'" not in encoded and '\\' not in encoded and '\n' not in encoded

    print('%d stars to magnitude %.1f, %.1f KB of JSON' % (len(stars), MAG_LIMIT, len(encoded) / 1024))
    print('round trip worst error: %.4f deg RA, %.4f deg Dec, %.3f mag' % tuple(worst))

    html = open(WIDGET, encoding='utf-8').read()
    pattern = re.compile(r"(const STAR_CATALOGUE_JSON = ')[^']*(';)")
    if not pattern.search(html):
        raise SystemExit('could not find STAR_CATALOGUE_JSON in %s' % WIDGET)
    current = pattern.search(html).group(0)[len("const STAR_CATALOGUE_JSON = '"):-2]

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
