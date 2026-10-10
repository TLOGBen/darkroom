"""Opening photos and listing their folder (CONTRACT-layering L3, B8 / H7). Photos are only read.

Layer: services. Depends on domain (errors, messages, the extension table) and utils (`imaging.fingerprint`); the
Engine arrives through the `EngineRef` the composition hands in. Never imports the facade, adapters or config.

open_photo also computes the photo's fingerprint (content SHA-256, CONTRACT-photo-library PL2) and keeps it with the
opened image so previews resolve the photo library's preset snapshot without hashing again (PLP5).

`checked_photo_path`, `list_photos`, `read_error` and `known_engine` are this module's public helpers: the other
services (preview, export, photo library) use them so a photo path is judged by one rule with one set of sentences.

Side effects: reading photo files (open, hash) and listing folders; decoding happens on the GPU thread. Photos are
never written, moved or renamed.

Contract codes: L3 = path checks and their order (required -> exists -> supported extension) with fixed sentences;
B8 = a folder listing is sorted by name and says where the current photo is; H7 = HEIC counts as a photo; H13 = a
read failure's reason is one line, passed through unchanged; PL2 / PLP5 = the content fingerprint is computed once
at open time and reused by previews.
"""
import os

from ..domain import messages as M
from ..domain.errors import DarkroomError
from ..domain.formats import PHOTO_EXT     # the one extension table (CONTRACT-heic H7); torch-free (KP11, PLP8)
from ..utils.imaging import fingerprint
from . import on_gpu


def list_photos(folder):
    """[{"name", "path"}] of the supported photos in `folder`, sorted (casefold, name) - the one listing rule
    (B8 / H7; the thumbnail grid uses the same list, CONTRACT-photo-library PL13)."""
    names = [n for n in os.listdir(folder)
             if os.path.splitext(n)[1].lower() in PHOTO_EXT and os.path.isfile(os.path.join(folder, n))]
    names.sort(key=lambda n: (n.casefold(), n))
    return [{"name": n, "path": os.path.join(folder, n)} for n in names]


def folder_listing(path):
    """{"folder", "files", "index"}: the photos next to `path` and where `path` is among them (-1: not listed)."""
    folder = os.path.dirname(os.path.abspath(path))
    files = list_photos(folder)
    base = os.path.normcase(os.path.basename(path))
    index = next((i for i, f in enumerate(files) if os.path.normcase(f["name"]) == base), -1)
    return {"folder": folder, "files": files, "index": index}


def is_photo_name(path):
    """True when the file name has one of the supported photo extensions (H7). Export judges items with it."""
    return os.path.splitext(path)[1].lower() in PHOTO_EXT


def checked_photo_path(path):
    """L3's path checks, in order and with its sentences: the stripped path of an existing supported photo.

    Shared by open_photo and every photo library operation (CONTRACT-photo-library PL7, PLP8)."""
    if not isinstance(path, str) or not path.strip():
        raise DarkroomError("invalid", M.PATH_REQUIRED)
    path = path.strip().strip('"')
    if not os.path.isfile(path):
        raise DarkroomError("not_found", M.PHOTO_NOT_FOUND.format(path=path))
    if not is_photo_name(path):
        raise DarkroomError("invalid", M.UNSUPPORTED_FORMAT)
    return path


def read_error(path, e):
    """The invalid DarkroomError for a photo that could not be read (L3 / CONTRACT-heic H13)."""
    name, reason = os.path.basename(path), str(e)   # reason is single-line at the source
    return DarkroomError("invalid", M.OPEN_ERROR.format(file_name=name, reason=reason),
                         {"reason": reason, "file_name": name, "path": path})


def photo_fingerprint(path):
    """fingerprint(path), with a read failure worded as the photo's read error (L3)."""
    try:
        return fingerprint(path)
    except OSError as e:
        raise read_error(path, e) from None


def known_engine(engine_ref, image_id):
    """The Engine holding image_id, else DarkroomError not_found (never builds the Engine)."""
    eng = engine_ref.peek()
    if not isinstance(image_id, str) or eng is None or image_id not in eng.images:
        raise DarkroomError("not_found", M.UNKNOWN_IMAGE)
    return eng


def _open(eng, path):
    """Decode `path` into the Engine (runs on the GPU thread)."""
    return eng.open(path)          # eng.open is looked up at call time (mock.patch.object still applies)


class PhotoService:
    """open_photo and list_folder."""

    def __init__(self, engine_ref):
        """engine_ref: the shared EngineRef (the Engine is built on the first open_photo)."""
        self.engine_ref = engine_ref

    def open_photo(self, path):
        """Check the path, hash the file, decode it onto the GPU -> the Engine's info dict (image_id, sizes, ...).

        Raises invalid / not_found per checked_photo_path, invalid with the read error sentence when the file
        cannot be hashed or decoded. Reads the photo; writes nothing."""
        path = checked_photo_path(path)
        fp = photo_fingerprint(path)       # the one SHA-256 (PL2); computed here, not on the GPU thread
        eng = self.engine_ref.get()
        try:
            info = on_gpu(eng, _open, eng, path)
        except (OSError, ValueError) as e:
            raise read_error(path, e) from None
        eng.get(info["image_id"])["fingerprint"] = fp     # for resolve_params at preview time (PLP5; shape unchanged)
        return info

    def list_folder(self, image_id):
        """{folder, files, index} for the folder of an opened photo; not_found for an unknown image_id."""
        eng = known_engine(self.engine_ref, image_id)
        try:
            path = eng.get(image_id)["path"]
        except KeyError:
            raise DarkroomError("not_found", M.UNKNOWN_IMAGE) from None
        return folder_listing(path)
