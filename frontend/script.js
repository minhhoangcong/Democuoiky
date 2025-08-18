// FlexTransfer Hub - Main JavaScript File
class FlexTransferHub {
  constructor() {
    this.transfers = [];
    this.activeTab = "all";
    this.ws = null;
    this.wsUrl = window.FLEX_WS_URL || "ws://localhost:8765/ws";
    this.chunkSize = 256 * 1024;
    this.lastRenderTime = 0;
    this.renderThrottle = 150;
    this.maxConcurrentUploads = 2; // Giới hạn số upload đồng thời
    this.init();
  }

  init() {
    this.setupEventListeners();
    this.setupDragAndDrop();
    this.updateStatusCards();
    this.renderTransfers();
    this.connectWebSocket();
  }

  // Cập nhật tốc độ cho tất cả transfer đang active
  updateTransferSpeeds() {
    const activeTransfers = this.transfers.filter((t) => t.status === "active");
    activeTransfers.forEach((transfer) => {
      if (transfer.type === "upload") {
        // Cập nhật tốc độ cho upload
        const speed = this.computeInstantSpeed(transfer);
        transfer.speed = this.formatSpeed(speed);
      }
    });
  }

  // Throttled render để tránh lag
  throttledRender() {
    const now = Date.now();
    if (now - this.lastRenderTime > this.renderThrottle) {
      // Cập nhật tốc độ trước khi render
      this.updateTransferSpeeds();
      this.renderTransfers();
      this.updateStatusCards();
      this.lastRenderTime = now;
    }
  }

  // ===== WebSocket integration =====
  connectWebSocket() {
    try {
      if (
        this.ws &&
        (this.ws.readyState === WebSocket.OPEN ||
          this.ws.readyState === WebSocket.CONNECTING)
      ) {
        return;
      }
      this.ws = new WebSocket(this.wsUrl);
      this.ws.onopen = () => {
        this.showNotification("Connected to upload server", "success");
        this.maybeStartNextUploads();
      };
      this.ws.onmessage = (ev) => this.handleWSMessage(ev);
      this.ws.onclose = () => {
        this.showNotification("Disconnected from upload server", "error");
        // Đưa các upload đang active về queued để đợi kết nối lại
        this.transfers.forEach((t) => {
          if (t.type === "upload" && t.status === "active") t.status = "queued";
        });
        this.renderTransfers();
      };
      this.ws.onerror = () => {
        this.showNotification("WebSocket error", "error");
      };
    } catch (e) {
      this.showNotification("Failed to connect WebSocket", "error");
    }
  }

