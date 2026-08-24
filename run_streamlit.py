"""RepoPath Streamlit 根目录启动脚本。"""

from pathlib import Path

from streamlit.web import bootstrap


def start_app() -> None:
    """启动 Streamlit 应用。"""
    app_path = Path(__file__).parent / "app.py"
    if not app_path.exists():
        raise FileNotFoundError(f"找不到应用入口: {app_path}")
    bootstrap.run(
        str(app_path), is_hello=False, args=[], flag_options={}
    )


if __name__ == "__main__":
    start_app()
