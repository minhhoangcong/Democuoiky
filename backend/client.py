import asyncio
import base64
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Iterable

import websockets
from logger import setup_logger

# Thiết lập logger cho client
logger = setup_logger("client")

DEFAULT_WS_URL = os.environ.get("WS_URL", "ws://localhost:8765/ws")
CHUNK_SIZE = 64 * 1024  # 64KB


@dataclass
class UploadState:
    file_id: str
    file_path: Path
    file_size: int
    offset: int = 0
    is_paused: bool = False
    is_stopped: bool = False


class AsyncUploader:
    def __init__(self, ws_url: str = DEFAULT_WS_URL, chunk_size: int = CHUNK_SIZE) -> None:
        self.ws_url = ws_url
        self.chunk_size = chunk_size
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.state: Optional[UploadState] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # start in running state
        logger.debug("AsyncUploader initialized with ws_url=%s, chunk_size=%d", ws_url, chunk_size)

    async def __aenter__(self):
        logger.debug("Connecting to WebSocket: %s", self.ws_url)
        self.websocket = await websockets.connect(self.ws_url, max_size=8 * 1024 * 1024)
        self._recv_task = asyncio.create_task(self._receiver())
        logger.info("Connected to WebSocket server")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        import contextlib
        if self._recv_task:
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recv_task
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()
        logger.debug("WebSocket connection closed")

    async def _receiver(self):
        try:
            assert self.websocket is not None
            async for message in self.websocket:
                await self._handle_message(message)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Receiver error: %s", exc, exc_info=True)

    async def _handle_message(self, message: str):
        import json
        try:
            data = json.loads(message)
        except Exception:
            logger.warning("Received non-JSON message: %s", message)
            return

        event = data.get("event")
        if not self.state:
            logger.debug("Received message without state: %s", data)
            return

        if event == "start-ack":
            self.state.offset = int(data.get("offset", 0))
            logger.info("Start acknowledged: resume at offset=%d for %s", 
                       self.state.offset, self.state.file_path.name)
        elif event == "progress":
            off = int(data.get("offset", 0))
            self.state.offset = off
            percent = data.get("percent")
            logger.debug("Progress: offset=%d (%s%%) for %s", 
                        off, percent, self.state.file_path.name)
        elif event == "pause-ack":
            logger.info("Pause acknowledged: offset=%s for %s", 
                       data.get('offset'), self.state.file_path.name)
        elif event == "resume-ack":
            off = int(data.get("offset", 0))
            self.state.offset = off
            logger.info("Resume acknowledged: offset=%d for %s", 
                       off, self.state.file_path.name)
        elif event == "stop-ack":
            logger.info("Stop acknowledged for %s", self.state.file_path.name)
        elif event == "complete-ack":
            logger.info("Upload completed: path=%s for %s", 
                       data.get('filePath'), self.state.file_path.name)
        elif event == "offset-mismatch":
            expected = int(data.get("expected", 0))
            logger.warning("Offset mismatch, expected=%d for %s", 
                          expected, self.state.file_path.name)
            self.state.offset = expected
        elif event == "error":
            logger.error("Server error: %s for %s", 
                        data.get('error'), self.state.file_path.name)
        else:
            logger.debug("Unknown event: %s", data)

    async def start(self, file_path: str, file_id: Optional[str] = None):
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            error_msg = f"File not found: {file_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        if file_id is None:
            file_id = uuid.uuid4().hex
            logger.debug("Generated file_id: %s", file_id)

        self.state = UploadState(
            file_id=file_id,
            file_path=path,
            file_size=path.stat().st_size,
        )

        logger.info("Starting upload: file=%s, size=%d bytes, id=%s", 
                   path.name, self.state.file_size, file_id)

        await self._send_json({
            "action": "start",
            "fileId": self.state.file_id,
            "fileName": path.name,
            "fileSize": self.state.file_size,
        })

    async def upload(self):
        if not self.state:
            error_msg = "Call start() first"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        assert self.websocket is not None

        logger.info("Starting upload process for %s", self.state.file_path.name)
        
        with open(self.state.file_path, "rb") as f:
            # Seek to resume offset if any
            if self.state.offset:
                logger.debug("Seeking to offset: %d", self.state.offset)
                f.seek(self.state.offset)

            while not self.state.is_stopped and self.state.offset < self.state.file_size:
                # Respect pause
                await self._pause_event.wait()
                if self.state.is_stopped:
                    break

                chunk = f.read(self.chunk_size)
                if not chunk:
                    break

                # base64 encode
                data_b64 = base64.b64encode(chunk).decode("ascii")
                offset_before = self.state.offset

                await self._send_json({
                    "action": "chunk",
                    "fileId": self.state.file_id,
                    "offset": offset_before,
                    "data": data_b64,
                })

                # Optimistically advance; server will correct via offset-mismatch
                self.state.offset += len(chunk)

                # Gentle yield to event loop
                await asyncio.sleep(0)

        if not self.state.is_stopped and self.state.offset >= self.state.file_size:
            logger.info("Upload completed, finalizing file: %s", self.state.file_path.name)
            await self.complete()

    async def pause(self):
        if not self.state or self.state.is_paused:
            return
        self.state.is_paused = True
        self._pause_event.clear()
        logger.info("Pausing upload for %s", self.state.file_path.name)
        await self._send_json({
            "action": "pause",
            "fileId": self.state.file_id,
        })

    async def resume(self):
        if not self.state or not self.state.is_paused:
            return
        self.state.is_paused = False
        self._pause_event.set()
        logger.info("Resuming upload for %s", self.state.file_path.name)
        await self._send_json({
            "action": "resume",
            "fileId": self.state.file_id,
        })

    async def stop(self, delete: bool = True):
        if not self.state:
            return
        self.state.is_stopped = True
        self._pause_event.set()
        logger.info("Stopping upload for %s (delete=%s)", self.state.file_path.name, delete)
        await self._send_json({
            "action": "stop",
            "fileId": self.state.file_id,
            "delete": bool(delete),
        })

    async def complete(self):
        if not self.state:
            return
        logger.info("Completing upload for %s", self.state.file_path.name)
        await self._send_json({
            "action": "complete",
            "fileId": self.state.file_id,
        })

    async def _send_json(self, obj):
        import json
        assert self.websocket is not None
        await self.websocket.send(json.dumps(obj))


