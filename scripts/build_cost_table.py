"""Формирование Excel-таблицы стоимости и применения в проекте СЕЙСМОС.

Данные о закупках взяты из кассовых чеков Ozon (cheque_*.pdf в корне
репозитория). Стоимость геофонов GS-20DX и субблоков Медуза ЯИНТ.468332.018
оставлена пустой — она задаётся отдельно.

Запуск:
    python scripts/build_cost_table.py
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

OUT = Path(__file__).resolve().parent.parent / "docs" / "cost" / "СЕЙСМОС_стоимость_и_применение.xlsx"

THIN = Side(style="thin", color="B0B0B0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HDR_FILL = PatternFill("solid", fgColor="1F4E79")
HDR_FONT = Font(bold=True, color="FFFFFF", size=11)
GRP_FONT = Font(bold=True, size=11)
GRP_FILL = PatternFill("solid", fgColor="DDEBF7")
NOTE_FONT = Font(italic=True, color="808080")
SUM_FILL = PatternFill("solid", fgColor="FFF2CC")
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center")

HEADERS = ["№", "Наименование", "Модель / артикул", "Кол-во", "Ед.",
           "Цена, руб", "Сумма, руб", "Назначение в проекте", "Чек №", "Дата чека"]

# (тип, наименование, модель, кол-во, ед, цена, сумма, назначение, чек, дата)
ROWS = [
    ("grp", "Датчики и аналого-цифровое преобразование"),
    ("item", "Геофон сейсмический", "GS-20DX", 30, "шт", None, None,
     "Чувствительный элемент; последовательная цепочка вдоль периметра", "", ""),
    ("item", "Субблок Медуза", "ЯИНТ.468332.018", 30, "шт", None, None,
     "Приёмно-обрабатывающий субблок периметрового сегмента", "", ""),
    ("item", "Модуль АЦП", "ADS131M08", 6, "шт", None, 11886.99,
     "Оцифровка сигналов геофонов (цены в чеках различаются)", "1212, 454, 829", "29.10.2026 / 02.11.2026"),

    ("grp", "Связь и передача данных"),
    ("item", "Коммутатор", "—", 7, "шт", 218.76, 1531.32,
     "Объединение узлов сбора в сеть", "1217", "21.10.2026"),
    ("item", "Модуль Ethernet-UART", "WT32-ETH01", 20, "шт", 408.03, 8160.60,
     "Сетевой интерфейс узла сбора (данные по Ethernet)", "829", "02.11.2026"),

    ("grp", "Питание"),
    ("item", "PoE-сплиттер (наружный)", "Plug & Play", 1, "шт", 275.13, 275.13,
     "Питание узла сбора через Ethernet", "788", "28.09.2026"),
    ("item", "PoE удлинитель-разветвитель", "RJ45 1→2", 1, "шт", 543.81, 543.81,
     "Разветвление PoE-линии", "1498", "17.10.2026"),
    ("item", "Понижающий преобразователь DC-DC", "LM2596S (8-40В → 5В), 10 шт", 2, "набор", 860.76, 1721.52,
     "Питание плат узла сбора", "719", "21.10.2026"),

    ("grp", "Кабельная продукция и разъёмы"),
    ("item", "Кабель витая пара UTP CCA, 305 м", "UTP CCA 305м PE", 2, "бухта", 7724.50, 15449.00,
     "Соединительные линии цепочки датчиков", "728", "29.10.2026"),
    ("item", "Модуль соединительный RJ45 герметичный", "8P8C IP68, компл. 10 шт", 1, "компл", 474.00, 474.00,
     "Герметичные соединения уличной линии", "171", "30.09.2026"),
    ("item", "Коннектор RJ45 сквозной", "Cat.6, 25 шт/упак", 2, "упак", 185.47, 370.94,
     "Оконцевание кабельных линий", "2149", "29.10.2026"),

    ("grp", "Монтаж и корпуса"),
    ("item", "Корпус приборный универсальный", "GAINTA G1022B (ABS)", 6, "шт", 228.27, 1369.62,
     "Корпуса узлов сбора", "306", "29.10.2026"),
    ("item", "Провод соединительный", "Dupont мама-мама, 10 см, 40 шт", 1, "компл", 122.91, 122.91,
     "Монтаж внутренних соединений", "748", "17.09.2026"),

    ("grp", "Электронные компоненты"),
    ("item", "Плата-переходник SMD→DIP", "SO8/TSSOP8/SOIC8/SOP8/SSOP-8, 20 шт", 1, "упак", 239.68, 239.68,
     "Монтаж микросхем", "1137", "21.10.2026"),
    ("item", "Конденсатор керамический 0,01 мкФ", "10 нФ, 50В, X7R (марк. 103), 20 шт", 3, "упак", 131.25, 393.75,
     "Фильтрация цепей питания/сигнала", "1139", "21.10.2026"),
    ("item", "Конденсатор керамический 0,01 мкФ", "10 нФ, 50В, X7R (марк. 103), 20 шт", 3, "упак", 123.64, 370.92,
     "Фильтрация цепей питания/сигнала", "719", "21.10.2026"),
    ("item", "Конденсатор керамический 0,1 мкФ", "100 нФ, 50В, X7R (марк. 104), 50 шт", 1, "упак", 220.66, 220.66,
     "Фильтрация цепей питания/сигнала", "1139", "21.10.2026"),
    ("item", "Конденсатор керамический 0,1 мкФ", "100 нФ, 50В, X7R (марк. 104), 50 шт", 1, "упак", 219.71, 219.71,
     "Фильтрация цепей питания/сигнала", "719", "21.10.2026"),

    ("grp", "Микросхемы и радиодетали (ЧИП и ДИП)"),
    ("item", "Микросхема — операционный усилитель", "MCP602T-I/SN, SOIC-8", 50, "шт", 57.90, 2895.00,
     "Входные усилители сигналов геофонов", "18028230, 18031641", "06–07.10.2026"),
    ("item", "Резистор металлоплёночный 10 кОм, 1%", "MF-25 (С2-23)", 200, "шт", 7.60, 1520.00,
     "Цепи усиления и фильтрации", "18028230, 18031641", "06–07.10.2026"),
    ("item", "Резистор металлоплёночный 430 Ом, 1%", "MF-25 (С2-23)", 50, "шт", 6.65, 332.50,
     "Цепи усиления и фильтрации", "18028230, 18031641", "06–07.10.2026"),
    ("item", "Резистор металлоплёночный 20 кОм, 1%", "MF-25 (С2-23)", 100, "шт", 7.60, 760.00,
     "Цепи усиления и фильтрации", "18028230, 18031641", "06–07.10.2026"),
    ("item", "Резистор углеродистый 100 Ом, 5%", "CF-25 (С1-4)", 100, "шт", 6.65, 665.00,
     "Цепи усиления и фильтрации", "18028230, 18031641", "06–07.10.2026"),
    ("item", "Резистор металлоплёночный 1 кОм, 1%", "MBB02070C1001FCT00 (Vishay)", 100, "шт", 11.40, 1140.00,
     "Цепи усиления и фильтрации", "18028230, 18031641", "06–07.10.2026"),

    ("grp", "Прочее"),
    ("item", "Клей шиноремонтный", "готовый раствор, 120 мл", 2, "шт", 152.00, 152.00,
     "Монтажные работы", "2095", "11.09.2026"),
    ("item", "Обработка заказа в ПВЗ (доставка, Ozon)", "—", 15, "усл", None, 1936.44,
     "Логистика заказов Ozon (сервисный сбор по всем чекам)", "все чеки Ozon", "—"),
]

NOTES = [
    "Примечания:",
    "• Стоимость геофонов GS-20DX (30 шт) и субблоков Медуза ЯИНТ.468332.018 (30 шт) не указана — оставлена пустой.",
    "• Цены взяты из кассовых чеков Ozon (cheque_*.pdf) и заказов ЧИП и ДИП (папка «Чеки/»).",
    "• Позиция «Обработка заказа в ПВЗ» — сервисный сбор за доставку по чекам Ozon; суммарно по всем чекам.",
    "• Для модулей АЦП ADS131M08 цены в чеках различаются (1961,19 / 1966,90 / 2018,26 руб), поэтому указана итоговая сумма.",
    "• Заказы ЧИП и ДИП 18028230 и 18031641 содержат один и тот же состав радиодеталей (итог 3 656,25 руб каждый).",
    "• Итог считается формулой Excel по столбцу «Сумма, руб».",
]

# Реестр чеков: (чек №, дата, сумма, состав)
RECEIPTS = [
    ("2095", "11.09.2026", 152.00, "Клей шиноремонтный, 120 мл — 2 шт"),
    ("748", "17.09.2026", 130.00, "Провод Dupont мама-мама, 40 шт + доставка"),
    ("788", "28.09.2026", 291.00, "PoE-сплиттер наружный + доставка"),
    ("171", "30.09.2026", 474.00, "Модуль соединительный RJ45 IP68, компл. 10 шт"),
    ("1498", "17.10.2026", 571.00, "PoE удлинитель-разветвитель RJ45 1→2 + доставка"),
    ("1217", "21.10.2026", 1610.00, "Коммутатор — 7 шт + доставка"),
    ("1137", "21.10.2026", 252.00, "Плата-переходник SO8/TSSOP8/SOIC8/SOP8/SSOP-8, 20 шт + доставка"),
    ("1139", "21.10.2026", 646.00, "Конденсаторы 0,01 мкФ (3 упак) и 0,1 мкФ (1 упак) + доставка"),
    ("719", "21.10.2026", 2431.00, "Конденсаторы 0,01/0,1 мкФ + LM2596S (2 набора по 10 шт) + доставка"),
    ("1212", "29.10.2026", 2068.00, "Модуль АЦП ADS131M08 — 1 шт + доставка"),
    ("728", "29.10.2026", 15974.00, "Кабель UTP CCA 305 м — 2 бухты + доставка"),
    ("2149", "29.10.2026", 390.00, "Коннектор RJ45 Cat.6, 25 шт/упак — 2 упак + доставка"),
    ("306", "29.10.2026", 1440.00, "Корпус GAINTA G1022B — 6 шт + доставка"),
    ("454", "02.11.2026", 6186.00, "Модуль АЦП ADS131M08 — 3 шт + доставка"),
    ("829", "02.11.2026", 12824.00, "Модуль АЦП ADS131M08 — 2 шт, WT32-ETH01 — 20 шт + доставка"),
    ("18028230", "06.10.2026", 3656.25, "ЧИП и ДИП: ОУ MCP602T — 25 шт, резисторы MF-25/CF-25/Vishay"),
    ("18031641", "07.10.2026", 3656.25, "ЧИП и ДИП: ОУ MCP602T — 25 шт, резисторы MF-25/CF-25/Vishay"),
]


def build_receipts_sheet(wb) -> None:
    ws = wb.create_sheet("Чеки")
    headers = ["№ чека", "Дата", "Сумма, руб", "Состав заказа"]
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = CENTER
        cell.border = BORDER

    r = 2
    for num, date, total, content in RECEIPTS:
        ws.cell(row=r, column=1, value=num).alignment = CENTER
        ws.cell(row=r, column=2, value=date).alignment = CENTER
        tc = ws.cell(row=r, column=3, value=total)
        tc.number_format = "#,##0.00"
        ws.cell(row=r, column=4, value=content).alignment = WRAP
        for c in range(1, len(headers) + 1):
            ws.cell(row=r, column=c).border = BORDER
        r += 1

    ws.cell(row=r, column=2, value="ИТОГО по чекам").font = Font(bold=True)
    ws.cell(row=r, column=3, value=f"=SUM(C2:C{r - 1})")
    ws.cell(row=r, column=3).number_format = "#,##0.00"
    ws.cell(row=r, column=3).font = Font(bold=True)
    for c in range(1, len(headers) + 1):
        ws.cell(row=r, column=c).fill = SUM_FILL
        ws.cell(row=r, column=c).border = BORDER

    for i, w in enumerate([10, 12, 13, 70], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Смета"

    ws.append(HEADERS)
    for c in range(1, len(HEADERS) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HDR_FILL
        cell.font = HDR_FONT
        cell.alignment = CENTER
        cell.border = BORDER

    r = 2
    num = 0
    for row in ROWS:
        if row[0] == "grp":
            ws.cell(row=r, column=1, value=row[1]).font = GRP_FONT
            for c in range(1, len(HEADERS) + 1):
                ws.cell(row=r, column=c).fill = GRP_FILL
                ws.cell(row=r, column=c).border = BORDER
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(HEADERS))
            r += 1
            continue

        _, name, model, qty, unit, price, total, purpose, cheque, date = row
        num += 1
        ws.cell(row=r, column=1, value=num).alignment = CENTER
        ws.cell(row=r, column=2, value=name).alignment = WRAP
        ws.cell(row=r, column=3, value=model).alignment = WRAP
        ws.cell(row=r, column=4, value=qty).alignment = CENTER
        ws.cell(row=r, column=5, value=unit).alignment = CENTER
        pc = ws.cell(row=r, column=6, value=price)
        tc = ws.cell(row=r, column=7, value=total)
        if price is not None:
            pc.number_format = "#,##0.00"
        if total is not None:
            tc.number_format = "#,##0.00"
        ws.cell(row=r, column=8, value=purpose).alignment = WRAP
        ws.cell(row=r, column=9, value=cheque).alignment = CENTER
        ws.cell(row=r, column=10, value=date).alignment = CENTER
        for c in range(1, len(HEADERS) + 1):
            ws.cell(row=r, column=c).border = BORDER
        r += 1

    ws.cell(row=r, column=2, value="ИТОГО по позициям (без стоимости Медуз, геофонов и доставки)").font = Font(bold=True)
    ws.cell(row=r, column=7, value=f"=SUM(G2:G{r - 1})")
    ws.cell(row=r, column=7).number_format = "#,##0.00"
    ws.cell(row=r, column=7).font = Font(bold=True)
    for c in range(1, len(HEADERS) + 1):
        ws.cell(row=r, column=c).fill = SUM_FILL
        ws.cell(row=r, column=c).border = BORDER
    r += 2

    for n in NOTES:
        c = ws.cell(row=r, column=1, value=n)
        c.font = Font(bold=True) if n.endswith(":") else NOTE_FONT
        r += 1

    for i, w in enumerate([4, 34, 30, 7, 7, 12, 13, 40, 14, 20], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    build_receipts_sheet(wb)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"Сохранено: {OUT}")


if __name__ == "__main__":
    main()
