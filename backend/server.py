import asyncio
import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import websockets
from websockets.server import WebSocketServerProtocol
from logger import setup_logger

# Thiết lập logger cho server
logger = setup_logger("server")

UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class UploadSession:
    file_id: str
    file_name: str
    file_size: int
    status: str = "active"  # active | paused | completed | stopped | error
    bytes_received: int = 0
    file_path: Path = field(default_factory=Path)
    file_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def part_path(self) -> Path:
        return self.file_path.with_suffix(self.file_path.suffix + ".part")


class UploadManager:
    def __init__(self) -> None:
        self.file_id_to_session: Dict[str, UploadSession] = {}
        self.connection_to_sessions: Dict[WebSocketServerProtocol, Dict[str, UploadSession]] = {}
        logger.info("UploadManager initialized")

    def register_connection(self, ws: WebSocketServerProtocol) -> None:
        # Track sessions initiated by this connection
        if ws not in self.connection_to_sessions:
            self.connection_to_sessions[ws] = {}
        logger.debug("Connection registered: %s", ws.remote_address)

    def unregister_connection(self, ws: WebSocketServerProtocol) -> None:
        # On disconnect, mark active sessions as paused to allow resume later,
        # but keep them in global mapping for cross-connection resumption.
        sessions = self.connection_to_sessions.pop(ws, {})
        for session in sessions.values():
            if session.status == "active":
                session.status = "paused"
                logger.info("Session paused due to disconnect: %s (%s)", 
                           session.file_id, session.file_name)
        logger.debug("Connection unregistered: %s", ws.remote_address)

    def get_or_create_session(self, file_id: str, file_name: str, file_size: int) -> UploadSession:
        # Normalize filename and target path
        safe_name = os.path.basename(file_name)
        target_path = UPLOADS_DIR / safe_name

        # Reuse session if exists
        existing = self.file_id_to_session.get(file_id)
        if existing:
            # Update metadata if needed
            existing.file_name = safe_name
            existing.file_size = file_size
            existing.file_path = target_path
            # Refresh bytes_received from disk
            if existing.part_path().exists():
                existing.bytes_received = existing.part_path().stat().st_size
                logger.debug("Resuming existing session: %s, offset=%d", file_id, existing.bytes_received)
            return existing

        # New session
        session = UploadSession(
            file_id=file_id,
            file_name=safe_name,
            file_size=file_size,
            status="active",
            bytes_received=0,
            file_path=target_path,
        )
        # If part file exists, load current size for resume
        if session.part_path().exists():
            session.bytes_received = session.part_path().stat().st_size
            logger.info("Found existing partial file: %s, size=%d bytes", 
                       session.part_path(), session.bytes_received)
        
        self.file_id_to_session[file_id] = session
        logger.info("Created new upload session: %s (%s), size=%d bytes", 
                   file_id, safe_name, file_size)
        return session

    def remove_session(self, file_id: str) -> None:
        if file_id in self.file_id_to_session:
            session = self.file_id_to_session[file_id]
            logger.debug("Removing session: %s (%s)", file_id, session.file_name)
            del self.file_id_to_session[file_id]

    async def handle_start(self, ws: WebSocketServerProtocol, payload: dict) -> None:
        file_id = payload.get("fileId")
        file_name = payload.get("fileName")
        file_size = int(payload.get("fileSize", 0))
        if not file_id or not file_name or file_size <= 0:
            logger.warning("Invalid start payload: fileId=%s, fileName=%s, fileSize=%s", 
                          file_id, file_name, file_size)
            await self.send_error(ws, file_id, "Invalid start payload")
            return

        session = self.get_or_create_session(file_id, file_name, file_size)
        session.status = "active"

        # Track this session under the current connection
        self.register_connection(ws)
        self.connection_to_sessions[ws][file_id] = session

        logger.info("Upload started: %s (%s), size=%d bytes, offset=%d", 
                   file_id, file_name, file_size, session.bytes_received)

        await self.send(ws, {
            "event": "start-ack",
            "fileId": session.file_id,
            "offset": session.bytes_received,
            "status": session.status,
        })

    async def handle_chunk(self, ws: WebSocketServerProtocol, payload: dict) -> None:
        file_id = payload.get("fileId")
        data_b64 = payload.get("data")
        offset = int(payload.get("offset", -1))
        if not file_id or data_b64 is None or offset < 0:
            logger.warning("Invalid chunk payload: fileId=%s, offset=%s, data_length=%d", 
                          file_id, offset, len(data_b64) if data_b64 else 0)
            await self.send_error(ws, file_id, "Invalid chunk payload")
            return

        session = self.file_id_to_session.get(file_id)
        if not session:
            logger.warning("Chunk received for unknown session: %s", file_id)
            await self.send_error(ws, file_id, "Session not found. Send start first.")
            return

        if session.status == "paused":
            logger.debug("Chunk ignored - session paused: %s", file_id)
            await self.send(ws, {"event": "paused", "fileId": file_id, "offset": session.bytes_received})
            return
        if session.status in ("stopped", "completed", "error"):
            logger.warning("Chunk rejected - invalid status: %s (%s)", file_id, session.status)
            await self.send_error(ws, file_id, f"Cannot accept chunk in status: {session.status}")
            return

        # Offset check for simple linear append protocol
        expected = session.bytes_received
        if offset != expected:
            logger.warning("Offset mismatch: expected=%d, received=%d for %s", 
                          expected, offset, file_id)
            await self.send(ws, {
                "event": "offset-mismatch",
                "fileId": file_id,
                "expected": expected,
                "received": offset,
            })
            return

        try:
            data = base64.b64decode(data_b64)
        except Exception as e:
            logger.error("Failed to decode base64 data for %s: %s", file_id, e)
            await self.send_error(ws, file_id, "Invalid base64 data")
            return

        # Write chunk to .part file with lock
        async with session.file_lock:
            part_path = session.part_path()
            part_path.parent.mkdir(parents=True, exist_ok=True)
            # Open in append+binary mode and write
            with open(part_path, "ab") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            session.bytes_received += len(data)

        percent = min(100.0 * session.bytes_received / max(session.file_size, 1), 100.0)
        logger.debug("Chunk processed: %s, offset=%d, chunk_size=%d, progress=%.1f%%", 
                    file_id, session.bytes_received, len(data), percent)
        
        await self.send(ws, {
            "event": "progress",
            "fileId": file_id,
            "offset": session.bytes_received,
            "receivedBytes": len(data),
            "percent": round(percent, 2),
        })

    async def handle_pause(self, ws: WebSocketServerProtocol, payload: dict) -> None:
        file_id = payload.get("fileId")
        session = self.file_id_to_session.get(file_id)
        if not session:
            logger.warning("Pause requested for unknown session: %s", file_id)
            await self.send_error(ws, file_id, "Session not found")
            return
        session.status = "paused"
        logger.info("Upload paused: %s (%s)", file_id, session.file_name)
        await self.send(ws, {"event": "pause-ack", "fileId": file_id, "offset": session.bytes_received})

    async def handle_resume(self, ws: WebSocketServerProtocol, payload: dict) -> None:
        file_id = payload.get("fileId")
        session = self.file_id_to_session.get(file_id)
        if not session:
            logger.warning("Resume requested for unknown session: %s", file_id)
            await self.send_error(ws, file_id, "Session not found")
            return
        session.status = "active"
        logger.info("Upload resumed: %s (%s)", file_id, session.file_name)
        await self.send(ws, {"event": "resume-ack", "fileId": file_id, "offset": session.bytes_received})

    async def handle_stop(self, ws: WebSocketServerProtocol, payload: dict) -> None:
        file_id = payload.get("fileId")
        delete = bool(payload.get("delete", True))
        session = self.file_id_to_session.get(file_id)
        if not session:
            logger.warning("Stop requested for unknown session: %s", file_id)
            await self.send_error(ws, file_id, "Session not found")
            return
        session.status = "stopped"
        logger.info("Upload stopped: %s (%s), delete=%s", file_id, session.file_name, delete)
        
        # Remove partial file if requested
        part_path = session.part_path()
        if delete and part_path.exists():
            try:
                part_path.unlink()
                logger.debug("Partial file deleted: %s", part_path)
            except Exception as exc:
                logger.warning("Failed to delete partial file %s: %s", part_path, exc)
        
        # Remove session from manager
        self.remove_session(file_id)
        # Also detach from this connection's session map
        if ws in self.connection_to_sessions:
            self.connection_to_sessions[ws].pop(file_id, None)
        await self.send(ws, {"event": "stop-ack", "fileId": file_id})

    async def handle_complete(self, ws: WebSocketServerProtocol, payload: dict) -> None:
        file_id = payload.get("fileId")
        session = self.file_id_to_session.get(file_id)
        if not session:
            logger.warning("Complete requested for unknown session: %s", file_id)
            await self.send_error(ws, file_id, "Session not found")
            return

        # Validate size
        if session.bytes_received != session.file_size:
            logger.warning("Size mismatch for %s: expected=%d, actual=%d", 
                          file_id, session.file_size, session.bytes_received)
            await self.send_error(ws, file_id, "Size mismatch. Not completed.")
            return

        # Rename .part to final file
        async with session.file_lock:
            part_path = session.part_path()
            if not part_path.exists():
                logger.error("Partial file missing for %s: %s", file_id, part_path)
                await self.send_error(ws, file_id, "Partial file missing")
                return
            try:
                final_path = session.file_path
                # If final file exists, add numeric suffix
                if final_path.exists():
                    base = final_path.stem
                    ext = final_path.suffix
                    idx = 1
                    while True:
                        candidate = final_path.with_name(f"{base} ({idx}){ext}")
                        if not candidate.exists():
                            final_path = candidate
                            break
                        idx += 1
                
                part_path.rename(final_path)
                session.status = "completed"
                logger.info("Upload completed: %s (%s) -> %s", 
                           file_id, session.file_name, final_path.name)
                
                await self.send(ws, {
                    "event": "complete-ack",
                    "fileId": file_id,
                    "filePath": str(final_path.resolve()),
                })
            except Exception as exc:
                session.status = "error"
                logger.error("Failed to finalize upload %s: %s", file_id, exc)
                await self.send_error(ws, file_id, f"Finalize failed: {exc}")
                return
        
        # Cleanup session
        self.remove_session(file_id)

    async def send(self, ws: WebSocketServerProtocol, message: dict) -> None:
        await ws.send(json.dumps(message))

    async def send_error(self, ws: WebSocketServerProtocol, file_id: Optional[str], error: str) -> None:
        payload = {"event": "error", "error": error}
        if file_id:
            payload["fileId"] = file_id
        logger.error("Sending error to client: %s", error)
        await ws.send(json.dumps(payload))


