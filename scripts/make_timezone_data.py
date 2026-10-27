"""Regenerate the timezone -> location table embedded in static/3d-moon-widget.html.

"Lock to the real Moon" needs to know where you are, because the Moon's tilt
depends on it. Rather than prompt for geolocation, the widget reads the
browser's IANA timezone (Intl.DateTimeFormat().resolvedOptions().timeZone,
e.g. "Europe/Budapest") and looks up that zone's principal city here. The same
table fills the place picker in the settings panel. This script is the only
producer, so if the layout changes, change parseTimezoneTable() in the widget too.

    python scripts/make_timezone_data.py            # regenerate and re-embed
    python scripts/make_timezone_data.py --check    # verify the embedded data matches

Source: the IANA tz database (public domain).
  zone.tab     one row per country-zone: country, coordinates, zone, comment.
               Preferred over zone1970.tab (which it contains) because it still
               lists zones like Europe/Oslo that newer releases fold into
               Europe/Berlin, and Oslo is a thousand kilometres from Berlin.
  iso3166.tab  country names for the picker.
  backward     old names browsers still report (Asia/Calcutta, Europe/Kiev,
               US/Eastern), mapped onto current zones.
The release is pinned so --check gives the same answer next year, and a copy is
cached next to this script so the build does not need the network.
"""
import argparse
import json
import os
import re
import sys
import tarfile
import urllib.request

TZDATA_VERSION = '2026e'
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'tzdata%s.tar.gz' % TZDATA_VERSION)
WIDGET = os.path.join(HERE, os.pardir, '.jekyll-build', 'static', '3d-moon-widget.html')
SOURCE_URL = 'https://data.iana.org/time-zones/releases/tzdata%s.tar.gz' % TZDATA_VERSION


def fetch_tzdata():
    if not os.path.exists(CACHE):
        print('downloading %s' % SOURCE_URL)
        with urllib.request.urlopen(SOURCE_URL) as r, open(CACHE, 'wb') as f:
            f.write(r.read())
    files = {}
    with tarfile.open(CACHE, 'r:gz') as tar:
        for name in ('version', 'zone.tab', 'iso3166.tab', 'backward'):
            files[name] = tar.extractfile(name).read().decode('utf-8')
    if files['version'].strip() != TZDATA_VERSION:
        raise SystemExit('%s says it is %r; delete it and retry' % (CACHE, files['version'].strip()))
    return files


def parse_iso6709(text):
    """'+4730+01905' or '+404251-0740023' -> (lat, lon) in degrees."""
    m = re.fullmatch(r'([+-])(\d{2})(\d{2})(\d{2})?([+-])(\d{3})(\d{2})(\d{2})?', text)
    if not m:
        raise ValueError('bad coordinates %r' % text)
    sl, dl, ml, xl, so, do, mo, xo = m.groups()
    lat = int(dl) + int(ml) / 60 + int(xl or 0) / 3600
    lon = int(do) + int(mo) / 60 + int(xo or 0) / 3600
    return (-lat if sl == '-' else lat), (-lon if so == '-' else lon)


def rows(text):
    for line in text.splitlines():
        if line and not line.startswith('#'):
            yield line.split('\t')


def read_zones(text):
    """zone.tab -> {zone: (lat, lon, country, comment)}."""
    out = {}
    for cols in rows(text):
        lat, lon = parse_iso6709(cols[1])
        out[cols[2]] = (lat, lon, cols[0], cols[3] if len(cols) > 3 else '')
    return out


def read_links(text):
    """`backward` -> {old name: target}."""
    links = {}
    for line in text.splitlines():
        cols = line.split()
        if len(cols) >= 3 and cols[0] == 'Link':
            links[cols[2]] = cols[1]
    return links


def resolve_links(links, zones):
    """Old name -> a zone in the table, following chains; unresolvable ones dropped."""
    out = {}
    for alias, target in links.items():
        if alias in zones:
            continue
        seen = set()
        while target not in zones and target not in seen:
            seen.add(target)
            target = links.get(target, target)
        if target in zones:
            out[alias] = target
    return out


def build_payload(files):
    """Coordinates in hundredths of a degree (~1 km): far finer than a timezone."""
    zones = read_zones(files['zone.tab'])
    countries = {cols[0]: cols[1] for cols in rows(files['iso3166.tab'])}
    used = sorted({c for _, _, c, _ in zones.values()})
    missing = [c for c in used if c not in countries]
    assert not missing, 'zone.tab uses country codes iso3166.tab lacks: %s' % missing
    return {
        'format': 'tz-coords-2',
        'tzdata': TZDATA_VERSION,
        'zones': {z: [int(round(lat * 100)), int(round(lon * 100)), cc] + ([note] if note else [])
                  for z, (lat, lon, cc, note) in sorted(zones.items())},
        'links': dict(sorted(resolve_links(read_links(files['backward']), zones).items())),
        'countries': {c: countries[c] for c in used},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true',
                    help='verify the embedded data is current instead of rewriting it')
    args = ap.parse_args()

    payload = build_payload(fetch_tzdata())
    # It is embedded in a single-quoted JS string literal, which JS unescapes before
    # JSON.parse sees it. \uXXXX survives that intact (a JS escape decoding to the
    # same character JSON wanted), so write every awkward character that way:
    # non-ASCII (Reunion, Aland) via ensure_ascii, and the apostrophe ("Dumont-
    # d'Urville") by hand. Any other backslash escape (\" \\ \n) would be mangled.
    encoded = json.dumps(payload, separators=(',', ':'), ensure_ascii=True).replace("'", '\\u0027')
    assert "'" not in encoded and not re.search(r'\\(?!u[0-9a-f]{4})', encoded)

    print('%d zones, %d old names, %d countries from tzdata %s, %.1f KB of JSON' % (
        len(payload['zones']), len(payload['links']), len(payload['countries']),
        TZDATA_VERSION, len(encoded) / 1024))

    html = open(WIDGET, encoding='utf-8').read()
    pattern = re.compile(r"(const TIMEZONE_COORDS_JSON = ')[^']*(';)")
    if not pattern.search(html):
        raise SystemExit('could not find TIMEZONE_COORDS_JSON in %s' % WIDGET)
    current = pattern.search(html).group(0)[len("const TIMEZONE_COORDS_JSON = '"):-2]

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
