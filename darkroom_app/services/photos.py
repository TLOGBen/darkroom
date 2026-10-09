"""Opening photos and listing their folder (CONTRACT-layering L3, B8 / H7). Photos are only read."""
import os

from .. import messages as M
from ..errors import DarkroomError
from . import on_gpu


def _photo_ext():
    from ..engine import PHOTO_EXT   # the one extension table (CONTRACT-heic H7)
    return PHOTO_EXT


def folder_listing(path):
    ext = _photo_ext()
    folder = os.path.dirname(os.path.abspath(path))
    names = [n for n in os.listdir(folder)
             if os.path.splitext(n)[1].lower() in ext and os.path.isfile(os.path.join(folder, n))]
    names.sort(key=lambda n: (n.casefold(), n))
    files = [{"name": n, "path": os.path.join(folder, n)} for n in names]
    base = os.path.normcase(os.path.basename(path))
    index = next((i for i, n in enumerate(names) if os.path.normcase(n) == base), -1)
    return {"folder": folder, "files": files, "index": index}


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
        if not isinstance(path, str) or not path.strip():
            raise DarkroomError("invalid", M.PATH_REQUIRED)
        path = path.strip().strip('"')
        if not os.path.isfile(path):
            raise DarkroomError("not_found", M.PHOTO_NOT_FOUND.format(path=path))
        if os.path.splitext(path)[1].lower() not in _photo_ext():
            raise DarkroomError("invalid", M.UNSUPPORTED_FORMAT)
        eng = self.engine_ref.get()
        try:
            return on_gpu(eng, _open, eng, path)
        except (OSError, ValueError) as e:
            name, reason = os.path.basename(path), str(e)   # reason is single-line at the source (CONTRACT-heic H13)
            raise DarkroomError("invalid", M.OPEN_ERROR.format(file_name=name, reason=reason),
                                {"reason": reason, "file_name": name, "path": path}) from None

    def list_folder(self, image_id):
        eng = known_engine(self.engine_ref, image_id)
        try:
            path = eng.get(image_id)["path"]
        except KeyError:
            raise DarkroomError("not_found", M.UNKNOWN_IMAGE) from None
        return folder_listing(path)