manager = UploadManager()


async def handler(ws: WebSocketServerProtocol, path: str) -> None:
    # Accept any path but recommend "/ws"
    logger.info("Client connected from %s path=%s", ws.remote_address, path)
    # Register connection for per-connection session tracking
    manager.register_connection(ws)
    try:
        async for message in ws:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON received from %s: %s", ws.remote_address, message[:100])
                await manager.send_error(ws, None, "Invalid JSON")
                continue

            action = data.get("action")
            logger.debug("Received action '%s' from %s", action, ws.remote_address)
            
            if action == "start":
                await manager.handle_start(ws, data)
            elif action == "chunk":
                await manager.handle_chunk(ws, data)
            elif action == "pause":
                await manager.handle_pause(ws, data)
            elif action == "resume":
                await manager.handle_resume(ws, data)
            elif action == "stop":
                await manager.handle_stop(ws, data)
            elif action == "complete":
                await manager.handle_complete(ws, data)
            else:
                logger.warning("Unknown action '%s' from %s", action, ws.remote_address)
                await manager.send_error(ws, data.get("fileId"), f"Unknown action: {action}")
    except websockets.exceptions.ConnectionClosedError:
        logger.info("Client disconnected abruptly: %s", ws.remote_address)
    except Exception as exc:
        logger.exception("Unhandled error from %s: %s", ws.remote_address, exc)
    finally:
        # Pause all active sessions tied to this connection to enable resume later
        manager.unregister_connection(ws)
        logger.info("Connection closed: %s", ws.remote_address)


async def main() -> None:
    host = os.environ.get("WS_HOST", "localhost")
    port = int(os.environ.get("WS_PORT", "8765"))
    async with websockets.serve(handler, host, port, origins=None, max_size=8 * 1024 * 1024):  # 8 MB frame
        logger.info("WebSocket server listening on ws://%s:%d", host, port)
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")