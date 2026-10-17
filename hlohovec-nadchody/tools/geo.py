"""Shared geodesy helpers: local ENU frame centred on the Hlohovec roundabout."""
import math

# Origin = centre of the roundabout at Hlohová / Námestie sv. Michala / SNP (OSM way 909068638)
LAT0, LON0 = 48.42790, 17.79614
_R = 6378137.0
_COS0 = math.cos(math.radians(LAT0))


def merc(lat, lon):
    """WGS84 -> Web-Mercator metres."""
    x = math.radians(lon) * _R
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * _R
    return x, y


_MX0, _MY0 = merc(LAT0, LON0)


def to_local(lat, lon):
    """WGS84 -> local metres (east, north) relative to origin (mercator scaled to ground)."""
    x, y = merc(lat, lon)
    return (x - _MX0) * _COS0, (y - _MY0) * _COS0


def tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def tile_to_local(tx, ty, z):
    """Fractional tile coordinate -> local metres."""
    n = 2 ** z
    mx = (tx / n * 2 - 1) * math.pi * _R
    my = (1 - ty / n * 2) * math.pi * _R
    return (mx - _MX0) * _COS0, (my - _MY0) * _COS0


def local_to_tile(e, n_, z):
    mx = e / _COS0 + _MX0
    my = n_ / _COS0 + _MY0
    n = 2 ** z
    return (mx / (math.pi * _R) + 1) / 2 * n, (1 - my / (math.pi * _R)) / 2 * n
