"""Utils layer: tools with no business knowledge (plan-v2 §1).

Modules: the guarded write module (the one module that writes files; see CONTRACT-write-guard G8 = "exactly five
write functions, each checking root / preset folder / protected extensions first"; its name is deliberately not
spelled out here because the layering test forbids that name in modules outside its whitelist), `encoding` (image
file encoders and EXIF), `imaging` (fingerprint,
JPEG headers, thumbnail pixels), `text` (one-line error text, strict int check), `gpucheck` (is the GPU busy?) and
`runtime_info` (versions for /api/version).

Dependency rule: utils imports only the standard library, third-party packages and the `darkroom` core library.
It never imports domain, services, adapters, the facade, composition or config.
"""
