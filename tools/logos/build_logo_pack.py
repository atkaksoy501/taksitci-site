#!/usr/bin/env python3
"""Banka logo paketini (logos.json) üretir.

Girdi: banka kataloğu (Taksitci/Resources/BankCatalog.json). `appStoreId`si olan her banka için Apple'ın
iTunes Lookup API'sinden (ücretsiz, anahtarsız) uygulama ikonunu çeker, 128 px PNG'ye küçültür ve hepsini
tek dosyada toplar. Çıktı (varsayılan): docs/data/logos.json  (GitHub Pages: data/logos.json)

Paket biçimi (schemaVersion 1):
  {"schemaVersion": 1, "generatedAt": "...Z", "source": "...", "logos": [{"id": "garanti-bbva", "png": "<base64>"}]}

Kurallar:
  - Kimlik elle doğrulanır: `appStoreId` yalnızca katalogda yazılıysa kullanılır. Kimliği olmayan banka atlanır.
    `--suggest` bu bankalar için App Store aramasından adayları listeler (hiçbir şey yazmaz); doğru olanı
    katalogdaki `appStoreId` alanına elle yaz.
  - Lookup cevabındaki `trackId` istenen kimlikle aynı değilse o banka atlanır ve uyarı verilir.
  - Veri aynıysa dosyaya dokunulmaz (`generatedAt` gereksiz değişmez).
  - `--check`: indirir ve doğrular, dosya yazmaz.

Kullanım:
  python3 scripts/logos/build_logo_pack.py [--catalog YOL] [--out YOL] [--check] [--suggest]
Gereksinim: Pillow (yalnızca ikon küçültmek için; `--suggest` ve testler için gerekmez).
"""
import argparse
import base64
import datetime as dt
import json
import pathlib
import sys
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / "Taksitci/Resources/BankCatalog.json"
DEFAULT_OUT = ROOT / "docs/data/logos.json"
SCHEMA_VERSION = 1
LOGO_SIZE = 128
MAX_LOGO_BYTES = 64 * 1024        # uygulama bundan büyük logoyu reddeder
MAX_PACK_BYTES = 2 * 1024 * 1024  # uygulama bundan büyük paketi reddeder
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
LOOKUP = "https://itunes.apple.com/lookup?id={id}&country=tr"
SEARCH = "https://itunes.apple.com/search?term={term}&country=tr&entity=software&limit=5"
SOURCE = "Apple iTunes Lookup API (uygulama ikonları), kurumları tanıtmak için"


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "taksitci-logo-pack"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def load_catalog(path):
    doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    banks = doc["banks"]
    ids = [b["id"] for b in banks]
    if len(set(ids)) != len(ids):
        sys.exit("Katalogda yinelenen id var")
    return banks


def pillow_resize(png_or_jpeg, size=LOGO_SIZE):
    """İkonu size×size PNG'ye küçültür (Pillow gerekir)."""
    import io
    from PIL import Image
    img = Image.open(io.BytesIO(png_or_jpeg)).convert("RGBA").resize((size, size), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def artwork_url(lookup_json, app_id):
    """Lookup cevabından 512 px ikon adresi. Kimlik uyuşmazsa ya da ikon yoksa None."""
    results = lookup_json.get("results") or []
    for r in results:
        if r.get("trackId") == app_id:
            return r.get("artworkUrl512") or r.get("artworkUrl100")
    return None


def build_logos(banks, get=http_get, resize=pillow_resize, warn=lambda m: print(m, file=sys.stderr)):
    """[(id, png bytes)] — kimliği olan her banka için; hata olan atlanır."""
    logos = []
    for b in banks:
        app_id = b.get("appStoreId")
        if not app_id:
            continue
        try:
            info = json.loads(get(LOOKUP.format(id=app_id)))
            url = artwork_url(info, app_id)
            if not url:
                warn(f"{b['id']}: App Store kaydı {app_id} ile eşleşmedi ya da ikon yok; atlandı")
                continue
            png = resize(get(url))
        except Exception as e:  # ağ, JSON, görsel hatası: tek banka tüm paketi bozmasın
            warn(f"{b['id']}: {e}; atlandı")
            continue
        if not png.startswith(PNG_SIGNATURE) or len(png) > MAX_LOGO_BYTES:
            warn(f"{b['id']}: PNG değil ya da {MAX_LOGO_BYTES} bayttan büyük; atlandı")
            continue
        logos.append((b["id"], png))
    return sorted(logos)


def to_doc(logos, generated_at):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
        "source": SOURCE,
        "logos": [{"id": i, "png": base64.b64encode(p).decode("ascii")} for i, p in logos],
    }


def validate(doc):
    assert doc["schemaVersion"] == SCHEMA_VERSION
    ids = [e["id"] for e in doc["logos"]]
    assert len(set(ids)) == len(ids), "yinelenen id"
    for e in doc["logos"]:
        png = base64.b64decode(e["png"], validate=True)
        assert png.startswith(PNG_SIGNATURE), f"{e['id']}: PNG değil"
        assert len(png) <= MAX_LOGO_BYTES, f"{e['id']}: logo çok büyük"
    assert len(json.dumps(doc)) <= MAX_PACK_BYTES, "paket çok büyük"


def same_logos(a, b):
    return a.get("schemaVersion") == b.get("schemaVersion") and a.get("logos") == b.get("logos")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_if_changed(doc, out):
    out = pathlib.Path(out)
    if out.exists() and same_logos(json.loads(out.read_text(encoding="utf-8")), doc):
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return True


def suggest(banks, get=http_get, out=print):
    """Kimliği olmayan bankalar için aday uygulamaları yazdırır. Seçim kullanıcıya aittir."""
    missing = [b for b in banks if not b.get("appStoreId")]
    for b in missing:
        out(f"# {b['id']} ({b['name']})")
        try:
            res = json.loads(get(SEARCH.format(term=urllib.parse.quote(b["name"]))))
        except Exception as e:
            out(f"  arama başarısız: {e}")
            continue
        for r in res.get("results", []):
            out(f"  {r.get('trackId')}\t{r.get('trackName')}\t{r.get('sellerName')}")
    return len(missing)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--check", action="store_true", help="indir ve doğrula, dosya yazma")
    ap.add_argument("--suggest", action="store_true", help="kimliği olmayan bankalar için aday uygulamaları listele")
    args = ap.parse_args(argv)

    banks = load_catalog(args.catalog)
    if args.suggest:
        suggest(banks)
        return 0
    logos = build_logos(banks)
    doc = to_doc(logos, now_iso())
    validate(doc)
    print(f"{len(logos)}/{len(banks)} banka logosu hazır")
    if args.check:
        return 0
    print("yazıldı" if write_if_changed(doc, args.out) else "değişiklik yok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
