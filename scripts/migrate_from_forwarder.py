#!/usr/bin/env python3
"""Перенос данных NetSchool из старого проекта max_tg_forw_sch.

    python scripts/migrate_from_forwarder.py /opt/max_tg_forw_sch/forwarder_data

Копирует (не удаляя исходники):
  netschool_users/           — пользователи, токены PWA, иконки, галерея
  netschool_sessions/        — сохранённые сессии «Сетевого города»
  netschool_feedback/        — отзывы из мини-приложения
  cache_*.json               — кэш дневника (в data/netschool_cache/)
  sent_grades.json           — отправленные оценки общего чекера
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from netschoolbot import config  # noqa: E402


def copy_tree(src: Path, dst: Path) -> int:
    if not src.exists():
        print(f"⏭  нет {src}")
        return 0
    count = 0
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        target = dst / item.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        count += 1
    print(f"✅ {src} → {dst}: {count} файл(ов)")
    return count


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    source = Path(sys.argv[1]).expanduser().resolve()
    if not source.exists():
        sys.exit(f"❌ Каталог не найден: {source}")

    config.ensure_data_dirs()
    total = 0

    total += copy_tree(source / "netschool_users", config.NETSCHOOL_USERS_DIR)
    total += copy_tree(source / "netschool_sessions", config.NETSCHOOL_SESSIONS_DIR)
    total += copy_tree(source / "netschool_feedback", config.NETSCHOOL_FEEDBACK_DIR)

    # Кэш дневника раньше лежал вперемешку с настройками пользователей
    moved_cache = 0
    for cache_file in config.NETSCHOOL_USERS_DIR.glob("cache_*.json"):
        shutil.move(str(cache_file), config.NETSCHOOL_CACHE_DIR / cache_file.name)
        moved_cache += 1
    if moved_cache:
        print(f"✅ кэш дневника перенесён в {config.NETSCHOOL_CACHE_DIR}: {moved_cache} файл(ов)")

    sent_grades = source / "sent_grades.json"
    if sent_grades.exists():
        shutil.copy2(sent_grades, config.SENT_GRADES_FILE)
        print(f"✅ {sent_grades} → {config.SENT_GRADES_FILE}")
        total += 1

    print(f"\n🎉 Готово. Перенесено файлов: {total + moved_cache}")
    print(f"📁 Данные проекта: {config.DATA_DIR}")


if __name__ == "__main__":
    main()
