#!/usr/bin/env python3
"""TCMB EVDS'ten yeni ayların TÜFE aylık değişimini ve anket beklentisini çeker; CSV/JSON girdilerini günceller.

Geçmişi yeniden yazmaz: yalnızca CSV'nin son ayından sonraki aylar eklenir. Ardından make_tufe.py çalıştırılır.

Ortam değişkenleri:
  EVDS_API_KEY             zorunlu (GitHub secret). İstek başlığında gönderilir.
  EVDS_BASE                API kökü. Varsayılan: https://evds3.tcmb.gov.tr/igmevdsms-dis   (doğrulandı: anahtar başlığı istiyor)
  EVDS_CPI_SERIES          TÜFE genel endeks serisi. Varsayılan: TP.TUKFIY2025.GENEL (2025=100; eski TP.FG.J0
                           2003=100 serisi Ocak 2026'da arşive alındı)
  EVDS_EXPECTATION_SERIES  Piyasa Katılımcıları Anketi 12 ay sonrası TÜFE beklentisi serisi.
                           Boşsa expectation.json elle güncellenir.                        (DOĞRULA)

formulas=1 → bir önceki döneme göre yüzde değişim (aylık %).
--check: son üç ayı EVDS ile karşılaştırır, dosya yazmaz.
"""
import csv
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
CSV = HERE / "tufe_monthly.csv"
EXPECTATION = HERE / "expectation.json"


def env(name, default=None):
    """Boş değer de tanımsız sayılır: Actions'ta tanımlanmamış repo değişkeni boş metin olarak gelir."""
    return os.environ.get(name) or default


CPI_SERIES = "TP.TUKFIY2025.GENEL"


def fetch(series, start, end, formula=None):
    base = env("EVDS_BASE", "https://evds3.tcmb.gov.tr/igmevdsms-dis").rstrip("/")
    q = f"series={series}&startDate={start:%d-%m-%Y}&endDate={end:%d-%m-%Y}&type=json&frequency=5"
    if formula is not None:
        q += f"&formulas={formula}"
    req = urllib.request.Request(f"{base}/{q}", headers={"key": os.environ["EVDS_API_KEY"], "User-Agent": "taksitci-tufe"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def evds(series, start, end, formula=None):
    items = fetch(series, start, end, formula).get("items", [])
    prefix = series.replace(".", "_")
    out = []
    for it in items:
        key = next((k for k in it if k.startswith(prefix)), None)
        if key is None or it[key] in (None, "", "null"):
            continue
        y, m = (int(x) for x in str(it["Tarih"]).split("-")[:2])
        out.append((y * 100 + m, float(it[key])))
    return sorted(out)


def last_csv_month():
    with open(CSV, newline="") as f:
        rows = list(csv.DictReader(f))
    y, m = rows[-1]["month"].split("-")
    return int(y) * 100 + int(m)


def check():
    """Kontrol: CSV'deki son üç ayı EVDS'ten çekip karşılaştırır (anahtar ve seri kodu doğru mu). Dosya yazmaz."""
    with open(CSV, newline="") as f:
        rows = list(csv.DictReader(f))[-3:]
    first = dt.date(*(int(x) for x in rows[0]["month"].split("-")), 1)
    series = env("EVDS_CPI_SERIES", CPI_SERIES)
    got = dict(evds(series, first, dt.date.today(), formula=1))
    off = 0
    for r in rows:
        y, m = (int(x) for x in r["month"].split("-"))
        ours, theirs = float(r["monthly_pct"]), got.get(y * 100 + m)
        ok = theirs is not None and abs(ours - theirs) < 0.05
        off += not ok
        print(f"{r['month']}: CSV %{ours:.2f} · EVDS {'—' if theirs is None else f'%{theirs:.2f}'} {'✓' if ok else '✗'}")
    if off:
        if not got:
            raw = fetch(series, first, dt.date.today(), formula=1)
            items = raw.get("items", [])
            print(f"EVDS cevabı: anahtarlar {sorted(raw)}, totalCount {raw.get('totalCount')}, {len(items)} kayıt")
            for it in items[:2]:
                print("  ", it)
        sys.exit(f"{off} ay tutmuyor: EVDS_CPI_SERIES ({series}) ya da formül yanlış olabilir")


def main():
    if not os.environ.get("EVDS_API_KEY"):
        sys.exit("EVDS_API_KEY yok")
    if "--check" in sys.argv:
        return check()
    last = last_csv_month()
    y, m = divmod(last, 100)
    start = dt.date(y + (m == 12), m % 12 + 1, 1)
    today = dt.date.today()

    series = env("EVDS_CPI_SERIES", CPI_SERIES)
    new = [(ym, v) for ym, v in evds(series, start, today, formula=1) if ym > last]
    for (a, _), (b, _) in zip([(last, 0)] + new, new):
        ya, ma = divmod(a, 100)
        yb, mb = divmod(b, 100)
        if (yb * 12 + mb) - (ya * 12 + ma) != 1:
            sys.exit(f"ay boşluğu: {a} → {b}")
    if new:
        with open(CSV, "a", newline="") as f:
            for ym, pct in new:
                f.write(f"{ym // 100}-{ym % 100:02d},{pct:.2f}\n")
        print(f"TÜFE: {len(new)} yeni ay, son {new[-1][0]}")
    else:
        print("TÜFE: yeni ay yok")

    exp_series = env("EVDS_EXPECTATION_SERIES")
    if exp_series:
        vals = evds(exp_series, today - dt.timedelta(days=120), today)
        if vals:
            ym, v = vals[-1]
            cur = json.loads(EXPECTATION.read_text())
            if ym >= cur["surveyMonth"]:
                cur.update(surveyMonth=ym, annual12m=round(v / 100, 4))
                EXPECTATION.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n")
                print(f"Beklenti: {ym} %{v}")


if __name__ == "__main__":
    main()
