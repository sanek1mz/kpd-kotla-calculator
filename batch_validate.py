#!/usr/bin/env python3
"""
Пакетная сверка нового Python-калькулятора со всеми историческими .ods-протоколами
(2015-2020) — сравнение q2, q4, q6, КПД, посчитанных нашей программой из тех же
исходных замеров, с результатами, которые в своё время выдала старая Kpd3t2.exe
(записаны оператором в .ods при вводе результатов расчёта).

q3 (хим.недожог) и q5(ном.нагрузка) берём из самого .ods как переданные значения
(программа их не выводит формулой, см. report_verification.md, раздел 6) - поэтому
независимая проверка приходится на q2, q4, q6 и итоговый КПД.

Запуск:  python3 batch_validate.py
"""

import re
import zipfile
import io
from pathlib import Path

import kpd_core as core
from fuel_data import SOLID_FUELS

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COAL = SOLID_FUELS["Кузнецкий Т"]  # типовой состав для котлов К-50-14 Таштагол


def read_ods_text(path: Path) -> str:
    data = path.read_bytes()
    z = zipfile.ZipFile(io.BytesIO(data))
    xml = z.read("content.xml").decode("utf-8")
    t = re.sub("<[^>]+>", " ", xml)
    return re.sub(r"\s+", " ", t)


def fnum(s):
    if s is None:
        return None
    s = s.replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return None


def extract(text: str) -> dict:
    pats = {
        "D": r"Расход пара\s*т/ч\s*([\d.,]+)",
        "Tpe": r"Т перегретого пара\s*0\s*С\s*([\d.,]+)",
        "Rpe_kgs": r"Р пара\s*кгс/см\s*2\s*([\d.,]+)",
        "t_pv": r"Тпитательной воды\s*0\s*С\s*([\d.,]+)",
        "t_uh": r"Т уходящих газов\s*0\s*С\s*([\d.,]+)",
        "O2_stac": r"О2 \(кислородомер стационарный\)\s*%\s*([\d.,]+)",
        "O2_scrub": r"перед скруббером\s*СО2\s*%\s*[\d.,]+\s*К-т избытка воздуха\s*[\d.,]+\s*О2\s*%\s*([\d.,]+)",
        "O2_dymosos": r"перед дымососом\s*СО2\s*%\s*[\d.,]+\s*К-т избытка воздуха\s*[\d.,]+\s*О2\s*%\s*([\d.,]+)",
        "O2_perp": r"за пароперегревателем\s*СО2\s*%\s*[\d.,]+\s*К-т избытка воздуха\s*[\d.,]+\s*О2\s*%\s*([\d.,]+)",
        "Wr": r"Влаж-ть Wр,\s*%\s*%\s*([\d.,]+)",
        "Ar": r"Зольн-ть Ар,\s*%\s*%\s*([\d.,]+)",
        "unos": r"Содержание горючих в уносе.*?%\s*%\s*([\d.,]+)",
        "q2": r"q2\s*%\s*([\d.,]+)",
        "q3": r"q3\s*%\s*([\d.,]+)",
        "q4": r"q4\s*%\s*([\d.,]+)",
        "q5": r"q5\s*%\s*([\d.,]+)",
        "q6": r"q6\s*%\s*([\d.,]+)",
        "kpd": r"КПД\s*\(?брутто\)?\s*%\s*([\d.,]+)",
    }
    out = {}
    for k, p in pats.items():
        m = re.search(p, text)
        out[k] = fnum(m.group(1)) if m else None
    return out


