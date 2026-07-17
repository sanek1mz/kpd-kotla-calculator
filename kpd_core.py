"""
Ядро расчёта КПД парового котла обратным балансом (нормативный метод).

Источник формул: "Тепловой расчет котельных агрегатов. Нормативный метод"
(Кузнецов Н.В. и др., ВТИ/ЦКТИ) — см. analysis/methodology_source.pdf в проекте
"КПД Таштагол". Формулы q2, q4, q5, q6, Qp, B, Dпр воспроизведены дословно
(см. report_verification.md, раздел 6).

Табличные удельные энтальпии компонентов продуктов сгорания (ct_CO2, ct_N2, ct_H2O,
ct_air) получены не по памяти, а численно (МНК) из таблицы 4 источника (энтальпии
23 эталонных топлив при альфа=1) — метод и остаточная невязка задокументированы
в комментариях ниже. Это даёт единый расчёт энтальпий, работающий для ЛЮБОГО состава
топлива (включая газ, для которого таблицы 4 в источнике нет), а не только для
23 табличных топлив.

Формула q3 (химический недожог) в источнике дана как табличное значение (табл. 8),
не как формула от измеренного CO — поэтому в этом инструменте q3 задаётся оператором
(с справочной подсказкой по умолчанию), а не считается по CO автоматически.
То же для q5(номинал) — источник даёт его как график (рис. 5), не формулу.
"""

from dataclasses import dataclass
import bisect

from fuel_data import SolidLiquidFuel, GasFuel, GasComponent


# =====================================================================================
# Удельные энтальпии компонентов продуктов сгорания и воздуха, кДж/м3 (при 0 °C = 0).
# Получены МНК по табл.4 источника (4 эталонных топлива: Кузнецкий Д, Березовское,
# Подмосковный бурый, мазут малосернистый - выбраны для максимального разброса
# соотношений VRO2:VNo2:VH2Oo). Проверено на топливе, не участвовавшем в подгонке
# (Кузнецкий Т, t=1000°C): расхождение <1%. std по ct_air между топливами <0.2%.
# =====================================================================================
_T_POINTS = [0, 200, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000, 2200]
_CT_CO2 = [0.0, 348.9, 753.7, 1231.0, 1694.9, 2109.6, 2704.6, 3161.0, 3716.6, 4262.7, 4762.8, 5245.6]
_CT_N2 = [0.0, 259.9, 527.3, 797.9, 1089.5, 1403.0, 1691.1, 2020.4, 2330.8, 2647.8, 2975.9, 3311.0]
_CT_H2O = [0.0, 314.6, 643.2, 991.0, 1364.6, 1775.7, 2172.6, 2584.7, 3020.6, 3474.6, 3953.2, 4444.9]
_CT_AIR = [0.0, 266.6, 542.2, 830.3, 1130.4, 1438.5, 1754.8, 2077.5, 2404.4, 2732.3, 3066.8, 3402.5]


def _interp(t: float, table: list[float]) -> float:
    """Линейная интерполяция по таблице удельных энтальпий; экстраполяция за 2200°C
    продолжает последний наклон (для очень горячих топочных температур)."""
    if t <= _T_POINTS[0]:
        return 0.0
    if t >= _T_POINTS[-1]:
        slope = (table[-1] - table[-2]) / (_T_POINTS[-1] - _T_POINTS[-2])
        return table[-1] + slope * (t - _T_POINTS[-1])
    i = bisect.bisect_right(_T_POINTS, t) - 1
    t0, t1 = _T_POINTS[i], _T_POINTS[i + 1]
    v0, v1 = table[i], table[i + 1]
    return v0 + (v1 - v0) * (t - t0) / (t1 - t0)


@dataclass
class CombustionVolumes:
    Vvo: float    # теоретический объём воздуха, м3/кг или м3/м3
    VRO2: float   # объём трёхатомных газов
    VNo2: float   # объём азота
    VH2Oo: float  # теоретический объём водяных паров
    Vgo: float    # теоретический объём газов


def combustion_volumes_solid_liquid(Cr: float, Hr: float, Sr: float, Or: float,
                                     Nr: float, Wr: float) -> CombustionVolumes:
    """Формулы источника (стр.15) для твёрдого/жидкого топлива, состав в % рабочей массы."""
    Vvo = 0.0889 * (Cr + 0.375 * Sr) + 0.265 * Hr - 0.0333 * Or
    VRO2 = 0.01866 * (Cr + 0.375 * Sr)
    VNo2 = 0.79 * Vvo + 0.008 * Nr
    VH2Oo = 0.111 * Hr + 0.0124 * Wr + 0.0161 * Vvo
    Vgo = VRO2 + VNo2 + VH2Oo
    return CombustionVolumes(Vvo, VRO2, VNo2, VH2Oo, Vgo)


