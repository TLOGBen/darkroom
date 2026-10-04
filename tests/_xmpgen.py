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
