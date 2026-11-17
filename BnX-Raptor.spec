# -*- mode: python -*-
# BnX-Raptor – TEK paketleme ayarı (yerel build.bat ve GitHub release.yml aynı dosyayı kullanır).
# Çağrı: python tools/paket_bauen.py  (doğrudan pyinstaller da çalışır: pyinstaller BnX-Raptor.spec)

# PyMuPDF 2.x yapay zekâ/düzen eklentilerini ve geliştirici dosyalarını getirir – BnX-Raptor kullanmaz.
HARIC_MODULE = ["onnxruntime", "pymupdf_layout", "pymupdf4llm", "pymupdf.layout", "numpy", "networkx",
                "tabulate", "yaml", "psutil"]
HARIC_PFADE = ("pymupdf/layout", "pymupdf\\layout", "pymupdf/mupdf-devel", "pymupdf\\mupdf-devel")
# Von PySide6 automatisch mitgebrachte, in BnX-Raptor ungenutzte Qt-Teile (weniger Größe und Lizenzpflichten):
# Qt PDF/PDFium, QML/Quick, Bildschirmtastatur, Software-OpenGL (Mesa). Geprüft: keine verbleibende Qt-DLL
# importiert diese Dateien (Import-Tabellen, 0.4.0).
HARIC_DATEIEN = {"opengl32sw.dll", "qt6pdf.dll", "qpdf.dll", "qt6virtualkeyboard.dll", "qtvirtualkeyboardplugin.dll",
                 "qt6quick.dll", "qt6qml.dll", "qt6qmlmeta.dll", "qt6qmlmodels.dll", "qt6qmlworkerscript.dll",
                 "qt6opengl.dll"}


def _behalten(eintrag):
    ziel = eintrag[0].replace("\\", "/")
    if ziel.rsplit("/", 1)[-1].lower() in HARIC_DATEIEN:
        return False
    return not any(ziel.startswith(p.replace("\\", "/")) for p in HARIC_PFADE)


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["win32com.client", "pythoncom"],
    excludes=HARIC_MODULE,
    noarchive=False,
)
a.datas = [d for d in a.datas if _behalten(d)]
a.binaries = [b for b in a.binaries if _behalten(b)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="BnX-Raptor", console=False,
          debug=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BnX-Raptor")
