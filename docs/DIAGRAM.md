# Блок-схемы СЕЙСМОС

Документ содержит блок-схемы системы контроля периметра **СЕЙСМОС** на
сейсмических геофонах GS-20DX. Схемы приведены в формате Mermaid и
отображаются на GitHub напрямую; готовые изображения лежат в `docs/img/`.

Содержание:

1. [Общая архитектура](#1-общая-архитектура)
2. [Поток данных](#2-поток-данных)
3. [Алгоритм обнаружения события](#3-алгоритм-обнаружения-события)
4. [Классификация и уровни](#4-классификация-и-уровни)
5. [Конечный автомат состояний системы](#5-конечный-автомат-состояний-системы)
6. [Жизненный цикл тревоги](#6-жизненный-цикл-тревоги)
7. [Схема развёртывания](#7-схема-развёртывания)
8. [Аппаратный сегмент и цепочка датчиков](#8-аппаратный-сегмент-и-цепочка-датчиков)

---

## 1. Общая архитектура

Система разделена на четыре слоя. Каждый слой развивается и тестируется
независимо, связь между слоями — через структуры данных (`ChainSample`,
`DetectionEvent`, `Alarm`).

```mermaid
flowchart TB
    subgraph HW["Аппаратный слой — seismos/hardware"]
        GEO["Геофон GS-20DX<br/>geophone.py"]
        ADC["АЦП ADS1256 / SPI<br/>adc.py"]
        NODE["Узел сбора, PoE + UDP<br/>node.py"]
        CHAIN["Цепочка датчиков<br/>chain.py"]
        SIM["Генератор сигналов<br/>simulator.py"]
    end

    subgraph DSP["Слой обработки — seismos/detection"]
        BAND["Полосовой фильтр<br/>dsp.py"]
        DET["Обнаружитель STA/LTA + CFAR<br/>staltl.py"]
        CLS["Классификатор воздействий<br/>classifier.py"]
    end

    subgraph CORE["Ядро — seismos/core"]
        MODELS["Модели данных<br/>models.py"]
        CONFIG["Конфигурация<br/>config.py"]
        REG["Реестр датчиков и зон<br/>registry.py"]
        ENG["Движок обработки<br/>engine.py"]
        STORE["Хранилище SQLite<br/>store.py"]
        BUS["Шина событий<br/>bus.py"]
    end

    subgraph APP["Прикладной слой"]
        API["REST + WebSocket API<br/>api/app.py"]
        CLI["Командная строка<br/>cli/main.py"]
        UI["Веб-консоль оператора<br/>console/"]
    end

    GEO --> ADC --> NODE --> CHAIN
    SIM --> CHAIN
    CHAIN -->|ChainSample| ENG
    ENG --> BAND --> DET --> CLS
    CLS -->|DetectionEvent| ENG
    MODELS -.-> ENG
    CONFIG -.-> ENG
    REG -.-> ENG
    ENG --> STORE
    ENG --> BUS
    BUS --> API
    STORE --> API
    API --> UI
    API --> CLI
```

![Блок-схема 01-architecture](img/diagram/01-architecture.png)


## 2. Поток данных

Путь от физического воздействия на грунт до тревоги на посту оператора.

```mermaid
flowchart LR
    A["Воздействие<br/>шаги, техника, подкоп"] --> B["Геофон GS-20DX<br/>напряжение, В"]
    B --> C["АЦП ADS1256<br/>24 бита, SPI"]
    C --> D["Нормировка<br/>В → мкм/с"]
    D --> E["Узел сбора<br/>пакет UDP, PoE"]
    E --> F["ChainReader<br/>ChainSample"]
    F --> G["ProcessingEngine.ingest"]
    G --> H["SeismicDetector.process"]
    H --> I["Classifier.classify"]
    I --> J["DetectionEvent"]
    J --> K["EventStore<br/>SQLite"]
    J --> L["EventBus.publish"]
    L --> M["WebSocket /ws"]
    M --> N["Консоль оператора"]
    J -->|уровень ≥ ТРЕВОГА<br/>и зона под охраной| O["Alarm"]
    O --> K
    O --> L
```

![Блок-схема 02-dataflow](img/diagram/02-dataflow.png)


### Единица данных — `ChainSample`

`ChainSample` — блок отсчётов одного датчика (скорость грунта, мкм/с) с
меткой времени и порядковым номером. Движок принимает именно эти объекты,
поэтому источником может быть как реальный узел сбора, так и генератор
синтетических сигналов.

```mermaid
classDiagram
    class ChainSample {
        +str sensor_id
        +datetime ts
        +int seq
        +ndarray samples
        +sample_rate
    }
    class DetectionEvent {
        +str id
        +str sensor_id
        +str zone_id
        +EventKind kind
        +EventLevel level
        +EventClass event_class
        +float confidence
        +float ratio
        +float peak
        +float duration_s
        +float dominant_hz
    }
    class Alarm {
        +str id
        +str sensor_id
        +str zone_id
        +EventLevel level
        +EventClass event_class
        +float confidence
        +list event_ids
        +AlarmState state
    }
    ChainSample --> DetectionEvent : обработка
    DetectionEvent --> Alarm : уровень ≥ ТРЕВОГА
```

![Блок-схема 03-classes](img/diagram/03-classes.png)


## 3. Алгоритм обнаружения события

Основной конвейер обработки одного канала геофона. Реализация —
`SeismicDetector.process()`.

```mermaid
flowchart TD
    START(["Блок отсчётов<br/>ChainSample.samples"]) --> BP["Полосовой фильтр<br/>5–120 Гц (каскад биквадов)"]
    BP --> FRAME["Нарезка на кадры<br/>frame_len = 64"]
    FRAME --> RMS["Расчёт уровня<br/>СКЗ кадра + пик"]
    RMS --> STA["STA/LTA<br/>отношение короткого окна к длинному"]
    STA --> CFAR["CFAR-порог<br/>адаптивный, по фону"]
    CFAR --> ACTIVE{"Событие<br/>активно?"}

    ACTIVE -->|нет| TRIG{"ratio ≥ trigger_ratio<br/>И cfar_hit?"}
    TRIG -->|нет| NEXT["Следующий кадр"]
    TRIG -->|да| OPEN["Открыть событие<br/>запомнить начало, пик"]
    OPEN --> NEXT

    ACTIVE -->|да| ACC["Накопить кадр<br/>обновить пик и максимум ratio"]
    ACC --> HOLD{"ratio ><br/>release_ratio?"}
    HOLD -->|да| KEEP["Продлить удержание"]
    HOLD -->|нет| DEC["Уменьшить удержание"]
    KEEP --> CLOSE{"Удержание = 0<br/>И длительность ≥ min<br/>ИЛИ длительность ≥ max?"}
    DEC --> CLOSE
    CLOSE -->|нет| NEXT
    CLOSE -->|да| CORE["Выделить энергетическое ядро<br/>участок выше 0.25·пик"]
    CORE --> FEAT["Признаки: длительность, СКЗ, пик,<br/>ZCR, доминирующая и центральная частота"]
    FEAT --> RESULT(["DetectorResult<br/>ended = true"])
    NEXT --> FRAME
```

![Блок-схема 04-detection](img/diagram/04-detection.png)


## 4. Классификация и уровни

Классификатор по вектору признаков определяет класс воздействия, класс
отображается в уровень значимости события (`CLASS_LEVEL`).

```mermaid
flowchart LR
    FEAT["Признаки события<br/>duration, peak, rms,<br/>dominant_hz, centroid_hz,<br/>zcr, ratio"] --> CLASS["Classifier.classify<br/>взвешенные гауссовы оценки"]
    CLASS --> EC{"Класс"}

    EC -->|weather / none| L0["Уровень 0 — ШУМ"]
    EC -->|footstep / unknown| L1["Уровень 1 — ПРЕДУПРЕЖДЕНИЕ"]
    EC -->|group / impact| L2["Уровень 2 — ТРЕВОГА"]
    EC -->|vehicle / digging /<br/>climb / tamper| L3["Уровень 3 — ПРОНИКНОВЕНИЕ"]

    L0 --> OUT(["DetectionEvent<br/>kind + level + confidence"])
    L1 --> OUT
    L2 --> OUT
    L3 --> OUT
```

![Блок-схема 05-classification](img/diagram/05-classification.png)


| Класс воздействия | Код | Уровень |
|---|---|---|
| Метео, шум | `weather`, `none` | 0 — ШУМ |
| Шаги, неизвестное | `footstep`, `unknown` | 1 — ПРЕДУПРЕЖДЕНИЕ |
| Группа людей, удар | `group`, `impact` | 2 — ТРЕВОГА |
| Техника, подкоп, перелаз, вскрытие | `vehicle`, `digging`, `climb`, `tamper` | 3 — ПРОНИКНОВЕНИЕ |

## 5. Конечный автомат состояний системы

Режимы работы системы (`SystemState`) и переходы между ними.

```mermaid
stateDiagram-v2
    [*] --> DISARMED
    DISARMED --> ARMING : arm()
    ARMING --> ARMED : все зоны готовы
    ARMED --> DISARMED : disarm()
    ARMED --> ALARM : событие уровня ≥ ТРЕВОГА<br/>в зоне под охраной
    ALARM --> ARMED : все тревоги сброшены
    ALARM --> DISARMED : disarm()
```

![Блок-схема 06-state-machine](img/diagram/06-state-machine.png)


| Состояние | Описание |
|---|---|
| `disarmed` | Система снята с охраны, события только пишутся в журнал |
| `arming` | Переход к охране (проверка готовности датчиков) |
| `armed` | Система на охране, тревоги формируются |
| `alarm` | Зафиксирована тревога, требуется реакция оператора |

## 6. Жизненный цикл тревоги

Тревога формируется движком при событии уровня ≥ ТРЕВОГА в зоне под охраной
(`AlarmState`).

```mermaid
flowchart LR
    EV["DetectionEvent<br/>уровень ≥ ТРЕВОГА"] --> GATE{"Зона под охраной<br/>И состояние ARMED/ALARM?"}
    GATE -->|нет| LOG["Только запись<br/>в журнал"]
    GATE -->|да| CREATE["Создать Alarm<br/>состояние ACTIVE"]
    CREATE --> PUB["Публикация в EventBus"]
    PUB --> CONSOLE["Тревожный монитор<br/>консоли оператора"]
    CONSOLE --> ACK{"Действие<br/>оператора"}
    ACK -->|подтвердить| ACKD["ACKNOWLEDGED<br/>оператор принял к работе"]
    ACK -->|сбросить| RESET["RESET<br/>тревога закрыта"]
    ACKD --> RESET
    RESET --> CLEAR{"Все тревоги<br/>закрыты?"}
    CLEAR -->|да| ARMED["Состояние → ARMED"]
    CLEAR -->|нет| CONSOLE
```

![Блок-схема 07-alarm-lifecycle](img/diagram/07-alarm-lifecycle.png)


## 7. Схема развёртывания

Варианты запуска системы: локально, в Docker и под systemd.

```mermaid
flowchart TB
    subgraph FIELD["Объект охраны"]
        S1["Геофон 1<br/>GS-20DX + АЦП"]
        S2["Геофон 2<br/>GS-20DX + АЦП"]
        SN["Геофон N<br/>GS-20DX + АЦП"]
        SW["Коммутатор PoE"]
        S1 --> SW
        S2 --> SW
        SN --> SW
    end

    subgraph SERVER["Сервер / пост охраны"]
        APP["Процесс СЕЙСМОС<br/>движок + API"]
        DB[("SQLite<br/>журнал и тревоги")]
        APP --> DB
    end

    subgraph CLIENT["Рабочее место оператора"]
        BROWSER["Браузер<br/>веб-консоль"]
    end

    SW -->|"UDP-пакеты отсчётов"| APP
    APP -->|"REST + WebSocket"| BROWSER

    subgraph DEPLOY["Способы запуска — deploy/"]
        D1["systemd<br/>seismos.service"]
        D2["Docker + compose"]
        D3["nginx — reverse proxy"]
    end
```

![Блок-схема 08-deployment](img/diagram/08-deployment.png)


## 8. Аппаратный сегмент и цепочка датчиков

Датчики подключаются последовательно (цепочкой); `ChainReader` опрашивает их
по очереди и выдаёт блоки `ChainSample` движку.

```mermaid
flowchart LR
    subgraph CH1["Цепочка 1"]
        G1["GS-20DX #1"] --> G2["GS-20DX #2"] --> G3["GS-20DX #3"] --> GN["… GS-20DX #N"]
    end
    CH1 --> CR["ChainReader<br/>последовательный опрос"]
    CR --> SAMP["ChainSample[]<br/>блок на каждый датчик"]
    SAMP --> ENG["ProcessingEngine<br/>ingest → handle_event"]
    ENG --> ST["EventStore"]
    ENG --> BS["EventBus"]
```

![Блок-схема 09-hardware-chain](img/diagram/09-hardware-chain.png)


| Узел | Назначение |
|---|---|
| Геофон GS-20DX | Преобразование колебаний грунта в напряжение |
| АЦП ADS1256 | 24-битная оцифровка, интерфейс SPI |
| Узел сбора | Питание PoE, упаковка отсчётов в UDP-пакеты |
| `ChainReader` | Последовательный опрос цепочки датчиков |
| `ProcessingEngine` | Приём `ChainSample`, обнаружение, тревоги |

---

## Как пересобрать изображения

Исходные тексты схем — в этом файле. Для экспорта в SVG/PNG:

```bash
# Один раз: установить mermaid-cli
npx -y @mermaid-js/mermaid-cli --version

# Экспорт отдельной схемы (пример)
npx -y @mermaid-js/mermaid-cli -i docs/DIAGRAM.md -o docs/img/diagram.png
```

Схемы также отображаются автоматически при просмотре этого файла на GitHub.