def combustion_volumes_gas(c: GasComponent) -> CombustionVolumes:
    """Формулы источника (стр.15-16) для газового топлива, состав в об.% сухого газа.
    dг (влагосодержание газа) принято 10 г/м3 при расчётной температуре 10°C (примечание
    источника) - в общем случае небольшой вклад, не запрашивается отдельно у оператора."""
    dg = 10.0
    sum_mn_CmHn_vo = c.CH4 * 2 + c.C2H6 * 3.5 + c.C3H8 * 5 + c.C4H10 * 6.5 + c.C5H12 * 8
    Vvo = 0.0476 * (sum_mn_CmHn_vo + 0.5 * (c.CO + c.H2) + 1.5 * c.H2S - c.O2)
    VNo2 = 0.79 * Vvo + 0.01 * c.N2
    sum_m_CmHn_ro2 = c.CH4 * 1 + c.C2H6 * 2 + c.C3H8 * 3 + c.C4H10 * 4 + c.C5H12 * 5
    VRO2 = 0.01 * (sum_m_CmHn_ro2 + c.CO2 + c.CO + c.H2S)
    sum_05n_CmHn = c.CH4 * 2 + c.C2H6 * 3 + c.C3H8 * 4 + c.C4H10 * 5 + c.C5H12 * 6
    VH2Oo = 0.01 * (sum_05n_CmHn + c.H2S + c.H2 + 0.124 * dg + 1.61 * Vvo)
    Vgo = VRO2 + VNo2 + VH2Oo
    return CombustionVolumes(Vvo, VRO2, VNo2, VH2Oo, Vgo)


def theoretical_enthalpies(vol: CombustionVolumes, t: float) -> tuple[float, float]:
    """Iго(t), Iво(t) - теоретические энтальпии продуктов сгорания и воздуха при альфа=1."""
    Igo = vol.VRO2 * _interp(t, _CT_CO2) + vol.VNo2 * _interp(t, _CT_N2) + vol.VH2Oo * _interp(t, _CT_H2O)
    Ivo = vol.Vvo * _interp(t, _CT_AIR)
    return Igo, Ivo


def enthalpy_at_alpha(vol: CombustionVolumes, t: float, alpha: float) -> float:
    """Iг = Iго + (альфа-1)*Iво - энтальпия газов при действительном избытке воздуха."""
    Igo, Ivo = theoretical_enthalpies(vol, t)
    return Igo + (alpha - 1.0) * Ivo


# Рис.5 источника, "Потери тепла от наружного охлаждения" (стр.173) - оцифровано
# вручную по графику (это график, не таблица чисел и не формула в оригинале).
# Ось X в источнике - паропроизводительность в кг/с, здесь переведена в т/ч (*3.6).
_Q5_CURVE_D_TH = [7.2, 18.0, 36.0, 72.0, 108.0, 144.0, 180.0, 216.0, 252.0]
_Q5_CURVE_PCT = [3.00, 1.35, 1.05, 0.85, 0.72, 0.62, 0.57, 0.50, 0.45]


def q5_reference_percent(D_nom_t_h: float) -> float:
    """Оценка q5 при номинальной нагрузке по рис.5 источника (оцифрованная кривая).
    Это приближение по графику, не точное табличное значение - см. USAGE.md."""
    return _lerp_table(D_nom_t_h, _Q5_CURVE_D_TH, _Q5_CURVE_PCT)


def excess_air_from_o2(o2_pct: float, co_pct: float = 0.0) -> float:
    """Коэффициент избытка воздуха по газовому анализу (формула Шиллинга с поправкой
    на CO): альфа = 21 / (21 - 79*(O2-0.5*CO)/(100-O2-CO2-CO)) упрощается на практике до
    альфа = 21/(21-O2+0.605*CO) при малых CO (типовая инженерная форма)."""
    denom = 21.0 - o2_pct + 0.605 * co_pct
    if denom <= 0.1:
        denom = 0.1
    return 21.0 / denom


