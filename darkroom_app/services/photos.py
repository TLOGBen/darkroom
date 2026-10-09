"""Opening photos and listing their folder (CONTRACT-layering L3, B8 / H7). Photos are only read.

open_photo also computes the photo's fingerprint (content SHA-256, CONTRACT-photo-library PL2) and keeps it with the
opened image so previews resolve the photo library's preset snapshot without hashing again (PLP5).
"""
import os

from .. import messages as M
from ..errors import DarkroomError
from . import on_gpu


def _photo_ext():
    from ..formats import PHOTO_EXT   # the one extension table (CONTRACT-heic H7); engine.PHOTO_EXT is this tuple
    return PHOTO_EXT                  # (KP11: torch-free, so the edit / thumbnails CLI commands stay light, PLP8)


def list_photos(folder):
    """[{"name", "path"}] of the supported photos in `folder`, sorted (casefold, name) - the one listing rule
    (B8 / H7; the thumbnail grid uses the same list, CONTRACT-photo-library PL13)."""
    ext = _photo_ext()
    names = [n for n in os.listdir(folder)
             if os.path.splitext(n)[1].lower() in ext and os.path.isfile(os.path.join(folder, n))]
    names.sort(key=lambda n: (n.casefold(), n))
    return [{"name": n, "path": os.path.join(folder, n)} for n in names]


def folder_listing(path):
    folder = os.path.dirname(os.path.abspath(path))
    files = list_photos(folder)
    base = os.path.normcase(os.path.basename(path))
    index = next((i for i, f in enumerate(files) if os.path.normcase(f["name"]) == base), -1)
    return {"folder": folder, "files": files, "index": index}


def checked_photo_path(path):
    """L3's path checks, in order and with its sentences: the stripped path of an existing supported photo.

    Shared by open_photo and every photo library operation (CONTRACT-photo-library PL7, PLP8)."""
    if not isinstance(path, str) or not path.strip():
        raise DarkroomError("invalid", M.PATH_REQUIRED)
    path = path.strip().strip('"')
    if not os.path.isfile(path):
        raise DarkroomError("not_found", M.PHOTO_NOT_FOUND.format(path=path))
    if os.path.splitext(path)[1].lower() not in _photo_ext():
        raise DarkroomError("invalid", M.UNSUPPORTED_FORMAT)
    return path


def read_error(path, e):
    """The invalid DarkroomError for a photo that could not be read (L3 / CONTRACT-heic H13)."""
    name, reason = os.path.basename(path), str(e)   # reason is single-line at the source
    return DarkroomError("invalid", M.OPEN_ERROR.format(file_name=name, reason=reason),
                         {"reason": reason, "file_name": name, "path": path})


def known_engine(engine_ref, image_id):
    """The Engine holding image_id, else DarkroomError not_found (never builds the Engine)."""
    eng = engine_ref.peek()
    if not isinstance(image_id, str) or eng is None or image_id not in eng.images:
        raise DarkroomError("not_found", M.UNKNOWN_IMAGE)
    return eng


def _open(eng, path):
    return eng.open(path)          # eng.open is looked up at call time (mock.patch.object still applies)


class PhotoService:
    def __init__(self, engine_ref):
        self.engine_ref = engine_ref

    def open_photo(self, path):
        path = checked_photo_path(path)
        from .photo_library import fingerprint      # the one SHA-256 (PL2); computed here, not on the GPU thread
        try:
            fp = fingerprint(path)
        except OSError as e:
            raise read_error(path, e) from None
        eng = self.engine_ref.get()
        try:
            info = on_gpu(eng, _open, eng, path)
        except (OSError, ValueError) as e:
            raise read_error(path, e) from None
        eng.get(info["image_id"])["fingerprint"] = fp     # for resolve_params at preview time (PLP5; shape unchanged)
        return info

    def list_folder(self, image_id):
        eng = known_engine(self.engine_ref, image_id)
        try:
            path = eng.get(image_id)["path"]
        except KeyError:
            raise DarkroomError("not_found", M.UNKNOWN_IMAGE) from None
        return folder_listing(path)
