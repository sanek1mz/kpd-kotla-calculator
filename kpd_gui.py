#!/usr/bin/env python3
"""
Расчёт КПД парового котла обратным балансом - графический интерфейс (tkinter, stdlib).

Реализация нормативной методики (Кузнецов Н.В. и др., "Тепловой расчет котельных
агрегатов. Нормативный метод"), восстановленной и валидированной в проекте
"КПД Таштагол" при реверс-инжиниринге программы Kpd3t2.exe (1987, Turbo Basic).
См. report.md и report_verification.md в корне проекта.

Запуск:  python3 kpd_gui.py
Зависимости: только стандартная библиотека Python 3 (tkinter).
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import date

from fuel_data import SOLID_FUELS, MAZUT_FUELS, GAS_FUELS, SOLID_FUEL_GROUPS, GasComponent
import kpd_core as core


FUEL_CATEGORIES = ["Твёрдое топливо", "Жидкое топливо (мазут)", "Газообразное топливо"]


class KpdApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=8)
        self.master = master
        master.title("Расчёт КПД парового котла — обратный баланс")
        master.geometry("1320x1040+20+10")
        master.minsize(1200, 900)
        self.pack(fill="both", expand=True)

        self.result: core.KpdResult | None = None
        self._build_ui()

    # ------------------------------------------------------------------ UI ----
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")

        self._build_fuel_section(left)
        self._build_regime_section(left)
        self._build_losses_section(left)
        self._build_buttons(left)

        self._build_results_section(right)

    def _labeled_entry(self, parent, row, label, default="", width=12):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=2, pady=2)
        var = tk.StringVar(value=str(default))
        ent = ttk.Entry(parent, textvariable=var, width=width)
        ent.grid(row=row, column=1, sticky="w", padx=2, pady=2)
        return var

    # --- Топливо ---------------------------------------------------------------
    def _build_fuel_section(self, parent):
        box = ttk.LabelFrame(parent, text="Топливо", padding=8)
        box.pack(fill="x", pady=4)

        ttk.Label(box, text="Вид топлива:").grid(row=0, column=0, sticky="w")
        self.fuel_cat_var = tk.StringVar(value=FUEL_CATEGORIES[0])
        cat_combo = ttk.Combobox(box, textvariable=self.fuel_cat_var, values=FUEL_CATEGORIES,
                                  state="readonly", width=28)
        cat_combo.grid(row=0, column=1, columnspan=2, sticky="w", pady=2)
        cat_combo.bind("<<ComboboxSelected>>", self._on_fuel_category_change)

        ttk.Label(box, text="Марка (справочная, № п/п):").grid(row=1, column=0, sticky="w")
        self.fuel_name_var = tk.StringVar()
        self.fuel_name_combo = ttk.Combobox(box, textvariable=self.fuel_name_var, state="readonly", width=38)
        self.fuel_name_combo.grid(row=1, column=1, columnspan=2, sticky="w", pady=2)
        self.fuel_name_combo.bind("<<ComboboxSelected>>", self._on_fuel_preset_change)

        # --- твёрдое/жидкое: состав рабочей массы (измеряется лабораторией на каждом опыте) ---
        self.sl_frame = ttk.Frame(box)
        self.sl_frame.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(self.sl_frame, text="Состав рабочей массы, % (можно скорректировать по замеру):",
                  font=("", 9, "italic")).grid(row=0, column=0, columnspan=4, sticky="w")
        def _pair(row, lbl1, def1, lbl2, def2):
            ttk.Label(self.sl_frame, text=lbl1).grid(row=row, column=0, sticky="w", padx=2, pady=2)
            v1 = tk.StringVar(value=str(def1))
            ttk.Entry(self.sl_frame, textvariable=v1, width=10).grid(row=row, column=1, sticky="w", padx=2, pady=2)
            ttk.Label(self.sl_frame, text=lbl2).grid(row=row, column=2, sticky="w", padx=(12, 2), pady=2)
            v2 = tk.StringVar(value=str(def2))
            ttk.Entry(self.sl_frame, textvariable=v2, width=10).grid(row=row, column=3, sticky="w", padx=2, pady=2)
            return v1, v2

        self.Wr, self.Ar = _pair(1, "Wr влажность,%", 8.0, "Ar зольность,%", 15.0)
        self.Sr, self.Cr = _pair(2, "Sr сера,%", 0.5, "Cr углерод,%", 60.0)
        self.Hr, self.Nr = _pair(3, "Hr водород,%", 4.0, "Nr азот,%", 1.5)
        self.Or, self.Qir_sl = _pair(4, "Or кислород,%", 8.0, "Qir теплота,МДж/кг", 22.5)
        ttk.Label(self.sl_frame, text="(если Qir=0 — расчёт по формуле Менделеева из состава)",
                  font=("", 8)).grid(row=5, column=0, columnspan=4, sticky="w")
        self.t_fuel = self._labeled_entry(self.sl_frame, 6, "t топлива,°C", 20.0)

        # --- газ: объёмный состав ---
        self.gas_frame = ttk.Frame(box)
        self.gas_entries = {}
        gas_fields = [("CH4", "CH4,%"), ("C2H6", "C2H6,%"), ("C3H8", "C3H8,%"), ("C4H10", "C4H10,%"),
                      ("H2", "H2,%"), ("H2S", "H2S,%"), ("CO", "CO,%"), ("CO2", "CO2,%"),
                      ("N2", "N2,%"), ("O2", "O2,%")]
        for i, (key, lbl) in enumerate(gas_fields):
            r, c = divmod(i, 2)
            ttk.Label(self.gas_frame, text=lbl).grid(row=r, column=c * 2, sticky="w", padx=2)
            var = tk.StringVar(value="0")
            ttk.Entry(self.gas_frame, textvariable=var, width=8).grid(row=r, column=c * 2 + 1, sticky="w", padx=2)
            self.gas_entries[key] = var
        self.Qir_gas = self._labeled_entry(self.gas_frame, 5, "Qir низшая теплота,МДж/м3", 35.6)

        self._on_fuel_category_change()

    def _on_fuel_category_change(self, *_):
        cat = self.fuel_cat_var.get()
        if cat == FUEL_CATEGORIES[0]:
            names = list(SOLID_FUELS.keys())
        elif cat == FUEL_CATEGORIES[1]:
            names = list(MAZUT_FUELS.keys())
        else:
            names = list(GAS_FUELS.keys())
        self.fuel_name_combo["values"] = names
        if names:
            self.fuel_name_var.set(names[0])
            self._on_fuel_preset_change()

        if cat == FUEL_CATEGORIES[2]:
            self.sl_frame.grid_remove()
            self.gas_frame.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        else:
            self.gas_frame.grid_remove()
            self.sl_frame.grid()

    def _on_fuel_preset_change(self, *_):
        cat = self.fuel_cat_var.get()
        name = self.fuel_name_var.get()
        if cat == FUEL_CATEGORIES[0] and name in SOLID_FUELS:
            f = SOLID_FUELS[name]
        elif cat == FUEL_CATEGORIES[1] and name in MAZUT_FUELS:
            f = MAZUT_FUELS[name]
        elif cat == FUEL_CATEGORIES[2] and name in GAS_FUELS:
            g = GAS_FUELS[name]
            self.gas_entries["CH4"].set(g.comp.CH4)
            self.gas_entries["C2H6"].set(g.comp.C2H6)
            self.gas_entries["C3H8"].set(g.comp.C3H8)
            self.gas_entries["C4H10"].set(g.comp.C4H10)
            self.gas_entries["H2"].set(g.comp.H2)
            self.gas_entries["H2S"].set(g.comp.H2S)
            self.gas_entries["CO"].set(g.comp.CO)
            self.gas_entries["CO2"].set(g.comp.CO2)
            self.gas_entries["N2"].set(g.comp.N2)
            self.gas_entries["O2"].set(g.comp.O2)
            self.Qir_gas.set(g.Qir_MJ_m3)
            return
        else:
            return
        self.Wr.set(f.Wr); self.Ar.set(f.Ar); self.Sr.set(f.Sr)
        self.Cr.set(f.Cr); self.Hr.set(f.Hr); self.Nr.set(f.Nr); self.Or.set(f.Or)
        self.Qir_sl.set(f.Qir_MJ)

    # --- Режим котла -------------------------------------------------------------
    def _build_regime_section(self, parent):
        box = ttk.LabelFrame(parent, text="Режим котла (замеры на опыте)", padding=8)
        box.pack(fill="x", pady=4)
        c1 = ttk.Frame(box); c1.grid(row=0, column=0, sticky="n")
        c2 = ttk.Frame(box); c2.grid(row=0, column=1, sticky="n", padx=(20, 0))

        self.D_nom = self._labeled_entry(c1, 0, "D номинальная, т/ч", 45.0)
        self.D = self._labeled_entry(c1, 1, "D фактическая, т/ч", 45.0)
        self.t_hv = self._labeled_entry(c1, 2, "t холодного воздуха,°C", 30.0)
        self.t_uh = self._labeled_entry(c1, 3, "t уходящих газов,°C", 150.0)
        self.O2 = self._labeled_entry(c1, 4, "O2 в уход.газах,%", 4.0)
        self.CO = self._labeled_entry(c1, 5, "CO в уход.газах,%", 0.01)

        self.t_pe = self._labeled_entry(c2, 0, "Tпе перегретый пар,°C", 250.0)
        self.p_pe = self._labeled_entry(c2, 1, "Pпе давление, МПа", 1.4)
        self.t_pv = self._labeled_entry(c2, 2, "t питательной воды,°C", 100.0)
        self.p_prod = self._labeled_entry(c2, 3, "Продувка, %", 1.0)

    # --- Потери --------------------------------------------------------------
    def _build_losses_section(self, parent):
        box = ttk.LabelFrame(parent, text="Потери (измеренные и справочные)", padding=8)
        box.pack(fill="x", pady=4)
        ttk.Label(box, text="Измеряется лабораторией (для твёрдого топлива):",
                  font=("", 9, "italic")).grid(row=0, column=0, columnspan=2, sticky="w")
        self.G_un = self._labeled_entry(box, 1, "Горючие в уносе, %", 0.0)
        self.G_shl = self._labeled_entry(box, 2, "Горючие в шлаке, %", 0.0)
        self.a_un = self._labeled_entry(box, 3, "Доля золы в уносе (аун)", 0.95)

        ttk.Label(box, text="Справочные (табл.8/рис.5 методики — задайте своё значение):",
                  font=("", 9, "italic")).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.q3 = self._labeled_entry(box, 5, "q3 хим.недожог, %", 0.0)
        self.q5_nom = self._labeled_entry(box, 6, "q5 при номин.нагрузке, %", 1.0)

    def _build_buttons(self, parent):
        box = ttk.Frame(parent)
        box.pack(fill="x", pady=10)
        ttk.Button(box, text="Рассчитать", command=self.on_calculate).pack(side="left", padx=4)
        ttk.Button(box, text="Сохранить отчёт...", command=self.on_save).pack(side="left", padx=4)

    # --- Результаты ------------------------------------------------------------
    def _build_results_section(self, parent):
        box = ttk.LabelFrame(parent, text="Результаты расчёта", padding=8)
        box.pack(fill="both", expand=True)
        self.result_text = tk.Text(box, width=54, height=40, font=("Courier New", 11))
        self.result_text.pack(fill="both", expand=True)
        self.result_text.insert("1.0", "Заполните данные и нажмите «Рассчитать».")
        self.result_text.configure(state="disabled")

    # ------------------------------------------------------------------ logic ----
    def _f(self, var: tk.StringVar, default=0.0) -> float:
        try:
            return float(str(var.get()).replace(",", "."))
        except ValueError:
            return default

    def _collect_inputs(self) -> core.KpdInputs:
        cat = self.fuel_cat_var.get()
        if cat == FUEL_CATEGORIES[0]:
            fc = "solid"
        elif cat == FUEL_CATEGORIES[1]:
            fc = "mazut"
        else:
            fc = "gas"

        inp = core.KpdInputs(fuel_category=fc)
        if fc == "gas":
            inp.gas_comp = GasComponent(
                CH4=self._f(self.gas_entries["CH4"]), C2H6=self._f(self.gas_entries["C2H6"]),
                C3H8=self._f(self.gas_entries["C3H8"]), C4H10=self._f(self.gas_entries["C4H10"]),
                H2=self._f(self.gas_entries["H2"]), H2S=self._f(self.gas_entries["H2S"]),
                CO=self._f(self.gas_entries["CO"]), CO2=self._f(self.gas_entries["CO2"]),
                N2=self._f(self.gas_entries["N2"]), O2=self._f(self.gas_entries["O2"]),
            )
            inp.Qir_measured = self._f(self.Qir_gas)
        else:
            inp.Wr = self._f(self.Wr); inp.Ar = self._f(self.Ar); inp.Sr = self._f(self.Sr)
            inp.Cr = self._f(self.Cr); inp.Hr = self._f(self.Hr); inp.Nr = self._f(self.Nr)
            inp.Or = self._f(self.Or)
            q = self._f(self.Qir_sl)
            inp.Qir_measured = q if q > 0 else None
            inp.t_fuel = self._f(self.t_fuel)

        inp.D_nom = self._f(self.D_nom); inp.D = self._f(self.D)
        inp.t_hv = self._f(self.t_hv); inp.t_uh = self._f(self.t_uh)
        inp.O2 = self._f(self.O2); inp.CO = self._f(self.CO)
        inp.t_pe = self._f(self.t_pe); inp.p_pe = self._f(self.p_pe)
        inp.t_pv = self._f(self.t_pv); inp.p_prod = self._f(self.p_prod)
        inp.G_un = self._f(self.G_un); inp.G_shl = self._f(self.G_shl)
        inp.a_un = self._f(self.a_un)
        inp.q3 = self._f(self.q3); inp.q5_nom = self._f(self.q5_nom)
        return inp

    def on_calculate(self):
        try:
            inp = self._collect_inputs()
            if inp.D <= 0:
                raise ValueError("Фактическая паропроизводительность D должна быть больше 0")
            result = core.calculate(inp)
        except Exception as e:  # noqa: BLE001 - показываем пользователю любую ошибку ввода
            messagebox.showerror("Ошибка расчёта", str(e))
            return
        self.result = result
        self._render_result(inp, result)

    def _render_result(self, inp: core.KpdInputs, r: core.KpdResult):
        unit = "м3" if inp.fuel_category == "gas" else "кг"
        lines = []
        lines.append("=" * 50)
        lines.append("  РЕЗУЛЬТАТЫ РАСЧЁТА КПД КОТЛА (обратный баланс)")
        lines.append("=" * 50)
        lines.append(f"Дата расчёта: {date.today().isoformat()}")
        lines.append("")
        lines.append(f"Vо возд.  = {r.vol.Vvo:8.3f} м3/{unit}")
        lines.append(f"VRO2      = {r.vol.VRO2:8.3f} м3/{unit}")
        lines.append(f"VN2о      = {r.vol.VNo2:8.3f} м3/{unit}")
        lines.append(f"VH2Oо     = {r.vol.VH2Oo:8.3f} м3/{unit}")
        lines.append(f"Vго       = {r.vol.Vgo:8.3f} м3/{unit}")
        lines.append("")
        lines.append(f"Избыток воздуха альфа       = {r.alpha:8.3f}")
        lines.append(f"Энтальпия уход.газов Iух    = {r.Iuh:8.1f} кДж/{unit}")
        lines.append(f"Энтальпия хол.воздуха Iохв  = {r.Iohv:8.1f} кДж/{unit}")
        lines.append(f"Располагаемая теплота Qp    = {r.Qp:8.1f} кДж/{unit}")
        lines.append("")
        lines.append("--- Потери теплоты, % ---")
        lines.append(f"q2 (с уходящими газами)     = {r.q2:8.3f}")
        lines.append(f"q3 (хим. недожог)           = {r.q3:8.3f}")
        lines.append(f"q4 (мех. недожог)           = {r.q4:8.3f}")
        lines.append(f"q5 (в окр. среду)           = {r.q5:8.3f}")
        lines.append(f"q6 (с теплом шлака)         = {r.q6:8.3f}")
        lines.append(f"Сумма Sq                    = {r.q2+r.q3+r.q4+r.q5+r.q6:8.3f}")
        lines.append("-" * 50)
        lines.append(f"КПД КОТЛА (брутто), %       = {r.eta:8.2f}")
        lines.append("-" * 50)
        lines.append("")
        lines.append(f"Расход топлива полный   B   = {r.B:10.1f} {unit}/ч")
        lines.append(f"Расход топлива расчётный Bp = {r.Bp:10.4f} {unit}/с")
        lines.append("")
        if r.eta < 40 or r.eta > 100:
            lines.append("!! ВНИМАНИЕ: результат вне физически разумного диапазона —")
            lines.append("   проверьте входные данные (возможно перепутаны поля O2/CO/")
            lines.append("   горючие в уносе — см. report_verification.md, раздел 2).")

        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", "\n".join(lines))
        self.result_text.configure(state="disabled")

    def on_save(self):
        if self.result is None:
            messagebox.showwarning("Нет результата", "Сначала выполните расчёт.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".txt",
                                             filetypes=[("Текстовый файл", "*.txt")],
                                             initialfile=f"kpd_расчёт_{date.today().isoformat()}.txt")
        if not path:
            return
        content = self.result_text.get("1.0", "end")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        messagebox.showinfo("Сохранено", f"Отчёт сохранён:\n{path}")


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    KpdApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