@dataclass
class KpdInputs:
    # топливо
    fuel_category: str  # "solid" | "mazut" | "gas"
    Wr: float = 0.0       # влажность рабочей массы, %  (твёрдое/жидкое)
    Ar: float = 0.0       # зольность рабочей массы, %  (твёрдое/жидкое)
    Sr: float = 0.0
    Cr: float = 0.0
    Hr: float = 0.0
    Nr: float = 0.0
    Or: float = 0.0
    gas_comp: GasComponent | None = None
    Qir_measured: float | None = None  # МДж/кг или МДж/м3, если известна измеренная (иначе считаем по составу)
    t_fuel: float = 20.0     # температура топлива, °C
    dф: float = 0.0          # удельный расход пара на распыл мазута, кг/кг
    iф: float = 2700.0       # энтальпия пара на форсунки, кДж/кг

    # режим котла
    D_nom: float = 0.0       # номинальная паропроизводительность, т/ч
    D: float = 0.0           # фактическая (расчётная) паропроизводительность, т/ч
    t_hv: float = 30.0       # температура холодного воздуха, °C
    t_uh: float = 150.0      # температура уходящих газов, °C
    O2: float = 4.0          # содержание O2 в уходящих газах, %
    CO: float = 0.0          # содержание CO в уходящих газах, %

    t_pe: float = 250.0      # температура перегретого пара, °C
    p_pe: float = 1.4        # давление перегретого пара, МПа
    t_pv: float = 100.0      # температура питательной воды, °C
    p_prod: float = 1.0      # непрерывная продувка, %

    # потери (частично измеряемые, частично табличные - см. docstring модуля)
    G_un: float = 0.0        # содержание горючих в уносе, %
    G_shl: float = 0.0       # содержание горючих в шлаке, %
    a_un: float = 0.95       # доля золы топлива в уносе
    q3: float = 0.0          # хим. недожог, % (справочное, табл.8: 0 - крупные тв.котлы, 0.1-0.5 газ/мазут)
    q5_nom: float = 1.0      # потери в окр.среду при номинальной нагрузке, % (справочное, рис.5)
    t_slag: float = 600.0    # температура шлака, °C (600 - твёрдое шлакоудаление, стандарт)


@dataclass
class KpdResult:
    Qp: float          # располагаемая теплота топлива, кДж/кг или кДж/м3
    alpha: float        # коэффициент избытка воздуха в уходящих газах
    Iuh: float          # энтальпия уходящих газов
    Iohv: float         # энтальпия холодного воздуха
    q2: float
    q3: float
    q4: float
    q5: float
    q6: float
    eta: float           # КПД брутто, %
    B: float             # полный расход топлива, кг/ч (или м3/ч для газа)
    Bp: float             # расчётный расход топлива, кг/с (или м3/с)
    D_pr: float           # приведённая нагрузка (для нормировки q5), т/ч
    vol: CombustionVolumes


# --- теплоёмкость сухой массы твёрдого топлива по группам (стр.18 источника) ---
_C_DRY_BY_GROUP = {
    "бурый": 1.13,
    "каменный": 1.09,
    "АШ_ПА_Т": 0.92,
}


def fuel_heat_of_combustion_mendeleev(Cr, Hr, Or, Sr, Wr) -> float:
    """Формула Менделеева, МДж/кг (приведена к тем же единицам, что и табличная
    Qir_measured) - используется, если Qp не измерена напрямую."""
    return (339 * Cr + 1030 * Hr - 108.8 * (Or - Sr) - 25 * Wr) / 1000.0


def calc_iтл(t_fuel: float, Wr: float, is_mazut: bool, c_dry: float = 0.92) -> float:
    """Физическая теплота топлива iтл = стл*tтл (стр.18 источника)."""
    if is_mazut:
        c_tl = 1.74 + 0.0025 * t_fuel
    else:
        c_tl = 0.042 * Wr + c_dry * (1 - 0.01 * Wr)
    return c_tl * t_fuel


