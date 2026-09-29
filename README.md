# J.A.R.V.I.S. — голосовий асистент для Windows 10/11

Офлайн-асистент у стилі Джарвіса з фільмів про Тоні Старка: українська мова (плюс російські та англійські назви програм), розпізнавання через Vosk, персональне навчання вимови, бінди «фраза → дія», самонавчання й мінімум звернень до DeepSeek. Інтерфейс зроблено на **pywebview** (HTML/CSS/JS, повністю офлайн): «скляні» панелі, анімований arc reactor, HUD-оверлей поверх усіх вікон.

## Можливості

- **Розпізнавання мови**: Vosk + sounddevice, wake word «Джарвіс» (і навчені варіанти вимови), push-to-talk `Ctrl+Alt+J`. Спершу grammar-режим (фрази з бази + ключові слова), якщо не вийшло — вільний режим, далі вторинні моделі (ru, en).
- **Навчання вимови** (вкладка «Слова/вимова»): 3–5 зразків слова → аліаси, які чує Vosk (`rapidfuzz` + транслітерація) і акустичні шаблони MFCC з DTW-порогом, обчисленим з розкиду між зразками. Далі режим тесту з оцінками. Кожне вдале використання додає аліас, а «не те» знижує його вагу.
- **Конвеєр команд**: точний бінд → нечіткий бінд → правила → кеш DeepSeek → DeepSeek (строгий JSON, pydantic, retry). Після успіху фраза, розпізнана через DeepSeek, зберігається як бінд.
- **Навички**: програми (індекс меню «Пуск», Program Files, реєстру, Steam, Epic, UWP; закриття через psutil), SoundCloud (yt-dlp або API, VLC чи браузер, рекомендації з урахуванням смаку), таймери, нагадування (toast-сповіщення, переживають перезапуск), скріншоти (увесь екран / активне вікно / область), гучність, блокування, вимкнення з підтвердженням, час і дата.
- **Голос**: edge-tts (`uk-UA-OstapNeural`) з кешем, офлайн-фолбек pyttsx3.

## Структура

```
Jarvis/
  README.md  requirements.txt  build.spec  .env.example  pyproject.toml
  jarvis/
    main.py  __main__.py  bootstrap.py  config.yaml
    core/      assistant, event_bus, events, intent, context, config, models, scheduler, errors
    speech/    audio_io, recognizer_vosk, wake_word, listener, grammar, tts
    nlu/       intent_parser, fuzzy_matcher, pronunciation_matcher, phrase_learner, pipeline,
               deepseek_client, deepseek_intents, interpreter, time_parser, durations, numbers, lexicon
    skills/    base (протокол Skill + реєстр), apps/, media_soundcloud/, timers, reminders,
               screenshots, system, bindings, actions, conversation
    storage/   db (sqlite3), migrations, repositories/
    training/  pronunciation_trainer, voice_templates (MFCC + DTW)
    services/  мости event bus ↔ сховище для UI
    ui/        app, main_window, hud, region_selector, js_api, event_relay, tray, hotkeys
      web/     index.html, hud.html, region.html, styles.css, *.js
    tests/
```

## Встановлення

1. Python **3.11+** (64-bit).
2. Залежності:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. **WebView2 Runtime**: у Windows 11 вже встановлений; для Windows 10 завантажте «Evergreen Bootstrapper» з сайту Microsoft.
4. **VLC** (64-bit), якщо `music.backend: vlc`. Інакше поставте `browser`.
5. Скопіюйте `.env.example` у `.env` і вкажіть ключ: `DEEPSEEK_API_KEY=sk-...`. Без ключа асистент працює повністю офлайн, лише без останнього кроку конвеєра.

### Моделі Vosk

Завантажте моделі з <https://alphacephei.com/vosk/models> і розпакуйте в теку `models/` у корені проєкту (або поруч із `Jarvis.exe`):

| Мова | Модель | Шлях у `config.yaml` |
|------|--------|----------------------|
| uk | `vosk-model-uk-v3` | `speech.models.uk` |
| ru | `vosk-model-small-ru-0.22` | `speech.models.ru` |
| en | `vosk-model-small-en-us-0.15` | `speech.models.en` |

Grammar-режим потребує моделі з динамічним графом (`graph/HCLr.fst` + `graph/Gr.fst`), наприклад `vosk-model-small-uk-v3-small`. Якщо графа немає, асистент автоматично працює у вільному режимі. Без жодної моделі залишається текстовий режим.

## Запуск

```bat
python -m jarvis
```

Під час першого запуску поруч створюється `config.yaml` (копія `jarvis/config.yaml`), база `data/jarvis.db`, логи `data/logs/`, кеш голосу `data/tts_cache/`. Програми індексуються у фоні.

Приклади команд:

- «Джарвіс, відкрий хром» / «закрий його»
- «Джарвіс, таймер на п'ять хвилин» / «скільки лишилось»
- «Джарвіс, нагадай завтра о 9 подзвонити мамі»
- «Джарвіс, увімкни Imagine Dragons Believer» / «увімкни щось під настрій» / «далі» / «мені це подобається»
- «Джарвіс, зроби скрін області»
- «Джарвіс, запам'ятай: коли я кажу "бойовий режим" — відкрий Discord і Dota» → «так»
- «не те» — якщо асистент помилився (знижує вагу хибного аліасу)

## Тести

```bat
pytest
```

Покрито парсер інтентів, нечіткий матчер і матчер вимови, сховище SQLite, парсер часу, DTW, конвеєр, асистента (підтвердження й виправлення), event bus і міст UI.

## Збірка в один .exe

```bat
pip install pyinstaller
pyinstaller build.spec
```

Результат: `dist\Jarvis.exe`. Поруч із ним покладіть теку `models\` і `.env`. `config.yaml` і `data\` створюються автоматично під час першого запуску.

## Архітектура коротко

- UI спілкується з ядром **лише через event bus**: `ui/js_api.py` перетворює виклики з JS на події, а `ui/event_relay.py` пакетами пересилає події з bus у вікно.
- Потоки не блокують одне одного: event bus, мікрофон, слухач, асистент, TTS, тренер, планувальник, індексатор і GUI працюють окремо.
- Нова навичка — це клас із `name`, `intents` і `handle(intent, context)`, зареєстрований у `bootstrap.py` через `registry.register_all([...])`. Ядро правити не потрібно.