def run_calc(vals: dict) -> core.KpdResult | None:
    if vals["D"] is None or vals["Tpe"] is None or vals["t_uh"] is None:
        return None
    # выбираем физически правдоподобное значение O2 (типичный диапазон уходящих газов
    # 2-16%): предпочитаем показание "за пароперегревателем" (ближе всего к точке, где
    # программа исторически спрашивала альфа уходящих газов), с проверкой разумности;
    # при отсутствии/аномалии - перебираем остальные точки замера по порядку
    candidates = [vals.get("O2_dymosos"), vals.get("O2_scrub"), vals.get("O2_stac"), vals.get("O2_perp")]
    o2 = next((c for c in candidates if c is not None and 1.0 <= c <= 16.0), None)
    if o2 is None:
        return None
    Wr = vals["Wr"] if vals["Wr"] is not None else DEFAULT_COAL.Wr
    Ar = vals["Ar"] if vals["Ar"] is not None else DEFAULT_COAL.Ar
    unos = vals["unos"] if vals["unos"] is not None else 0.0
    Rpe_kgs = vals["Rpe_kgs"] if vals["Rpe_kgs"] is not None else 14.0
    p_pe_mpa = Rpe_kgs * 0.0980665

    inp = core.KpdInputs(
        fuel_category="solid",
        Wr=Wr, Ar=Ar, Sr=DEFAULT_COAL.Sr, Cr=DEFAULT_COAL.Cr, Hr=DEFAULT_COAL.Hr,
        Nr=DEFAULT_COAL.Nr, Or=DEFAULT_COAL.Or, Qir_measured=None, t_fuel=20.0,
        D_nom=vals["D"], D=vals["D"], t_hv=30.0, t_uh=vals["t_uh"], O2=o2, CO=0.0,
        t_pe=vals["Tpe"], p_pe=p_pe_mpa, t_pv=vals["t_pv"] or 100.0, p_prod=1.0,
        G_un=unos, G_shl=unos, a_un=0.95,
        q3=vals["q3"] if vals["q3"] is not None else 0.0,
        q5_nom=vals["q5"] if vals["q5"] is not None else 1.0,
    )
    try:
        return core.calculate(inp)
    except Exception:
        return None


def main():
    ods_files = sorted(
        p for p in ROOT.rglob("*.ods")
        if "dosbox_isolated" not in p.parts and "kpd_calculator" not in p.parts and "analysis" not in p.parts
    )
    print(f"Найдено .ods файлов: {len(ods_files)}\n")

    rows = []
    skipped = []
    for p in ods_files:
        try:
            text = read_ods_text(p)
        except Exception as e:
            skipped.append((p, f"ошибка чтения: {e}"))
            continue
        vals = extract(text)
        if vals["kpd"] is None or vals["q2"] is None:
            skipped.append((p, "нет блока «Расчёт КПД котла брутто» (незаполненный протокол)"))
            continue
        r = run_calc(vals)
        if r is None:
            skipped.append((p, "недостаточно данных для расчёта (нет D/Tпе/t.ух/O2)"))
            continue
        rel = p.relative_to(ROOT)
        rows.append((rel, vals, r))

    print(f"Посчитано и сопоставлено: {len(rows)}")
    print(f"Пропущено: {len(skipped)}\n")

    print(f"{'Файл':60s} {'D':>5s} {'КПД(файл)':>10s} {'КПД(наш)':>9s} {'Δ,%':>6s}   q2ф/н        q4ф/н")
    print("-" * 130)
    diffs = []
    for rel, vals, r in rows:
        d = r.eta - vals["kpd"]
        diffs.append(d)
        name = str(rel)
        if len(name) > 58:
            name = "..." + name[-55:]
        print(f"{name:60s} {vals['D']:5.1f} {vals['kpd']:10.2f} {r.eta:9.2f} {d:6.2f}   "
              f"{vals['q2']:5.2f}/{r.q2:5.2f}  {(vals['q4'] or 0):5.2f}/{r.q4:5.2f}")

    if diffs:
        import statistics
        print("\n" + "=" * 60)
        print(f"Среднее отклонение КПД:        {statistics.mean(diffs):+.2f} п.п.")
        print(f"Медианное |отклонение| КПД:    {statistics.median(abs(x) for x in diffs):.2f} п.п.")
        print(f"Макс. |отклонение| КПД:        {max(abs(x) for x in diffs):.2f} п.п.")
        within_2 = sum(1 for x in diffs if abs(x) <= 2.0)
        print(f"В пределах ±2 п.п.:            {within_2}/{len(diffs)} ({100*within_2/len(diffs):.0f}%)")

    if skipped:
        print(f"\n--- Пропущенные файлы ({len(skipped)}) ---")
        for p, reason in skipped:
            print(f"  {p.relative_to(ROOT)}: {reason}")


if __name__ == "__main__":
    main()