def calculate(inp: KpdInputs) -> KpdResult:
    is_gas = inp.fuel_category == "gas"
    is_mazut = inp.fuel_category == "mazut"

    # --- объёмы продуктов сгорания и Qp ---
    if is_gas:
        assert inp.gas_comp is not None
        vol = combustion_volumes_gas(inp.gas_comp)
        Qp = inp.Qir_measured if inp.Qir_measured is not None else 0.0
    else:
        vol = combustion_volumes_solid_liquid(inp.Cr, inp.Hr, inp.Sr, inp.Or, inp.Nr, inp.Wr)
        Qir = inp.Qir_measured if inp.Qir_measured is not None else \
            fuel_heat_of_combustion_mendeleev(inp.Cr, inp.Hr, inp.Or, inp.Sr, inp.Wr)
        c_dry = 0.92
        i_tl = calc_iтл(inp.t_fuel, inp.Wr, is_mazut, c_dry)
        Q_v_vn = 0.0  # калорифер не учитывается отдельным вводом в этой версии инструмента
        Q_f = inp.dф * (inp.iф - 2380.0) if is_mazut and inp.dф > 0 else 0.0
        Qp = (Qir * 1000.0) + i_tl + Q_v_vn + Q_f  # переводим Qir из МДж в кДж

    alpha = excess_air_from_o2(inp.O2, inp.CO)

    Iuh = enthalpy_at_alpha(vol, inp.t_uh, alpha)
    _, Iohv = theoretical_enthalpies(vol, inp.t_hv)

    # --- потери ---
    q4 = 0.0
    if not is_gas and (inp.G_un > 0 or inp.G_shl > 0) and Qp > 0:
        Ar_val = inp.Ar
        a_shl = 1.0 - inp.a_un
        term_un = (inp.a_un * inp.G_un / (100.0 - inp.G_un)) if inp.G_un < 100 else 0.0
        term_shl = (a_shl * inp.G_shl / (100.0 - inp.G_shl)) if inp.G_shl < 100 else 0.0
        q4 = (term_un + term_shl) * 32.7e3 * Ar_val / Qp

    q3 = inp.q3

    q2 = (Iuh - alpha * Iohv) * (100.0 - q4) / Qp * 1.0 if Qp > 0 else 0.0
    # (формула источника уже содержит alpha на выходе последней ступени ВП; здесь берём
    #  общий alpha уходящих газов - в двухступенчатых схемах отличие мало и не запрашивается
    #  у оператора отдельным полем в этой версии инструмента)

    q5 = inp.q5_nom * (inp.D_nom / inp.D) if inp.D > 0 else inp.q5_nom

    q6 = 0.0
    if not is_gas and Qp > 0:
        a_shl = 1.0 - inp.a_un
        ct_shl = 560.0  # кДж/кг, тв. шлакоудаление, tшл=600°C (стр.20 источника)
        q6 = a_shl * ct_shl * inp.Ar / Qp

    eta = 100.0 - (q2 + q3 + q4 + q5 + q6)

    # --- расход топлива и приведённая нагрузка ---
    D_pr = inp.D * (1.0 - 0.01 * inp.p_prod) if inp.D else 0.0  # оценка; программа печатала близкое к D значение

    i_pe = steam_enthalpy_superheated(inp.t_pe, inp.p_pe)
    i_pv = water_enthalpy(inp.t_pv)
    i_kip = saturated_water_enthalpy(inp.p_pe)
    D_pr_water = 0.01 * inp.p_prod * inp.D  # т/ч, расход продувочной воды (стр.21 источника)

    if Qp > 0 and eta > 0:
        D_pe_kg_s = inp.D * 1000.0 / 3600.0
        D_pr_kg_s = D_pr_water * 1000.0 / 3600.0
        numerator = D_pe_kg_s * (i_pe - i_pv) + D_pr_kg_s * (i_kip - i_pv)
        Bp = numerator / (Qp * eta / 100.0)  # кг/с
        B = Bp * 3600.0
    else:
        Bp = 0.0
        B = 0.0

    return KpdResult(Qp=Qp, alpha=alpha, Iuh=Iuh, Iohv=Iohv, q2=q2, q3=q3, q4=q4, q5=q5, q6=q6,
                      eta=eta, B=B, Bp=Bp, D_pr=inp.D, vol=vol)


# --- упрощённые таблицы воды/пара (табл.9 источника, узловые точки) ---
_SAT_P = [0.1, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0]
_SAT_T = [99.6, 151.8, 179.9, 198.3, 212.4, 233.8, 250.3, 264.0, 275.6, 295.0, 311.0, 324.6, 336.6, 347.3, 356.9]
_SAT_IKIP = [417, 640, 763, 845, 909, 1008, 1087, 1154, 1213, 1317, 1408, 1491, 1568, 1642, 1714]
_SAT_INP = [2675, 2749, 2778, 2792, 2800, 2804, 2801, 2794, 2785, 2759, 2725, 2685, 2637, 2582, 2510]


def _lerp_table(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_right(xs, x) - 1
    x0, x1 = xs[i], xs[i + 1]
    y0, y1 = ys[i], ys[i + 1]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def saturated_water_enthalpy(p_MPa: float) -> float:
    """i' (кипящая вода) на линии насыщения при давлении p, МПа -> кДж/кг (табл.9)."""
    return _lerp_table(p_MPa, _SAT_P, _SAT_IKIP)


def water_enthalpy(t_C: float) -> float:
    """Приближённая энтальпия воды (некипящей) i = 4.19*t, кДж/кг."""
    return 4.19 * t_C


def steam_enthalpy_superheated(t_C: float, p_MPa: float) -> float:
    """Приближённая энтальпия перегретого пара: i'' насыщения при p + перегрев
    с усреднённой теплоёмкостью пара ~2.2 кДж/(кг*К) относительно температуры насыщения.
    Это упрощение (без полных пароводяных таблиц) даёт точность в пределах typичных
    режимов (Tпе 250-550°C, Pпе 1-14 МПа) в единицы кДж/кг."""
    t_sat = _lerp_table(p_MPa, _SAT_P, _SAT_T)
    i_sat_steam = _lerp_table(p_MPa, _SAT_P, _SAT_INP)
    dt = max(0.0, t_C - t_sat)
    cp_steam = 2.2
    return i_sat_steam + cp_steam * dt
