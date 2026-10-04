"""Qwen job list for the experiment (A = unpublished-control edits, B = want/avoid boost)."""

A_TEXT = ("Increase midtone local contrast and clarity, remove atmospheric haze, enhance fine surface texture. "
          "Keep the composition, people, faces, colours and every object exactly the same.")
A_NEG_TEXT = ("Reduce midtone local contrast for a gentle soft-focus glow, soften fine detail slightly. "
              "Keep the composition, people, faces, colours and every object exactly the same.")
KEEP = " Keep the composition, framing, pose, facial features, expression and every object exactly the same."

B = {
    "portrait_laughing": ("Make the photo look clearer and more transparent, with clean natural skin and a slightly warmer tone.",
                          "oversaturated colours, plastic waxy skin, airbrushed skin, changed teeth or expression"),
    "portrait_oldman": ("Make the wrinkles and skin texture more three-dimensional and the eyes a little brighter, with clearer overall tone.",
                        "smoothed skin, plastic skin, over-sharpened halos, oversaturated colours"),
    "portrait_studio": ("Make the skin look clean with a subtle healthy sheen, the knit fabric texture crisper and the background gradient smoother.",
                        "oversaturated colours, plastic skin, changed face shape, extra wrinkles in clothing"),
    "landscape_lighthouse": ("Give the storm clouds more depth and tonal layers and make the lighthouse a bit brighter and more prominent.",
                             "HDR halos, oversaturated colours, extra objects, changed rocks"),
    "fog_karst": ("Make the scene clearer and more transparent with livelier greens, while keeping the drifting mist atmosphere.",
                  "mist completely removed, neon green, oversaturated colours, changed mountains"),
}

PHOTOS = ["portrait_laughing", "portrait_oldman", "portrait_studio", "landscape_lighthouse", "fog_karst"]


def jobs():
    js = []
    for p in PHOTOS:
        for pe in (0, 1):
            js.append(dict(tag=f"aib-A-{p}-pe{pe}-s1", photo=p, part="A", pe=pe, sampler=1, text=A_TEXT))
    js.append(dict(tag="aib-A-portrait_laughing-pe0-s0", photo="portrait_laughing", part="A", pe=0, sampler=0, text=A_TEXT))
    js.append(dict(tag="aib-Aneg-portrait_oldman-pe0-s1", photo="portrait_oldman", part="Aneg", pe=0, sampler=1, text=A_NEG_TEXT))
    for p in PHOTOS:
        want, avoid = B[p]
        js.append(dict(tag=f"aib-B-{p}-pe1-s0", photo=p, part="B", pe=1, sampler=0,
                       text=want + " Avoid: " + avoid + "." + KEEP, neg=avoid))
    return js
