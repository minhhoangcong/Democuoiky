import argparse
import asyncio
import os
from pathlib import Path
import contextlib

import websockets

# Import handler từ server và AsyncUploader từ client
import server as server_mod
from client import AsyncUploader
from logger import setup_logger

# Thiết lập logger cho app
logger = setup_logger("app")

async def run_server(host: str, port: int):
    async with websockets.serve(
        server_mod.handler,
        host,
        port,
        origins=None,
        max_size=8 * 1024 * 1024,
    ):
        logger.info("Server listening on ws://%s:%d/ws", host, port)
        await asyncio.Future()  # run forever


async def run_client(ws_url: str, file_paths: list, file_id: str | None, chunk: int, interactive: bool):
    from client import interactive_upload, upload_many

    if interactive:
        if len(file_paths) > 1:
            logger.warning("Interactive mode only supports single file, using first file: %s", file_paths[0])
        logger.info("Starting interactive upload for file: %s", file_paths[0])
        await interactive_upload(ws_url, file_paths[0], file_id)
        return

    # Non-interactive upload - hỗ trợ nhiều file
    if len(file_paths) == 1:
        logger.info("Starting single file upload: %s", file_paths[0])
        async with AsyncUploader(ws_url, chunk) as up:
            await up.start(file_paths[0], file_id)
            await up.upload()
    else:
        logger.info("Starting multi-file upload: %d files", len(file_paths))
        await upload_many(ws_url, file_paths, concurrency=2, chunk=chunk)


async def run_both(host: str, port: int, ws_url: str, file_paths: list, file_id: str | None, chunk: int, interactive: bool):
    logger.info("Starting both server and client mode")
    server_task = asyncio.create_task(run_server(host, port))
    try:
        # Chờ server khởi động
        logger.debug("Waiting for server to start...")
        await asyncio.sleep(0.3)
        await run_client(ws_url, file_paths, file_id, chunk, interactive)
    finally:
        logger.info("Stopping server...")
        server_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server_task


def collect_files_from_paths(paths: list, recursive: bool = False) -> list:
    """
    Thu thập tất cả files từ danh sách đường dẫn (có thể là file hoặc folder)
    
    Args:
        paths: Danh sách đường dẫn
        recursive: Có duyệt đệ quy vào subfolder không
    
    Returns:
        Danh sách đường dẫn file
    """
    all_files = []
    
    for path_str in paths:
        path = Path(path_str)
        if not path.exists():
            logger.warning("Path does not exist: %s", path_str)
            continue
            
        if path.is_file():
            all_files.append(str(path))
        elif path.is_dir():
            logger.info("Scanning directory: %s", path)
            if recursive:
                # Duyệt đệ quy tất cả subfolder
                for file_path in path.rglob('*'):
                    if file_path.is_file():
                        all_files.append(str(file_path))
            else:
                # Chỉ duyệt file trong folder hiện tại
                for file_path in path.iterdir():
                    if file_path.is_file():
                        all_files.append(str(file_path))
    
    # Loại bỏ duplicate và sắp xếp
    unique_files = list(set(all_files))
    unique_files.sort()
    
    logger.info("Collected %d files for upload", len(unique_files))
    if len(unique_files) <= 10:
        for file_path in unique_files:
            logger.debug("  - %s", file_path)
    else:
        for file_path in unique_files[:5]:
            logger.debug("  - %s", file_path)
        logger.debug("  ... and %d more files", len(unique_files) - 5)
    
    return unique_files


def main():
    parser = argparse.ArgumentParser(description="Run async WebSocket server and/or client")
    parser.add_argument("--mode", choices=["server", "client", "both"], default="both", help="Chạy server, client, hoặc cả hai")

    # Server config
    parser.add_argument("--host", default=os.environ.get("WS_HOST", "localhost"), help="Host cho server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("WS_PORT", "8765")), help="Port cho server")

    # Client config
    parser.add_argument("--ws", dest="ws_url", default=os.environ.get("WS_URL", "ws://localhost:8765/ws"), help="WebSocket URL cho client")
    parser.add_argument("--file", dest="file_paths", nargs="+", default=None, help="Đường dẫn file(s) để upload (bắt buộc nếu mode=client/both)")
    parser.add_argument("--dir", dest="directory_paths", nargs="+", default=None, help="Đường dẫn folder(s) để upload (bắt buộc nếu mode=client/both)")
    parser.add_argument("--recursive", action="store_true", help="Duyệt đệ quy vào subfolder khi upload folder")
    parser.add_argument("--id", dest="file_id", default=None, help="Tùy chọn: file id (chỉ áp dụng cho single file)")
    parser.add_argument("--chunk", dest="chunk", type=int, default=64 * 1024, help="Kích thước chunk (bytes)")
    parser.add_argument("--interactive", dest="interactive", action="store_true", help="Client interactive (p/r/s/q) - chỉ hỗ trợ single file")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    parser.add_argument("--log-file", default=None, help="File log (optional)")

    args = parser.parse_args()

    # Thiết lập log level từ command line
    if args.log_file:
        logger = setup_logger("app", args.log_level, args.log_file)
    else:
        logger = setup_logger("app", args.log_level)

    logger.info("Starting application with mode: %s", args.mode)
    logger.debug("Configuration: host=%s, port=%d, ws_url=%s, chunk_size=%d", 
                args.host, args.port, args.ws_url, args.chunk)

    # Thu thập tất cả files cần upload
    file_paths = []
    
    if args.file_paths:
        file_paths.extend(args.file_paths)
        logger.info("Added %d files from --file argument", len(args.file_paths))
    
    if args.directory_paths:
        dir_files = collect_files_from_paths(args.directory_paths, args.recursive)
        file_paths.extend(dir_files)
        logger.info("Added %d files from --dir argument", len(dir_files))
    
    # Kiểm tra có files để upload không
    if args.mode in ("client", "both") and not file_paths:
        error_msg = "--file hoặc --dir là bắt buộc khi mode=client hoặc mode=both"
        logger.error(error_msg)
        parser.error(error_msg)

    # Kiểm tra interactive mode với multiple files
    if args.interactive and len(file_paths) > 1:
        logger.warning("Interactive mode only supports single file, using first file: %s", file_paths[0])
        file_paths = [file_paths[0]]

    try:
        if args.mode == "server":
            logger.info("Running server only mode")
            asyncio.run(run_server(args.host, args.port))
        elif args.mode == "client":
            logger.info("Running client only mode")
            asyncio.run(run_client(args.ws_url, file_paths, args.file_id, args.chunk, args.interactive))
        else:  # both
            logger.info("Running both server and client mode")
            asyncio.run(run_both(args.host, args.port, args.ws_url, file_paths, args.file_id, args.chunk, args.interactive))
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except Exception as e:
        logger.error("Application error: %s", e, exc_info=True)
        raise


if __name__ == "__main__":
    main()
