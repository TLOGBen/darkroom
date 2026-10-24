"""`python -s -m <module> <args>` for a given checkout, on a Python whose ._pth file ignores the working directory.

Verification scaffolding for /prove-it. Usage:

    <darkroom python> -s .claude/prove-it/tools/run_module.py --repo <checkout> <module> [args...]

Why: the dedicated darkroom Python is an embeddable build; its python313._pth lists the folders on sys.path and
makes Python ignore the working directory and PYTHONPATH. It lists the main checkout
(D:/Workspace/02_Project/code/darkroom; until 2026-10-24 the repo's old place D:/Code/darkroom), so
`python -s -m darkroom_app...` always imports the main checkout, whatever folder it runs in. This puts <checkout>
(a worktree of another commit, say) first on sys.path and runs <module> as __main__, exactly as `-m` would with that
checkout importable.
"""
import os
import runpy
import sys


def main():
    args = sys.argv[1:]
    if len(args) < 3 or args[0] != "--repo":
        sys.stderr.write("usage: run_module.py --repo <checkout> <module> [args...]\n")
        return 2
    repo, module, rest = os.path.abspath(args[1]), args[2], args[3:]
    sys.path.insert(0, repo)
    sys.argv = [module] + rest
    runpy.run_module(module, run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
