#!/usr/bin/env python3
"""tufe.json üretir: aylık TÜFE değişimlerinden zincirlenmiş endeks (2025 ortalaması = 100) + anket beklentisi.

Girdi:
  scripts/tufe/tufe_monthly.csv   month (yyyy-mm), monthly_pct  (TÜİK/TCMB aylık % değişim)
  scripts/tufe/expectation.json   series, surveyMonth (yyyymm), annual12m (0.237 = %23,7)
Çıktı (varsayılan):
  Taksitci/Resources/tufe.json    uygulamaya gömülü kopya
  docs/data/tufe.json             GitHub Pages'ten indirilen kopya

TÜİK Ocak 2026'da temel yılı 2003=100'den 2025=100'e taşıdı; aylık oranlar değişmedi. Endeksi
aylık oranlardan zincirleyip 2025 ortalamasını 100'e eşitlemek iki seriyi tek seride birleştirir.
Uygulama yalnızca endeks oranlarını kullanır.

Kullanım: python3 scripts/tufe/make_tufe.py [çıktı yolları...]
"""
import csv
import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_OUT = [ROOT / "Taksitci/Resources/tufe.json", ROOT / "docs/data/tufe.json"]


def load_monthly(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            y, m = r["month"].split("-")
            rows.append((int(y) * 100 + int(m), float(r["monthly_pct"])))
    rows.sort()
    return rows


def build(rows, expectation):
    level = 100.0
    raw = []
    for ym, pct in rows:
        level *= 1 + pct / 100
        raw.append((ym, level))
    base = [v for ym, v in raw if ym // 100 == 2025]
    if len(base) != 12:
        sys.exit("2025'in 12 ayı da gerekli (2025=100 ölçeklemesi)")
    scale = 100 / (sum(base) / 12)
    points = [{"m": ym, "v": round(v * scale, 4)} for ym, v in raw]
    return {
        "schemaVersion": 1,
        "generatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "TÜİK TÜFE aylık değişim (TCMB tüketici fiyatları tablosu); TCMB Piyasa Katılımcıları Anketi",
        "cpi": {"series": "TÜFE genel endeks", "base": "2025=100 (aylık oranlardan zincirlenmiş)", "points": points},
        "expectation": expectation,
    }


def validate(doc):
    pts = doc["cpi"]["points"]
    assert doc["schemaVersion"] == 1
    assert pts, "boş seri"
    for a, b in zip(pts, pts[1:]):
        ya, ma = divmod(a["m"], 100)
        yb, mb = divmod(b["m"], 100)
        assert (yb * 12 + mb) - (ya * 12 + ma) == 1, f"ay boşluğu: {a['m']} → {b['m']}"
        assert b["v"] > 0, f"pozitif değil: {b['m']}"
        assert abs(b["v"] / a["v"] - 1) < 0.30, f"aşırı sıçrama: {b['m']}"
    assert 0 <= doc["expectation"]["annual12m"] <= 5, "beklenti aralık dışı"
    size = len(json.dumps(doc))
    assert size < 256 * 1024, f"dosya çok büyük: {size}"


def main():
    rows = load_monthly(HERE / "tufe_monthly.csv")
    expectation = json.loads((HERE / "expectation.json").read_text())
    doc = build(rows, expectation)
    validate(doc)
    outs = [pathlib.Path(p) for p in sys.argv[1:]] or DEFAULT_OUT
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"
    for out in outs:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print(f"→ {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}  son ay {doc['cpi']['points'][-1]['m']}, beklenti %{expectation['annual12m']*100:.2f}")


if __name__ == "__main__":
    main()
