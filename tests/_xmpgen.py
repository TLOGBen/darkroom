"""Build small synthetic Lightroom xmp files for tests."""
import os

HEAD = '''<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
'''


def xmp_text(attrs=None, name="Test Preset", curves=None, extra="", group=None):
    attrs = dict({"ProcessVersion": "11.0", "Version": "15.3"}, **(attrs or {}))
    a = "".join(f'   crs:{k}="{v}"\n' for k, v in attrs.items())
    body = f'''   <crs:Name>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{name}</rdf:li>
    </rdf:Alt>
   </crs:Name>
'''
    if group is not None:
        body += f'''   <crs:Group>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{group}</rdf:li>
    </rdf:Alt>
   </crs:Group>
'''
    for tag, pts in (curves or {}).items():
        lis = "".join(f"     <rdf:li>{x}, {y}</rdf:li>\n" for x, y in pts)
        body += f"   <crs:{tag}>\n    <rdf:Seq>\n{lis}    </rdf:Seq>\n   </crs:{tag}>\n"
    return HEAD + a + "   >\n" + body + extra + "  </rdf:Description>\n </rdf:RDF>\n</x:xmpmeta>\n"


def linear_mask(zero, full, local, inverted=False, what="Mask/Gradient"):
    loc = "".join(f'       crs:{k}="{v}"\n' for k, v in local.items())
    return f'''   <crs:MaskGroupBasedCorrections>
    <rdf:Seq>
     <rdf:li>
      <rdf:Description
       crs:What="Correction"
       crs:CorrectionAmount="1"
       crs:CorrectionActive="true"
       crs:CorrectionName="Mask 1"
{loc}      >
      <crs:CorrectionMasks>
       <rdf:Seq>
        <rdf:li
         crs:What="{what}"
         crs:MaskActive="true"
         crs:MaskName="Linear Gradient 1"
         crs:MaskBlendMode="0"
         crs:MaskInverted="{str(inverted).lower()}"
         crs:MaskValue="1"
         crs:ZeroX="{zero[0]}"
         crs:ZeroY="{zero[1]}"
         crs:FullX="{full[0]}"
         crs:FullY="{full[1]}"/>
       </rdf:Seq>
      </crs:CorrectionMasks>
      </rdf:Description>
     </rdf:li>
    </rdf:Seq>
   </crs:MaskGroupBasedCorrections>
'''


def radial_mask(top, left, bottom, right, local, feather=0, flipped=True, inverted=False, angle=0):
    loc = "".join(f'       crs:{k}="{v}"\n' for k, v in local.items())
    return f'''   <crs:MaskGroupBasedCorrections>
    <rdf:Seq>
     <rdf:li>
      <rdf:Description
       crs:What="Correction"
       crs:CorrectionAmount="1"
       crs:CorrectionActive="true"
       crs:CorrectionName="Mask 1"
{loc}      >
      <crs:CorrectionMasks>
       <rdf:Seq>
        <rdf:li
         crs:What="Mask/CircularGradient"
         crs:MaskActive="true"
         crs:MaskName="Radial Gradient 1"
         crs:MaskBlendMode="0"
         crs:MaskInverted="{str(inverted).lower()}"
         crs:MaskValue="1"
         crs:Top="{top}"
         crs:Left="{left}"
         crs:Bottom="{bottom}"
         crs:Right="{right}"
         crs:Angle="{angle}"
         crs:Midpoint="50"
         crs:Roundness="0"
         crs:Feather="{feather}"
         crs:Flipped="{str(flipped).lower()}"
         crs:Version="2"/>
       </rdf:Seq>
      </crs:CorrectionMasks>
      </rdf:Description>
     </rdf:li>
    </rdf:Seq>
   </crs:MaskGroupBasedCorrections>
'''


def write(dirpath, filename, text):
    p = os.path.join(dirpath, filename)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return p


def _look(name):
    return f'   <crs:Look>\n    <rdf:Description crs:Name="{name}" crs:Amount="1"/>\n   </crs:Look>\n'


# A stand-in for the user's preset library where there is none (a clean checkout / CI): one file per kind of preset
# the library tests look for (find_preset patterns), every one of them supported (no PV2010) and without a crop.
SYNTHETIC_LIBRARY = [
    ("a-pv67.xmp", {"ProcessVersion": "6.7", "Contrast2012": "+10", "Exposure2012": "+0.20"}, {}),
    ("b-pv10.xmp", {"ProcessVersion": "10.0", "Exposure2012": "-0.30", "Clarity2012": "+15", "Vibrance": "+12"}, {}),
    ("c-pv11-curves.xmp", {"ProcessVersion": "11.0", "Highlights2012": "-40", "Shadows2012": "+30"},
     {"curves": {"ToneCurvePV2012": [(0, 18), (64, 60), (192, 200), (255, 245)],
                 "ToneCurvePV2012Red": [(0, 0), (128, 136), (255, 255)],
                 "ToneCurvePV2012Blue": [(0, 8), (128, 122), (255, 250)]}}),
    ("d-pv154-color.xmp", {"ProcessVersion": "15.4", "HueAdjustmentOrange": "-10", "SaturationAdjustmentBlue": "-25",
                           "LuminanceAdjustmentGreen": "+15", "ColorGradeMidtoneHue": "30", "ColorGradeMidtoneSat": "10",
                           "ColorGradeBlending": "60", "SplitToningHighlightHue": "45",
                           "SplitToningHighlightSaturation": "15"}, {}),
    ("e-wb-temperature.xmp", {"WhiteBalance": "Custom", "Temperature": "5500", "Tint": "+10",
                              "IncrementalTemperature": "+8"}, {}),
    ("f-look-color.xmp", {"Exposure2012": "+0.15"}, {"extra": _look("Adobe Color")}),
    ("g-look-mono.xmp", {"Contrast2012": "+20"}, {"extra": _look("Adobe Monochrome")}),
    ("h-hdr.xmp", {"HDREditMode": "1", "Exposure2012": "+0.10"}, {}),
    ("i-mask-radial.xmp", {"Exposure2012": "+0.10"},
     {"extra": radial_mask(0.2, 0.2, 0.8, 0.8, {"LocalExposure2012": "-0.40"}, feather=50)}),
    ("j-mask-linear.xmp", {"Contrast2012": "+5"},
     {"extra": linear_mask((0.5, 0.0), (0.5, 0.4), {"LocalExposure2012": "-0.30", "LocalDehaze": "+10"})}),
    ("k-bw-plain.xmp", {"ConvertToGrayscale": "True", "GrayMixerOrange": "+20", "GrayMixerBlue": "-30",
                        "Contrast2012": "+15"}, {}),
    ("l-bw-toned.xmp", {"ConvertToGrayscale": "True", "SplitToningShadowHue": "30",
                        "SplitToningShadowSaturation": "25"}, {}),
    ("m-film.xmp", {"GrainAmount": "25", "GrainSize": "30", "PostCropVignetteAmount": "-15", "Dehaze": "+8",
                    "Texture": "+10", "Saturation": "-10", "Sharpness": "30", "ParametricShadows": "+10"}, {}),
]


def synthetic_library(xmp_dir):
    """Write SYNTHETIC_LIBRARY into xmp_dir (an existing folder); returns the paths."""
    out = []
    for filename, attrs, kw in SYNTHETIC_LIBRARY:
        stem = filename[:-4]
        out.append(write(xmp_dir, filename, xmp_text(attrs, name=f"Synthetic {stem}", group=f"Synthetic - {stem[0]}",
                                                    **kw)))
    return out
