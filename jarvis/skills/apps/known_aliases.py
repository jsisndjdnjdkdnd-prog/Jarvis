from __future__ import annotations

from dataclasses import dataclass

from jarvis.core.models import ProgramKind

KNOWN_ALIASES: dict[str, tuple[str, ...]] = {
    "chrome": ("хром", "гугл хром", "хроме", "браузер", "гугл", "google chrome", "хром браузер"),
    "firefox": ("фаєрфокс", "файрфокс", "мозила", "мозилла", "фаерфокс"),
    "opera": ("опера", "опера джі екс", "opera gx"),
    "microsoft edge": ("едж", "ейдж", "edge"),
    "brave": ("брейв",),
    "discord": ("діскорд", "дискорд", "дс"),
    "telegram": ("телеграм", "телега", "телеграмм", "тг"),
    "viber": ("вайбер",),
    "slack": ("слак",),
    "zoom": ("зум",),
    "skype": ("скайп",),
    "whatsapp": ("вотсап", "ватсап"),
    "spotify": ("спотифай", "спотіфай"),
    "steam": ("стім", "стим", "стеам"),
    "epic games launcher": ("епік", "епік геймс", "эпик"),
    "dota 2": ("дота", "дотка", "доту", "дотку", "дота 2", "дота два", "доти"),
    "counter strike 2": ("кс", "контра", "каес", "кс 2", "кс два", "контру", "counter strike"),
    "counter strike global offensive": ("кс го", "ксго"),
    "grand theft auto v": ("гта", "гта 5", "гта п'ять", "gta"),
    "minecraft": ("майнкрафт", "майн"),
    "fortnite": ("фортнайт",),
    "valorant": ("валорант",),
    "league of legends": ("ліга легенд", "лол"),
    "world of tanks": ("танки", "ворлд оф танкс"),
    "rust": ("раст",),
    "pubg": ("пабг", "пубг"),
    "apex legends": ("апекс",),
    "visual studio code": ("вс код", "віжуал студіо код", "vs code", "vscode"),
    "visual studio": ("віжуал студіо", "вижуал студио"),
    "pycharm": ("пайчарм", "пічарм"),
    "intellij idea": ("інтелідж", "ідея"),
    "notepad++": ("нотпад плюс плюс", "нотпад"),
    "obs studio": ("обс", "обс студіо"),
    "malwarebytes": ("малварбайтс", "малвербайтс", "малвар байтс", "мал вер байтс"),
    "word": ("ворд", "microsoft word"),
    "excel": ("ексель", "эксель", "microsoft excel"),
    "powerpoint": ("пауерпоінт", "поверпоінт", "презентації"),
    "outlook": ("аутлук", "пошта"),
    "photoshop": ("фотошоп",),
    "premiere pro": ("прем'єр", "премьер"),
    "after effects": ("афтер ефектс",),
    "blender": ("блендер",),
    "vlc media player": ("влц", "влс", "плеєр vlc"),
    "qbittorrent": ("торрент", "кьюбіт торрент"),
    "utorrent": ("юторрент", "торент"),
    "7 zip": ("севен зіп", "архіватор"),
    "winrar": ("вінрар",),
    "anydesk": ("енідеск", "анідеск"),
    "teamviewer": ("тімв'ювер", "тім вьювер"),
    "battle net": ("батлнет", "батл нет", "близзард"),
    "ubisoft connect": ("юбісофт",),
    "ea app": ("еа", "ориджин", "origin"),
    "gog galaxy": ("гог",),
    "nvidia": ("нвідіа", "джифорс"),
}

VENDOR_PREFIXES: tuple[str, ...] = (
    "microsoft ", "google ", "mozilla ", "adobe ", "valve ", "the ", "jetbrains ", "epic games ",
    "nvidia ", "oracle ", "apple ", "mozilla ",
)


@dataclass(frozen=True)
class SystemProgram:
    name: str
    launch_target: str
    process_names: tuple[str, ...]
    aliases: tuple[str, ...]
    kind: ProgramKind = ProgramKind.SYSTEM


SYSTEM_PROGRAMS: tuple[SystemProgram, ...] = (
    SystemProgram("Notepad", "notepad.exe", ("notepad.exe",), ("блокнот", "нотатки", "notepad")),
    SystemProgram(
        "Calculator", "calc.exe", ("calculatorapp.exe", "calculator.exe", "calc.exe"), ("калькулятор", "калькулятора")
    ),
    SystemProgram("File Explorer", "explorer.exe", (), ("провідник", "проводник", "мій комп'ютер", "файли")),
    SystemProgram("Task Manager", "taskmgr.exe", ("taskmgr.exe",), ("диспетчер задач", "диспетчер завдань")),
    SystemProgram("Command Prompt", "cmd.exe", ("cmd.exe",), ("командний рядок", "консоль", "cmd")),
    SystemProgram("PowerShell", "powershell.exe", ("powershell.exe",), ("павершел", "пауершел", "powershell")),
    SystemProgram("Paint", "mspaint.exe", ("mspaint.exe",), ("пейнт", "паінт", "малювалка")),
    SystemProgram("Control Panel", "control.exe", (), ("панель керування", "панель управления")),
    SystemProgram("Settings", "ms-settings:", ("systemsettings.exe",), ("налаштування", "параметри", "настройки")),
    SystemProgram("Snipping Tool", "snippingtool.exe", ("snippingtool.exe",), ("ножиці", "ножницы")),
    SystemProgram("Registry Editor", "regedit.exe", ("regedit.exe",), ("редактор реєстру", "регедіт")),
)
