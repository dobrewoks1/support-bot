import subprocess
import sys
from pathlib import Path

from tests.conftest import ROOT


def test_ask_from_command_line(tmp_path: Path, project_env: dict[str, str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "support_bot", "--ask", "Какой у вас режим работы?", "--provider", "fake",
         "--db", str(tmp_path / "dialogs.sqlite3")],
        cwd=ROOT,
        env=project_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "9:00" in result.stdout
    assert "статья: «Какой у вас режим работы?»" in result.stdout


def test_console_mode_reads_stdin(tmp_path: Path, project_env: dict[str, str]) -> None:
    script = "Сколько стоит замена масла?\nПоможете оформить ОСАГО?\n/stats\n/exit\n"
    result = subprocess.run(
        [sys.executable, "-m", "support_bot", "--console", "--provider", "fake",
         "--db", str(tmp_path / "dialogs.sqlite3")],
        cwd=ROOT,
        env=project_env,
        input=script,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "900 рублей" in result.stdout
    assert "→ оператору: обращение #2" in result.stdout
    assert "Всего обращений: 2" in result.stdout
