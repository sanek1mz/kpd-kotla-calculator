#!/usr/bin/env python3
"""
Точная сверка: для пар "сырой вывод Kpd3t2.exe (3 знака) <-> .ods с исходными
замерами" берём измерения из .ods, считаем нашим калькулятором, сравниваем
с ТОЧНЫМ (не округлённым оператором до 2 знаков) результатом самой программы.
"""

import re
import zipfile
import io
from pathlib import Path

import kpd_core as core
from fuel_data import SOLID_FUELS
from batch_validate import read_ods_text, extract as extract_ods, fnum

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COAL = SOLID_FUELS["Кузнецкий Т"]

PAIRS = [
    ("2015, 2016, 2017/10.10.17/KOTEL 4.txt", "2015, 2016, 2017/10.10.17/Таштагол   котел № 4.ods"),
    ("2015, 2016, 2017/20.10.16/KOTEL 2", "2015, 2016, 2017/20.10.16/Таштагол 20.10.2016  котел № 2.ods"),
    ("2018/10.05.18/KOTEL 4 10.05.18.txt", "2018/10.05.18/Таштагол   котел № 4.ods"),
    ("2018/12.01.18/KOTEL 4 12.01.18.txt", "2018/12.01.18/Таштагол   котел № 4.ods"),
    ("2018/12.01.18/KOTEL 5 12.01.18", "2018/12.01.18/Таштагол   котел № 5.ods"),
    ("2018/15.03.18/KOTEL 5 15.03.18.txt", "2018/15.03.18/Таштагол   котел № 5.ods"),
    ("2018/22.06.18/KOTEL 1.txt", "2018/22.06.18/Таштагол   котел № 1.ods"),
]


def parse_raw_exe(path: Path) -> dict:
    text = path.read_bytes().decode("cp866", errors="replace")
    pats = {
        "D": r"D=\s*([\-%\d.]+)", "q2": r"q2=\s*([\-%\d.]+)", "q3": r"q3=\s*([\-%\d.]+)",
        "q4": r"q4=\s*([\-%\d.]+)", "q5": r"q5=\s*([\-%\d.]+)", "q6": r"q6=\s*([\-%\d.]+)",
        "kpd": r"котла,\s*%,\s*=\s*([\-%\d.]+)",
    }
    out = {}
    for k, p in pats.items():
        m = re.search(p, text)
        v = m.group(1) if m else None
        out[k] = fnum(v.lstrip("%")) if v else None
    return out


def run_calc(vals: dict) -> core.KpdResult | None:
    if vals["D"] is None or vals["Tpe"] is None or vals["t_uh"] is None:
        return None
    candidates = [vals.get("O2_dymosos"), vals.get("O2_scrub"), vals.get("O2_stac"), vals.get("O2_perp")]
    o2 = next((c for c in candidates if c is not None and 1.0 <= c <= 16.0), None)
    if o2 is None:
        return None
    Wr = vals["Wr"] if vals["Wr"] is not None else DEFAULT_COAL.Wr
    Ar = vals["Ar"] if vals["Ar"] is not None else DEFAULT_COAL.Ar
    unos = vals["unos"] if vals["unos"] is not None else 0.0
    Rpe_kgs = vals["Rpe_kgs"] if vals["Rpe_kgs"] is not None else 14.0
    inp = core.KpdInputs(
        fuel_category="solid",
        Wr=Wr, Ar=Ar, Sr=DEFAULT_COAL.Sr, Cr=DEFAULT_COAL.Cr, Hr=DEFAULT_COAL.Hr,
        Nr=DEFAULT_COAL.Nr, Or=DEFAULT_COAL.Or, Qir_measured=None, t_fuel=20.0,
        D_nom=vals["D"], D=vals["D"], t_hv=30.0, t_uh=vals["t_uh"], O2=o2, CO=0.0,
        t_pe=vals["Tpe"], p_pe=Rpe_kgs * 0.0980665, t_pv=vals["t_pv"] or 100.0, p_prod=1.0,
        G_un=unos, G_shl=unos, a_un=0.95,
        q3=vals["q3"] if vals["q3"] is not None else 0.0,
        q5_nom=vals["q5"] if vals["q5"] is not None else 1.0,
    )
    try:
        return core.calculate(inp)
    except Exception:
        return None


def main():
    print(f"{'Пара':45s} {'КПД(exe,3зн)':>12s} {'КПД(наш)':>9s} {'Δ,п.п.':>7s}")
    print("-" * 80)
    diffs = []
    for raw_rel, ods_rel in PAIRS:
        raw_path = ROOT / raw_rel
        ods_path = ROOT / ods_rel
        raw_vals = parse_raw_exe(raw_path)
        ods_text = read_ods_text(ods_path)
        ods_vals = extract_ods(ods_text)
        if raw_vals["kpd"] is None or raw_vals["kpd"] < 0:
            print(f"{raw_rel:45s}  (пропуск - переполнение % в сыром выводе)")
            continue
        r = run_calc(ods_vals)
        if r is None:
            print(f"{raw_rel:45s}  (пропуск - недостаточно данных в .ods)")
            continue
        d = r.eta - raw_vals["kpd"]
        diffs.append(d)
        name = Path(raw_rel).name
        print(f"{name:45s} {raw_vals['kpd']:12.3f} {r.eta:9.3f} {d:7.2f}")

    if diffs:
        import statistics
        print("\n" + "=" * 40)
        print(f"Медиана |Δ|: {statistics.median(abs(x) for x in diffs):.2f} п.п.")
        print(f"Средняя |Δ|: {statistics.mean(abs(x) for x in diffs):.2f} п.п.")


if __name__ == "__main__":
    main()