  ensureSocketOpen() {
    return new Promise((resolve, reject) => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) return resolve();
      this.connectWebSocket();
      const start = Date.now();
      const check = () => {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) return resolve();
        if (Date.now() - start > 5000) return reject(new Error("WS not open"));
        setTimeout(check, 100);
      };
      check();
    });
  }

  send(obj) {
    try {
      this.ws &&
        this.ws.readyState === WebSocket.OPEN &&
        this.ws.send(JSON.stringify(obj));
    } catch {
      // ignore
    }
  }

  handleWSMessage(ev) {
    try {
      const msg = JSON.parse(ev.data);
      const fileId = msg.fileId;
      const transfer = this.transfers.find((t) => t.id === fileId);
      if (msg.event === "start-ack") {
        if (!transfer) return;
        transfer.status = "active";
        transfer.bytesSent = msg.offset || 0;
        this.runUploadLoopOnce(transfer);
      }
      if (msg.event === "progress") {
        if (!transfer) return;
        transfer.bytesSent = msg.offset;
        transfer.progress = Math.min(
          100,
          (transfer.bytesSent / Math.max(transfer.size, 1)) * 100
        );
        transfer.speed = this.formatSpeed(this.computeInstantSpeed(transfer));
        if (transfer.bytesSent >= transfer.size) {
          transfer.progress = 100;
        }
        // Sử dụng throttled render để tránh lag
        this.throttledRender();
      }
      // Nếu đang đợi ACK cho chunk vừa gửi, và offset đã >= điểm kỳ vọng → gỡ chờ
      if (transfer && transfer._ackResolver && transfer._ackOffset) {
        if (msg.offset >= transfer._ackOffset) {
          transfer._ackResolver();
          transfer._ackResolver = null;
          transfer._ackOffset = 0;
        }
      }

      if (msg.event === "offset-mismatch") {
        if (!transfer) return;
        transfer.bytesSent = msg.expected || 0;
        if (transfer.status === "active") this.runUploadLoopOnce(transfer);
      }
      if (msg.event === "paused") {
        if (!transfer) return;
        transfer.status = "paused";
        transfer.bytesSent = msg.offset || transfer.bytesSent;
        this.renderTransfers();
        return;
      }

      if (msg.event === "pause-ack") {
        if (!transfer) return;
        transfer.status = "paused";
        this.renderTransfers();
      }
      if (msg.event === "resume-ack") {
        if (!transfer) return;
        transfer.status = "active";
        transfer.bytesSent = msg.offset || transfer.bytesSent || 0;
        this.runUploadLoopOnce(transfer);
      }
      if (msg.event === "stop-ack") {
        // Transfer có thể đã bị xóa từ UI, chỉ cần log
        if (!transfer) {
          console.log(
            "Stop acknowledged for already removed transfer:",
            fileId
          );
          return;
        }
        // Remove transfer
        const idx = this.transfers.findIndex((t) => t.id === fileId);
        if (idx > -1) this.transfers.splice(idx, 1);
        this.updateStatusCards();
        this.renderTransfers();
        this.maybeStartNextUploads();
      }
      if (msg.event === "complete-ack") {
        if (!transfer) return;
        transfer.status = "completed";
        transfer.progress = 100;
        transfer.speed = "0 KB/s";
        this.updateStatusCards();
        this.renderTransfers();
        this.maybeStartNextUploads();
      }
      if (msg.event === "error") {
        // Không hiển thị lỗi "Session not found" khi đã cancel
        if (msg.error && msg.error.includes("Session not found")) {
          // Chỉ log lỗi này, không hiển thị notification
          console.log("Session not found (likely already cancelled):", fileId);
          return;
        }

        if (transfer) transfer.status = "error";
        this.showNotification(msg.error || "Upload error", "error");
        this.renderTransfers();
        this.maybeStartNextUploads();
      }
    } catch {
      // ignore parsing errors
    }
  }

  async startUpload(transfer) {
    transfer.type = "upload";
    transfer.status = "pending";
    transfer.progress = 0;
    transfer.speed = "0 KB/s";
    transfer.bytesSent = 0;
    transfer.lastTickBytes = 0;
    transfer.lastTickAt = performance.now();
    await this.ensureSocketOpen();
    this.send({
      action: "start",
      fileId: transfer.id,
      fileName: transfer.name,
      fileSize: transfer.size,
    });
  }

  async uploadLoop(transfer) {
    if (!transfer || transfer.status !== "active") return;
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

    const file = transfer.file;
    if (!file) return;

    // Loop sending chunks until paused/stopped/completed
    while (transfer.status === "active" && transfer.bytesSent < transfer.size) {
      const start = transfer.bytesSent;
      const end = Math.min(start + this.chunkSize, transfer.size);
      const slice = file.slice(start, end);
      const buffer = await slice.arrayBuffer();
      const base64 = this.arrayBufferToBase64(buffer);

      // Phanh backpressure: tránh “dồn” WS khiến pause/stop tới chậm
      while (this.ws && this.ws.bufferedAmount > 4 * 1024 * 1024) {
        // 4MB buffer
        await new Promise((r) => setTimeout(r, 10)); // nhả event loop 10ms
        // Nếu người dùng vừa pause/stop thì dừng vòng lặp ngay
        if (transfer.status !== "active") return;
      }

      // Gửi chunk
      this.send({
        action: "chunk",
        fileId: transfer.id,
        offset: start,
        data: base64,
      });
      // Đặt “điểm kỳ vọng” = byte sau khi gửi chunk này
      transfer._ackOffset = end;
      transfer._ackPromise = new Promise(
        (res) => (transfer._ackResolver = res)
      );

      // Chờ server ACK (progress có offset >= _ackOffset)
      await transfer._ackPromise;
      if (transfer.status !== "active") return;

      // Update progress
      transfer.bytesSent = end;
      transfer.progress = Math.min(
        100,
        (transfer.bytesSent / Math.max(transfer.size, 1)) * 100
      );
      transfer.speed = this.formatSpeed(
        this.computeInstantSpeed(transfer, transfer.bytesSent)
      );

      // Throttled render để tránh lag
      this.throttledRender();

      // Small yield to keep UI responsive
      await new Promise((r) => setTimeout(r, 5));
    }

    // Final render
    this.renderTransfers();
    this.updateStatusCards();

    if (transfer.status === "active" && transfer.bytesSent >= transfer.size) {
      // Notify server completed
      this.send({ action: "complete", fileId: transfer.id });
    }
  }
  // Chỉ chạy 1 vòng uploadLoop tại 1 thời điểm cho mỗi transfer
  runUploadLoopOnce(transfer) {
    if (!transfer) return;
    if (transfer._uplRunning) return; // đã chạy rồi thì thôi
    transfer._uplRunning = true;
    (async () => {
      try {
        await this.uploadLoop(transfer);
      } finally {
        transfer._uplRunning = false; // kết thúc mới cho chạy lại
      }
    })();
  }

  arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
  }

  computeInstantSpeed(transfer, currentBytes = null) {
    const now = performance.now();
    const total =
      currentBytes != null
        ? currentBytes
        : transfer.type === "upload"
        ? transfer.bytesSent
        : transfer.bytesReceived;

    const lastAt = transfer.lastTickAt || now;
    const lastBytes =
      typeof transfer.lastTickBytes === "number" ? transfer.lastTickBytes : 0;
    const elapsedMs = now - lastAt;

    let bps = transfer.currentSpeedBps || 0;
    if (elapsedMs > 250) {
      const delta = total - lastBytes;
      bps = delta > 0 ? (delta * 1000) / elapsedMs : 0;
      transfer.lastTickAt = now;
      transfer.lastTickBytes = total;
      transfer.currentSpeedBps = bps;
    }
    return bps;
  }

  // ===== Existing UI wiring =====
  setupEventListeners() {
    // File dropzone functionality
    const dropzone = document.getElementById("file-dropzone");
    const browseLink = document.getElementById("browse-files-link");
    const dropzoneLabel = document.querySelector(".dropzone");

    if (browseLink) {
      browseLink.addEventListener("click", (e) => {
        e.preventDefault();
        dropzone.click();
      });
    }

    if (dropzone) {
      dropzone.addEventListener("change", (e) => {
        this.handleFileSelection(e.target.files);
      });
    }

    // Keyboard support for dropzone
    if (dropzoneLabel) {
      dropzoneLabel.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          dropzone.click();
        }
      });
    }

    // URL input functionality
    const urlForm = document.querySelector(".add-url-section");
    const urlInput = document.getElementById("download-url");
    const addUrlBtn = document.getElementById("add-url-btn");

    if (urlForm) {
      urlForm.addEventListener("submit", (e) => {
        e.preventDefault();
        this.addDownloadURL();
      });
    }

    if (addUrlBtn) {
      addUrlBtn.addEventListener("click", (e) => {
        e.preventDefault();
        this.addDownloadURL();
      });
    }

    // Tab functionality
    this.setupTabs();

    // Status cards click handlers
    this.setupStatusCards();
  }

  setupDragAndDrop() {
    const dropzone = document.querySelector(".dropzone");

    if (!dropzone) return;

    ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
      });
    });

    ["dragenter", "dragover"].forEach((eventName) => {
      dropzone.addEventListener(eventName, () => {
        dropzone.classList.add("drag-over");
      });
    });

    ["dragleave", "drop"].forEach((eventName) => {
      dropzone.addEventListener(eventName, () => {
        dropzone.classList.remove("drag-over");
      });
    });

    dropzone.addEventListener("drop", (e) => {
      const files = e.dataTransfer.files;
      this.handleFileSelection(files);
    });
  }

  setupTabs() {
    const tabs = document.querySelectorAll(".tab");
    const panels = ["all", "uploads", "downloads"];

    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        const targetPanel = tab
          .getAttribute("aria-controls")
          .replace("panel-", "");
        this.switchTab(targetPanel);
      });

      tab.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          const targetPanel = tab
            .getAttribute("aria-controls")
            .replace("panel-", "");
          this.switchTab(targetPanel);
        }
      });
    });
  }

  setupStatusCards() {
    const cards = document.querySelectorAll(".card");
    cards.forEach((card) => {
      card.addEventListener("click", () => {
        const cardType = card.dataset.type || "all";
        this.switchTab(cardType);
      });
    });
  }

  switchTab(tabName) {
    // Update tab states
    const tabs = document.querySelectorAll(".tab");
    tabs.forEach((tab) => {
      tab.classList.remove("active");
      tab.setAttribute("aria-selected", "false");
      tab.setAttribute("tabindex", "-1");
    });

    const activeTab = document.getElementById(`tab-${tabName}`);
    if (activeTab) {
      activeTab.classList.add("active");
      activeTab.setAttribute("aria-selected", "true");
      activeTab.setAttribute("tabindex", "0");
    }

    this.activeTab = tabName;
    this.renderTransfers();
  }

  handleFileSelection(files) {
    if (!files || files.length === 0) return;

    Array.from(files).forEach((file) => {
      const transfer = {
        id: this.generateId(),
        name: file.name,
        size: file.size,
        type: "upload",
        status: "pending",
        progress: 0,
        speed: "0 KB/s",
        startTime: Date.now(),
        file: file,
        bytesSent: 0,
        lastTickBytes: 0,
        lastTickAt: performance.now(),
        currentSpeedBps: 0,
      };

      this.transfers.push(transfer);
    });

    this.updateStatusCards();
    this.renderTransfers();
    this.maybeStartNextUploads();
  }

  addDownloadURL() {
    const urlInput = document.getElementById("download-url");
    const rawUrl = urlInput.value.trim();
    if (!rawUrl) {
      this.showNotification("Vui lòng nhập URL", "error");
      return;
    }

    let normalized;
    try {
      normalized = new URL(rawUrl, window.location.origin).toString();
    } catch (e) {
      this.showNotification("URL không hợp lệ", "error");
      return;
    }

    // NEW: tên file hiển thị = phần cuối path, bỏ query, và decode cho đẹp
    const lastSeg = normalized.split("/").pop() || "";
    const prettyName = decodeURIComponent(lastSeg.split("?")[0]) || "download";

    const transfer = {
      id: this.generateId(),
      name: this.extractFileName(normalized),
      size: 0,
      type: "download",
      status: "pending",
      progress: 0,
      speed: "0 KB/s",
      startTime: Date.now(),
      url: normalized,
    };

    this.transfers.push(transfer);
    // Keep simulated for downloads
    this.startHttpDownload(transfer);

    urlInput.value = "";
    this.updateStatusCards();
    this.renderTransfers();
    this.showNotification("Đã bắt đầu tải", "success");
  }
  async startHttpDownload(transfer) {
    transfer.type = "download";
    transfer.status = "pending";
    transfer.progress = 0;
    transfer.speed = "0 KB/s";
    transfer.bytesReceived = transfer.bytesReceived || 0;
    transfer.chunks = transfer.chunks || [];
    transfer.lastTickBytes = transfer.bytesReceived;
    transfer.lastTickAt = performance.now();

    // HEAD để lấy size (có thể bị CORS/không hỗ trợ) → nếu lỗi vẫn tiếp tục GET
    try {
      const head = await fetch(transfer.url, { method: "HEAD" });
      if (head.ok) {
        const len = head.headers.get("content-length");
        transfer.size = len ? parseInt(len, 10) : 0;
      } else {
        // không set error, vẫn cho chạy GET
        transfer.size = transfer.size || 0;
      }
    } catch {
      transfer.size = transfer.size || 0;
    }
    // Bắt đầu stream (dù HEAD có thành công hay không)
    this.runDownloadOnce(transfer);
  }
  // [MỚI] Chạy 1 vòng tải (dùng lại Range nếu đã có bytesReceived)
  runDownloadOnce(transfer) {
    if (transfer._dlRunning) return; // chốt an toàn: tránh chạy trùng
    transfer._dlRunning = true;
    this.streamHttp(transfer)
      .catch(() => {}) // để không văng promise
      .finally(() => {
        transfer._dlRunning = false;
      });
  }

  async streamHttp(transfer) {
    if (transfer.status === "stopped") return;

    transfer.status = "active";
    // Tạo AbortController để Pause/Stop
    transfer.controller = new AbortController();
    const headers = {};
    if (transfer.bytesReceived > 0) {
      headers["Range"] = `bytes=${transfer.bytesReceived}-`;
    }

    let resp;
    try {
      resp = await fetch(transfer.url, {
        headers,
        signal: transfer.controller.signal,
      });
    } catch (e) {
      if (transfer.status !== "paused" && transfer.status !== "stopped") {
        this.showNotification("Network error while downloading", "error");
        transfer.status = "error";
        this.renderTransfers();
      }
      return;
    }

    if (!(resp.ok || resp.status === 206)) {
      this.showNotification(`HTTP ${resp.status} for GET`, "error");
      transfer.status = "error";
      this.renderTransfers();
      return;
    }

    const reader = resp.body.getReader();
    const pump = async () => {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        // Lưu chunk (demo: giữ RAM; muốn bền hơn có thể ghi IndexedDB)
        transfer.chunks.push(value);
        transfer.bytesReceived += value.length;

        // Cập nhật progress/speed
        transfer.progress = transfer.size
          ? Math.min(100, (transfer.bytesReceived / transfer.size) * 100)
          : 0;
        transfer.speed = this.formatSpeed(
          this.computeInstantSpeed(transfer, transfer.bytesReceived)
        );
        this.throttledRender();

        if (transfer.status !== "active") {
          // bị pause/stop giữa chừng
          try {
            transfer.controller.abort();
          } catch {}
          return;
        }
      }

      // Hoàn tất
      transfer.progress = 100;
      transfer.status = "completed";
      transfer.speed = "0 KB/s";

      // Gộp các chunk -> blob -> tải về
      const blob = new Blob(transfer.chunks);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = transfer.name || "download";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(a.href);

      this.updateStatusCards();
      this.renderTransfers();
    };

    await pump();
  }

  renderTransfers() {
    const noTransfersSection = document.querySelector(".no-transfers");
    const container = document.querySelector(".container");

    // Remove existing transfer list
    const existingList = document.querySelector(".transfers-list");
    if (existingList) {
      existingList.remove();
    }

    let filteredTransfers = this.transfers;

    // Filter based on active tab
    if (this.activeTab === "uploads") {
      filteredTransfers = this.transfers.filter((t) => t.type === "upload");
    } else if (this.activeTab === "downloads") {
      filteredTransfers = this.transfers.filter((t) => t.type === "download");
    }

    if (filteredTransfers.length === 0) {
      if (noTransfersSection) {
        noTransfersSection.style.display = "block";
      }
      return;
    }

    if (noTransfersSection) {
      noTransfersSection.style.display = "none";
    }

    // Create transfers list
    const transfersList = document.createElement("section");
    transfersList.className = "transfers-list";
    transfersList.setAttribute("aria-label", "Transfer list");

    filteredTransfers.forEach((transfer) => {
      const transferItem = this.createTransferItem(transfer);
      transfersList.appendChild(transferItem);
    });

    // Insert after tabs
    const tabsWrapper = document.querySelector(".tabs-wrapper");
    if (tabsWrapper && tabsWrapper.parentNode) {
      tabsWrapper.parentNode.insertBefore(
        transfersList,
        tabsWrapper.nextSibling
      );
    }
  }

  createTransferItem(transfer) {
    const item = document.createElement("div");
    item.className = `transfer-item ${transfer.status}`;
    item.setAttribute("data-id", transfer.id);

    const statusIcon = this.getStatusIcon(transfer.status);
    const progressBar = this.createProgressBar(transfer.progress);

    // Xác định nút nào cần hiển thị dựa trên status
    let actionButtons = "";

    if (transfer.status === "completed") {
      // File đã hoàn thành - chỉ có nút Stop
      actionButtons = `
                <button class="action-btn stop-btn" title="Stop">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M6 6h12v12H6z"/>
                    </svg>
                </button>
            `;
    } else if (transfer.status === "pending") {
      // File đang chờ - có nút Start
      actionButtons = `
                <button class="action-btn start-btn" title="Start">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M8 5v14l11-7z"/>
                    </svg>
                </button>
                <button class="action-btn stop-btn" title="Stop">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M6 6h12v12H6z"/>
                    </svg>
                </button>
            `;
    } else if (transfer.status === "active") {
      // File đang upload - có nút Pause và Stop
      actionButtons = `
                <button class="action-btn pause-btn" title="Pause">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
                    </svg>
                </button>
                <button class="action-btn stop-btn" title="Stop">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M6 6h12v12H6z"/>
                    </svg>
                </button>
            `;
    } else if (transfer.status === "paused") {
      // File đã pause - có nút Resume và Stop
      actionButtons = `
                <button class="action-btn resume-btn" title="Resume">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M8 5v14l11-7z"/>
                    </svg>
                </button>
                <button class="action-btn stop-btn" title="Stop">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M6 6h12v12H6z"/>
                    </svg>
                </button>
            `;
    } else if (transfer.status === "error") {
      // File có lỗi - có nút Start (retry) và Stop
      actionButtons = `
                <button class="action-btn start-btn" title="Retry">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/>
                    </svg>
                </button>
                <button class="action-btn stop-btn" title="Stop">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M6 6h12v12H6z"/>
                    </svg>
                </button>
            `;
    }

    item.innerHTML = `
            <div class="transfer-info">
                <div class="transfer-icon">${statusIcon}</div>
                <div class="transfer-details">
                    <div class="transfer-name">${transfer.name}</div>
                    <div class="transfer-meta">
                        <span class="transfer-size">${this.formatFileSize(
                          transfer.size
                        )}</span>
                        <span class="transfer-speed">${transfer.speed}</span>
                    </div>
                </div>
            </div>
            <div class="transfer-progress">
                ${progressBar}
                <div class="transfer-percentage">${Math.round(
                  transfer.progress
                )}%</div>
            </div>
            <div class="transfer-actions">
                ${actionButtons}
            </div>
        `;

    // Add event listeners
    const startBtn = item.querySelector(".start-btn");
    const pauseBtn = item.querySelector(".pause-btn");
    const resumeBtn = item.querySelector(".resume-btn");
    const stopBtn = item.querySelector(".stop-btn");

    if (startBtn) {
      startBtn.addEventListener("click", () => this.startTransfer(transfer));
    }

    if (pauseBtn) {
      pauseBtn.addEventListener("click", () => this.pauseTransfer(transfer));
    }

    if (resumeBtn) {
      resumeBtn.addEventListener("click", () => this.resumeTransfer(transfer));
    }

    if (stopBtn) {
      stopBtn.addEventListener("click", () => this.stopTransfer(transfer));
    }

    return item;
  }

  createProgressBar(progress) {
    return `
            <div class="progress-bar">
                <div class="progress-fill" style="width: ${progress}%"></div>
            </div>
        `;
  }

  getStatusIcon(status) {
    const icons = {
      pending:
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>',
      active:
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>',
      completed:
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>',
      paused:
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
      error:
        '<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/></svg>',
    };
    return icons[status] || icons.pending;
  }

  updateStatusCards() {
    const activeTransfers = this.transfers.filter((t) => t.status === "active");
    const completedTransfers = this.transfers.filter(
      (t) => t.status === "completed"
    );
    const totalFiles = this.transfers.length;
    const totalSpeed = this.calculateTotalSpeed();

    // Update status card values
    this.updateStatusCard("active", activeTransfers.length);
    this.updateStatusCard("completed", completedTransfers.length);
    this.updateStatusCard("total-files", totalFiles);
    this.updateStatusCard("total-speed", totalSpeed);
  }

  updateStatusCard(type, value) {
    const card = document.querySelector(`[data-type="${type}"]`);
    if (card) {
      const valueElement = card.querySelector(".card-text span:last-child");
      if (valueElement) {
        if (type === "total-speed") {
          valueElement.textContent = value;
        } else {
          valueElement.innerHTML = `<b>${value}</b>`;
        }
      }
    }
  }

  calculateTotalSpeed() {
    const activeTransfers = this.transfers.filter((t) => t.status === "active");
    if (activeTransfers.length === 0) return "0 KB/s";

    // Tính tổng tốc độ từ tất cả transfer đang active
    let totalBps = 0;
    activeTransfers.forEach((transfer) => {
      // Sử dụng currentSpeedBps nếu có, nếu không thì tính toán
      if (transfer.currentSpeedBps && transfer.currentSpeedBps > 0) {
        totalBps += transfer.currentSpeedBps;
      } else {
        const speed = this.computeInstantSpeed(transfer);
        if (speed > 0) {
          totalBps += speed;
        }
      }
    });

    if (totalBps === 0) return "0 KB/s";
    return this.formatSpeed(totalBps);
  }

  startTransfer(transfer) {
    if (transfer.type === "upload") {
      if (["pending", "error", "queued"].includes(transfer.status)) {
        // tôn trọng giới hạn đồng thời
        if (this.countActiveUploads() >= this.maxConcurrentUploads) {
          transfer.status = "queued";
          this.showNotification("Queued: waiting for available slot", "info");
          this.renderTransfers();
          return;
        }
        // 👉 chỉ khởi động qua startUpload (gửi 'start' và chờ 'start-ack' mới uploadLoop)
        this.startUpload(transfer);
      }
    } else {
      // For downloads (real)
      if (transfer.status === "pending") {
        this.startHttpDownload(transfer); // <-- thêm nhánh pending
      } else if (transfer.status === "paused" || transfer.status === "error") {
        this.runDownloadOnce(transfer);
      }
    }

    this.renderTransfers();
  }

  pauseTransfer(transfer) {
    if (transfer.type === "upload") {
      if (transfer.status === "active") {
        transfer.status = "paused";
        this.send({ action: "pause", fileId: transfer.id });
        // nếu đang đợi ACK thì gỡ để vòng lặp thoát nhanh
        if (transfer._ackResolver) {
          transfer._ackResolver();
          transfer._ackResolver = null;
          transfer._ackOffset = 0;
        }

        this.maybeStartNextUploads();
      }
    } else {
      // For downloads (real)
      if (transfer.status === "active") {
        transfer.status = "paused";
        if (transfer.controller) {
          try {
            transfer.controller.abort();
          } catch {}
        }
      }
    }

    this.renderTransfers();
  }

  resumeTransfer(transfer) {
    if (transfer.type === "upload") {
      if (transfer.status === "paused") {
        if (this.countActiveUploads() >= this.maxConcurrentUploads) {
          transfer.status = "queued";
          this.showNotification("Queued: waiting for available slot", "info");
          this.renderTransfers();
          return;
        }
        transfer.status = "active";
        this.send({ action: "resume", fileId: transfer.id });
        this.runUploadLoopOnce(transfer);
      } else if (
        transfer.status === "queued" ||
        transfer.status === "pending"
      ) {
        this.startTransfer(transfer);
      }
    } else {
      // For downloads (real)
      if (transfer.status === "paused" || transfer.status === "error") {
        this.runDownloadOnce(transfer); // dùng Range theo bytesReceived hiện có
      }
    }
  }

  stopTransfer(transfer) {
    if (transfer.type === "upload") {
      // Đặt trạng thái stopped để vòng lặp dừng ngay
      transfer.status = "stopped";
      // Gửi lệnh stop đến server
      this.send({ action: "stop", fileId: transfer.id, delete: true });
      // HỦY CHỜ ACK để không kẹt await khi dừng
      if (transfer._ackResolver) {
        transfer._ackResolver();
        transfer._ackResolver = null;
        transfer._ackOffset = 0;
      }

      // Cập nhật UI ngay lập tức để tránh delay
      const index = this.transfers.findIndex((t) => t.id === transfer.id);
      if (index > -1) {
        this.transfers.splice(index, 1);
        this.updateStatusCards();
        this.renderTransfers();
      }
      // Thử start các pending khác
      this.maybeStartNextUploads();
    } else {
      // For downloads (real)
      transfer.status = "stopped";
      if (transfer.controller) {
        try {
          transfer.controller.abort();
        } catch {}
      }
      // Xoá khỏi UI
      const index = this.transfers.findIndex((t) => t.id === transfer.id);
      if (index > -1) {
        this.transfers.splice(index, 1);
        this.updateStatusCards();
        this.renderTransfers();
      }
    }
  }

  // Legacy method - keep for backward compatibility
  togglePause(transfer) {
    if (transfer.status === "active") {
      this.pauseTransfer(transfer);
    } else if (transfer.status === "paused") {
      this.resumeTransfer(transfer);
    }
  }

  generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2);
  }

  isValidURL(string) {
    try {
      new URL(string);
      return true;
    } catch (_) {
      return false;
    }
  }

  extractFileName(url) {
    try {
      const urlObj = new URL(url);
      const pathname = urlObj.pathname;
      const fileName = pathname.split("/").pop();
      return fileName || "download";
    } catch {
      return "download";
    }
  }

  formatFileSize(bytes) {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  }

  formatSpeed(bytesPerSecond) {
    if (!bytesPerSecond || bytesPerSecond === 0) return "0 KB/s";
    const k = 1024;
    const sizes = ["B/s", "KB/s", "MB/s", "GB/s"];
    const i = Math.floor(Math.log(bytesPerSecond) / Math.log(k));
    return (
      parseFloat((bytesPerSecond / Math.pow(k, i)).toFixed(2)) + " " + sizes[i]
    );
  }

  showNotification(message, type = "info") {
    // Create notification element
    const notification = document.createElement("div");
    notification.className = `notification ${type}`;
    notification.textContent = message;

    // Add to page
    document.body.appendChild(notification);

    // Remove after 3 seconds
    setTimeout(() => {
      if (notification.parentNode) {
        notification.parentNode.removeChild(notification);
      }
    }, 3000);
  }

  // Trả về số upload đang active
  countActiveUploads() {
    return this.transfers.filter(
      (t) => t.type === "upload" && t.status === "active"
    ).length;
  }

  // Bắt đầu các upload đang pending nếu còn slot trống
  maybeStartNextUploads() {
    let active = this.countActiveUploads();
    if (active >= this.maxConcurrentUploads) return;

    const pendingList = this.transfers.filter(
      (t) =>
        t.type === "upload" && (t.status === "pending" || t.status === "queued")
    );
    for (const t of pendingList) {
      if (active >= this.maxConcurrentUploads) break;
      this.startUpload(t);
      active += 1;
    }
  }
}

// Initialize the application when DOM is loaded
document.addEventListener("DOMContentLoaded", () => {
  new FlexTransferHub();
});

// Export for potential module usage
if (typeof module !== "undefined" && module.exports) {
  module.exports = FlexTransferHub;
}