async def upload_many(ws_url: str, files: Iterable[str], concurrency: int = 2, chunk: int = CHUNK_SIZE):
    """
    Upload nhiều files với concurrency control và progress tracking
    
    Args:
        ws_url: WebSocket URL
        files: Danh sách file paths
        concurrency: Số lượng upload đồng thời
        chunk: Kích thước chunk
    """
    file_list = list(files)
    total_files = len(file_list)
    completed_files = 0
    failed_files = []
    
    logger.info("Starting batch upload: %d files, concurrency=%d", total_files, concurrency)
    
    # Tạo semaphore để giới hạn số upload đồng thời
    semaphore = asyncio.Semaphore(concurrency)
    
    async def worker(file_path: str):
        """Worker function để upload một file"""
        async with semaphore:
            try:
                logger.debug("Processing file: %s", file_path)
                async with AsyncUploader(ws_url, chunk) as up:
                    await up.start(file_path)
                    await up.upload()
                logger.info("File uploaded successfully: %s", file_path)
                return True
            except Exception as e:
                logger.error("Failed to upload file %s: %s", file_path, e)
                return False

    # Tạo tasks cho tất cả files
    tasks = []
    for file_path in file_list:
        task = asyncio.create_task(worker(file_path))
        tasks.append((file_path, task))
    
    # Chờ tất cả tasks hoàn thành
    for file_path, task in tasks:
        try:
            success = await task
            if success:
                completed_files += 1
            else:
                failed_files.append(file_path)
            
            # Log progress
            progress = (completed_files + len(failed_files)) / total_files * 100
            logger.info("Progress: %d/%d files completed (%.1f%%)", 
                       completed_files + len(failed_files), total_files, progress)
            
        except Exception as e:
            logger.error("Task failed for %s: %s", file_path, e)
            failed_files.append(file_path)
    
    # Summary
    logger.info("Batch upload completed: %d/%d files successful", completed_files, total_files)
    if failed_files:
        logger.warning("Failed files (%d):", len(failed_files))
        for failed_file in failed_files:
            logger.warning("  - %s", failed_file)
    
    return {
        'total': total_files,
        'completed': completed_files,
        'failed': failed_files,
        'success_rate': completed_files / total_files if total_files > 0 else 0
    }


