"""Basit, düzenlenebilir .docx yazıcı (saf Python, Word gerekmez).

Anlagenverzeichnis için başlık, birkaç paragraf ve kenarlıklı bir tablo üretir. Word'ün kendi
biçimi (OOXML) doğrudan yazılır; dosya Word'de normal belge gibi açılır ve düzenlenir.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>
<w:sz w:val="22"/><w:lang w:val="de-DE"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Standard"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Titel"><w:name w:val="Title"/><w:basedOn w:val="Standard"/>
<w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="Tabelle"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/><w:left w:val="single" w:sz="4" w:space="0" w:color="000000"/>
<w:bottom w:val="single" w:sz="4" w:space="0" w:color="000000"/><w:right w:val="single" w:sz="4" w:space="0" w:color="000000"/>
<w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/>
</w:tblBorders><w:tblCellMar><w:left w:w="100" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>"""

_CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{titel}</dc:title><dc:creator>BnX-Raptor</dc:creator></cp:coreProperties>"""


def _absatz(text: str, stil: str = "", fett: bool = False, rechts: bool = False) -> str:
    ppr = ""
    if stil or rechts:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{stil}"/>' if stil else "") + \
              ('<w:jc w:val="right"/>' if rechts else "") + "</w:pPr>"
    rpr = "<w:rPr><w:b/></w:rPr>" if fett else ""
    return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def _zelle(text: str, breite: int, fett: bool = False, rechts: bool = False) -> str:
    return (f'<w:tc><w:tcPr><w:tcW w:w="{breite}" w:type="dxa"/></w:tcPr>'
            f'{_absatz(text, fett=fett, rechts=rechts)}</w:tc>')


def docx_schreiben(ziel: Path, titel: str, absaetze: list[str], kopf: list[str],
                   zeilen: list[list[str]], breiten: list[int], rechts_spalten: set[int] = frozenset()) -> Path:
    """Titel + Absätze + Tabelle (erste Zeile = Kopfzeile, wird auf jeder Seite wiederholt)."""
    tabelle = ['<w:tbl><w:tblPr><w:tblStyle w:val="Tabelle"/><w:tblW w:w="0" w:type="auto"/></w:tblPr><w:tblGrid>',
               *[f'<w:gridCol w:w="{b}"/>' for b in breiten], "</w:tblGrid>",
               '<w:tr><w:trPr><w:tblHeader/></w:trPr>',
               *[_zelle(k, b, fett=True, rechts=i in rechts_spalten) for i, (k, b) in enumerate(zip(kopf, breiten))],
               "</w:tr>"]
    for z in zeilen:
        tabelle += ["<w:tr>", *[_zelle(t, b, rechts=i in rechts_spalten)
                                for i, (t, b) in enumerate(zip(z, breiten))], "</w:tr>"]
    tabelle.append("</w:tbl>")
    koerper = (_absatz(titel, "Titel") + "".join(_absatz(a) for a in absaetze) + "".join(tabelle)
               + "<w:p/>" + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
               '<w:pgMar w:top="1417" w:right="1417" w:bottom="1134" w:left="1417" w:header="708" '
               'w:footer="708" w:gutter="0"/></w:sectPr>')
    dokument = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body>{koerper}</w:body></w:document>")
    ziel = Path(ziel)
    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/document.xml", dokument)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("docProps/core.xml", _CORE.format(titel=escape(titel)))
    return ziel


def docx_tabelle_lesen(pfad: Path) -> list[list[str]]:
    """Testler ve kontrol için: ilk tablonun satırlarını metin olarak okur."""
    import re
    with zipfile.ZipFile(pfad) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    from xml.sax.saxutils import unescape
    zeilen = []
    for tr in re.findall(r"<w:tr>.*?</w:tr>|<w:tr .*?</w:tr>", xml, re.S):
        zellen = re.findall(r"<w:tc>(.*?)</w:tc>", tr, re.S)
        zeilen.append([unescape("".join(re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", c, re.S)))
                       for c in zellen])
    return zeilen
