"""Start the real darkroom App (`python -s -m darkroom_app`) with an order gate on the photo-library edit reads.

Verification scaffolding for /prove-it, never product code. Usage (run from any folder):

    <darkroom python> -s .claude/prove-it/tools/gated_app.py --repo <checkout> --gate-dir <dir> -- <darkroom_app args>

<checkout> is the source tree whose darkroom_app is run (a worktree of another commit works). The App is the
unchanged `darkroom_app.__main__.main`; the only addition is a gate after three EditStore reads, used to force the
order a hypothesis path describes:

* gate "P1": after `EditStore.read_previous` returns (restore_edit has read the current and the previous edit);
* gate "P2": after `EditStore.read` returns None, or `EditStore.exists` returns False (clear_edit has seen "no edit").

A gate fires once per arming and only when `<gate-dir>/arm-<gate>` exists (the driver creates it; the gate removes
it). It then writes `<gate-dir>/paused-<gate>` (which read paused it), waits until `<gate-dir>/go-<gate>` exists
(at most 60 s), writes `<gate-dir>/resumed-<gate>`, and returns the read's own result unchanged. Nothing else in the
App is touched; with no arm file the App behaves exactly as the checkout's code.
"""
import argparse
import os
import sys
import time

WAIT_S = 60.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--gate-dir", required=True)
    ap.add_argument("rest", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    gate_dir = os.path.abspath(a.gate_dir)
    rest = a.rest[1:] if a.rest[:1] == ["--"] else a.rest
    sys.path.insert(0, repo)

    import darkroom_app
    from darkroom_app.adapters.persist import edit_store

    with open(os.path.join(gate_dir, "app-module.txt"), "w", encoding="utf-8") as f:
        f.write(os.path.abspath(darkroom_app.__file__) + "\n")     # doctor: which checkout is being run

    def consume(gate):
        try:
            os.remove(os.path.join(gate_dir, "arm-" + gate))
            return True
        except FileNotFoundError:
            return False

    def hold(gate, what):
        with open(os.path.join(gate_dir, "paused-" + gate), "w", encoding="utf-8") as f:
            f.write(f"{what} {time.time():.3f}\n")
        go = os.path.join(gate_dir, "go-" + gate)
        deadline = time.monotonic() + WAIT_S
        while not os.path.exists(go) and time.monotonic() < deadline:
            time.sleep(0.01)
        with open(os.path.join(gate_dir, "resumed-" + gate), "w", encoding="utf-8") as f:
            f.write(f"{what} {time.time():.3f} go={'yes' if os.path.exists(go) else 'timeout'}\n")

    def gated(name, gate, fires):
        real = getattr(edit_store.EditStore, name)

        def wrapper(self, *args, **kwargs):
            result = real(self, *args, **kwargs)
            if fires(result) and consume(gate):
                hold(gate, f"EditStore.{name} -> {result!r}"[:200])
            return result
        wrapper.__wrapped__ = real
        setattr(edit_store.EditStore, name, wrapper)

    gated("read_previous", "P1", lambda r: True)
    gated("read", "P2", lambda r: r is None)
    gated("exists", "P2", lambda r: r is False)

    from darkroom_app.__main__ import main as app_main
    return app_main(rest)


if __name__ == "__main__":
    sys.exit(main())