async def interactive_upload(ws_url: str, file_path: str, file_id: Optional[str] = None):
    logger.info("Starting interactive upload for %s", file_path)
    async with AsyncUploader(ws_url) as up:
        await up.start(file_path, file_id)
        uploader_task = asyncio.create_task(up.upload())

        print("Commands: p=pause, r=resume, s=stop, q=quit")

        async def read_input():
            loop = asyncio.get_running_loop()
            while True:
                cmd = await loop.run_in_executor(None, sys.stdin.readline)
                if not cmd:
                    continue
                cmd = cmd.strip().lower()
                if cmd == 'p':
                    logger.debug("User command: pause")
                    await up.pause()
                elif cmd == 'r':
                    logger.debug("User command: resume")
                    await up.resume()
                elif cmd == 's':
                    logger.debug("User command: stop")
                    await up.stop(delete=True)
                elif cmd == 'q':
                    logger.debug("User command: quit")
                    await up.stop(delete=False)
                    break
                else:
                    print("Unknown command. Use p/r/s/q")

        reader_task = asyncio.create_task(read_input())
        done, pending = await asyncio.wait(
            {uploader_task, reader_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Async WebSocket file uploader client")
    parser.add_argument("file", nargs='*', help="Path(s) to file(s) to upload")
    parser.add_argument("--ws", dest="ws_url", default=DEFAULT_WS_URL, help="WebSocket URL, default ws://localhost:8765/ws")
    parser.add_argument("--dir", dest="directory_paths", nargs="+", default=None, help="Directory path(s) to upload all files from")
    parser.add_argument("--recursive", action="store_true", help="Recursively scan subdirectories when using --dir")
    parser.add_argument("--id", dest="file_id", default=None, help="Optional file id (only for single-file mode)")
    parser.add_argument("--chunk", dest="chunk", type=int, default=CHUNK_SIZE, help="Chunk size in bytes (default 65536)")
    parser.add_argument("--concurrency", dest="concurrency", type=int, default=2, help="Number of concurrent uploads for multi-file mode")
    parser.add_argument("--interactive", dest="interactive", action="store_true", help="Interactive mode (only for single-file mode)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Log level")
    parser.add_argument("--log-file", default=None, help="File log (optional)")
    
    args = parser.parse_args()

    # Thiết lập log level từ command line
    if args.log_file:
        logger = setup_logger("client", args.log_level, args.log_file)
    else:
        logger = setup_logger("client", args.log_level)

    # Thu thập tất cả files cần upload
    all_files = []
    
    # Thêm files từ positional arguments
    if args.file:
        all_files.extend(args.file)
        logger.info("Added %d files from positional arguments", len(args.file))
    
    # Thêm files từ --dir argument
    if args.directory_paths:
        from app import collect_files_from_paths  # Import function từ app.py
        dir_files = collect_files_from_paths(args.directory_paths, args.recursive)
        all_files.extend(dir_files)
        logger.info("Added %d files from --dir argument", len(dir_files))
    
    # Loại bỏ duplicate và sắp xếp
    unique_files = list(set(all_files))
    unique_files.sort()
    
    if not unique_files:
        error_msg = "Please provide at least one file path or directory"
        logger.error(error_msg)
        parser.error(error_msg)

    # Kiểm tra interactive mode với multiple files
    if args.interactive and len(unique_files) > 1:
        logger.warning("Interactive mode only supports single file, using first file: %s", unique_files[0])
        unique_files = [unique_files[0]]

    try:
        if len(unique_files) == 1:
            if args.interactive:
                asyncio.run(interactive_upload(args.ws_url, unique_files[0], args.file_id))
            else:
                asyncio.run(upload_many(args.ws_url, unique_files, concurrency=1, chunk=args.chunk))
        else:
            asyncio.run(upload_many(args.ws_url, unique_files, concurrency=args.concurrency, chunk=args.chunk))
    except KeyboardInterrupt:
        logger.info("Upload interrupted by user")
    except Exception as e:
        logger.error("Upload error: %s", e, exc_info=True)
        raise


if __name__ == "__main__":
    main()
