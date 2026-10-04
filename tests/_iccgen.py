"""Build small matrix/TRC ICC v4 profiles for tests (Display P3 with the sRGB tone curve).

Colorants are the D50-adapted (Bradford) Display P3 primaries, as in Apple's Display P3 profile; the tone
curve is a parametricCurveType function 3 with the sRGB constants. Written out here independently of the
reader in darkroom._icc.
"""
import struct

D50 = (0.9642, 1.0, 0.8249)
P3_COLORANTS = {"r": (0.515121, 0.241196, -0.001053),
                "g": (0.291977, 0.692245, 0.041885),
                "b": (0.157104, 0.066574, 0.784073)}
SRGB_PARA = (2.4, 1 / 1.055, 0.055 / 1.055, 1 / 12.92, 0.04045)


def _s15(v):
    return struct.pack(">i", int(round(v * 65536)))


def _xyz(xyz):
    return b"XYZ " + b"\0" * 4 + b"".join(_s15(v) for v in xyz)


def _para(params):
    return b"para" + b"\0" * 4 + struct.pack(">HH", 3, 0) + b"".join(_s15(v) for v in params)


def _mluc(text):
    enc = text.encode("utf-16-be")
    return (b"mluc" + b"\0" * 4 + struct.pack(">II", 1, 12) + b"enUS" + struct.pack(">II", len(enc), 28) + enc)


def _pad(b):
    return b + b"\0" * (-len(b) % 4)


def matrix_trc_profile(colorants=P3_COLORANTS, para=SRGB_PARA, name="Display P3 (test)"):
    curve = _para(para)
    tags = [(b"desc", _mluc(name)), (b"cprt", _mluc("test profile, no copyright")), (b"wtpt", _xyz(D50)),
            (b"rXYZ", _xyz(colorants["r"])), (b"gXYZ", _xyz(colorants["g"])), (b"bXYZ", _xyz(colorants["b"])),
            (b"rTRC", curve), (b"gTRC", curve), (b"bTRC", curve)]
    table_len = 4 + 12 * len(tags)
    offset = 128 + table_len
    entries, data = [], b""
    for sig, body in tags:
        entries.append(struct.pack(">4sII", sig, offset + len(data), len(body)))
        data += _pad(body)
    size = 128 + table_len + len(data)
    header = (struct.pack(">I", size) + b"lcms" + struct.pack(">I", 0x04300000) + b"mntr" + b"RGB " + b"XYZ "
              + b"\0" * 12 + b"acsp" + b"\0" * 4 + b"\0" * 4 + b"\0" * 8 + b"\0" * 8 + b"\0" * 4
              + b"".join(_s15(v) for v in D50) + b"\0" * 4 + b"\0" * 16 + b"\0" * 28)
    assert len(header) == 128, len(header)
    return header + struct.pack(">I", len(tags)) + b"".join(entries) + data


def display_p3():
    return matrix_trc_profile()
