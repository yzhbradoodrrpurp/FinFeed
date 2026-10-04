"""Local deployment preparation/import. Never puts private records in Git."""
import argparse
import json
import os
from pathlib import Path
import secrets

from state import ROOT, read_state, validate


def private_write(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("w") as file:
        os.chmod(path, 0o600)
        file.write(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "import"])
    parser.add_argument("--config", type=Path, help="本机私密 JSON 配置（含 DATABASE_URL）")
    args = parser.parse_args()
    if args.action == "prepare":
        state = read_state()
        if state is None:
            raise SystemExit("没有本机记录，请先保存自选股与持仓")
        target = ROOT / ".local" / "cloud-migration"
        private_write(target / "records.json", json.dumps(state, ensure_ascii=False, allow_nan=False, indent=2))
        token_path = target / "bootstrap-code.txt"
        if not token_path.exists():
            private_write(token_path, secrets.token_urlsafe(32))
        print(f"已准备私密迁移文件：{len(state['watchlist'])} 个标的、{len(state['positions'])} 项持仓")
        print("目录：dashboard/.local/cloud-migration/（已被 Git 忽略，文件权限 600）")
        return
    if args.config:
        config = json.loads(args.config.read_text())
        url = config.get("DATABASE_URL")
    else:
        url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("请在本机私密配置中填写 DATABASE_URL，不要发送到聊天")
    from cloud_store import Store
    path = ROOT / ".local" / "cloud-migration" / "records.json"
    state = validate(json.loads(path.read_text()))
    try:
        Store(url).update_state(state, require_empty=True)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        # No DSN or underlying exception details in terminal/logs.
        raise SystemExit(f"迁移失败：{type(error).__name__}，请检查连接配置") from None
    print("自选股、排序与持仓已导入私有云端数据库")


if __name__ == "__main__":
    main()
