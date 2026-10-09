"""Child entry for every python the tests start (CONTRACT-write-guard G6).

    python -s tests/_guardrun.py --roots JSON --report DIR --test-id ID (-m module | -c code) [args...]

Build the prefix with `_writeguard.python_cmd()` (`_util.guarded_python()`). The write guard is armed first, with the
writable roots the parent declared, then the module or code runs like `python -m` / `python -c` would. A violation
writes its constant first line plus stack to stderr and the process exits 86; the parent test also turns red because
the violation is appended to the parent's report folder.
"""
import importlib.util
import os
import runpy
import sys

_spec = importlib.util.spec_from_file_location("_writeguard", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                           "_writeguard.py"))
_writeguard = importlib.util.module_from_spec(_spec)
sys.modules["_writeguard"] = _writeguard
_spec.loader.exec_module(_writeguard)          # arms the hook (child mode: sys.argv[0] is this file)


def _run(rest):
    if len(rest) >= 2 and rest[0] == "-m":
        sys.argv = [rest[1], *rest[2:]]
        runpy.run_module(rest[1], run_name="__main__", alter_sys=True)
    elif len(rest) >= 2 and rest[0] == "-c":
        sys.argv = ["-c", *rest[2:]]
        exec(compile(rest[1], "<string>", "exec"), {"__name__": "__main__", "__builtins__": __builtins__})
    else:
        raise SystemExit("usage: _guardrun.py --roots J --report D --test-id T (-m module | -c code) [args...]")


def main():
    code = 0
    try:
        _run(sys.argv[7:])
    except SystemExit as e:
        code = e.code
    except _writeguard.WriteGuardViolation:
        code = 1
    except BaseException:
        import traceback
        traceback.print_exc()
        code = 1
    if _writeguard.child_exit_code() is not None:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except (OSError, ValueError):
                pass
        os.write(2, (_writeguard.first_violation_text() + "\n").encode("utf-8"))
        os._exit(_writeguard.CHILD_EXIT)
    if code is None or isinstance(code, int):
        sys.exit(code)
    print(code, file=sys.stderr)
    sys.exit(1)


main()
