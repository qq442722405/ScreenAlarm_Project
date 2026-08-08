# -*- coding: utf-8 -*-
# 模块化拆分文件：从原主程序提取，后续可独立维护

class MonitorThread(QThread):
    value_updated = Signal(object, str, object, str)
    countdown_tick = Signal(float)

    # 【修改项 1】识别间隔默认 10 秒
    def __init__(self, boxes, interval=10.0, ocr_params=None, scale=1.0, parent=None):
        super().__init__(parent)
        self.boxes = boxes
        self.interval = max(0.1, interval)
        self.ocr_params = ocr_params or {'scale': 3.0, 'clahe': 2.0, 'thresh_block': 11, 'thresh_c': 2}
        self.scale = scale
        self.running = True
        self.reader = None

    def set_reader(self, reader):
        self.reader = reader

    def update_params(self, interval=None, ocr_params=None, scale=None):
        if interval is not None:
            self.interval = max(0.1, interval)
        if ocr_params is not None:
            self.ocr_params = ocr_params
        if scale is not None:
            self.scale = scale

    def stop(self):
        self.running = False

    def _clean_digit_text(self, text):
        mapping = {
            'O': '0', 'o': '0', 'D': '0',
            'I': '1', 'l': '1', '|': '1', '!': '1',
            'Z': '2', 'z': '2',
            'S': '5', 's': '5',
            'B': '8',
        }
        res = list(text)
        for i, ch in enumerate(res):
            if ch in mapping:
                res[i] = mapping[ch]
        return "".join(res)

    def run(self):
        scale = self.scale

        with mss.mss() as sct:
            while self.running:
                if not self.reader:
                    self.msleep(200)
                    continue

                start_time = time.time()
                box_list = list(self.boxes)

                for box in box_list:
                    if not self.running: break
                    
                    capture_x = getattr(box, 'capture_x', 0)
                    capture_y = getattr(box, 'capture_y', 0)
                    capture_w = getattr(box, 'capture_w', 0)
                    capture_h = getattr(box, 'capture_h', 0)
                    dp = getattr(box, 'decimal_places', 0)

                    x = int(capture_x * scale)
                    y = int(capture_y * scale)
                    w = int(capture_w * scale)
                    h = int(capture_h * scale)

                    if w <= 0 or h <= 0: continue

                    try:
                        bbox = {"top": y, "left": x, "width": w, "height": h}
                        sct_img = sct.grab(bbox)
                        img_np = np.array(sct_img)

                        if img_np.shape[2] == 4:
                            bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
                        else:
                            bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                        scale_factor = max(1.0, float(self.ocr_params.get('scale', 3.0)))
                        new_w, new_h = int(w * scale_factor), int(h * scale_factor)
                        scaled_bgr = cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

                        attempts = []

                        ok1, buf1 = cv2.imencode(".png", scaled_bgr)
                        if ok1: attempts.append(buf1.tobytes())

                        gray = cv2.cvtColor(scaled_bgr, cv2.COLOR_BGR2GRAY)
                        ok2, buf2 = cv2.imencode(".png", gray)
                        if ok2: attempts.append(buf2.tobytes())

                        inverted = cv2.bitwise_not(gray)
                        ok3, buf3 = cv2.imencode(".png", inverted)
                        if ok3: attempts.append(buf3.tobytes())

                        clahe_clip = float(self.ocr_params.get('clahe', 2.0))
                        if clahe_clip > 0:
                            clahe = cv2.createCLAHE(clipLimit=clahe_clip, tileGridSize=(8, 8))
                            enhanced = clahe.apply(gray)
                        else:
                            enhanced = gray

                        sharpened = cv2.filter2D(enhanced, -1, np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]]))
                        
                        block = int(self.ocr_params.get('thresh_block', 11))
                        c_val = int(self.ocr_params.get('thresh_c', 2))
                        binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, c_val)
                        ok4, buf4 = cv2.imencode(".png", binary)
                        if ok4: attempts.append(buf4.tobytes())

                        found_val = None
                        last_raw_str = ""

                        for buf in attempts:
                            if not self.running: break
                            raw_text = str(self.reader.classification(buf))
                            if not raw_text: continue
                            last_raw_str = raw_text

                            clean_t = self._clean_digit_text(raw_text).replace(' ', '')
                            clean_t = re.sub(r'(?<=\d)[,::·\'`_\-*\°ae~,;–—.\s、]+(?=\d)', '.', clean_t)

                            if dp > 0:
                                digits = re.sub(r'\D', '', clean_t)
                                if digits:
                                    if len(digits) > dp:
                                        val_str = digits[:-dp] + '.' + digits[-dp:]
                                    else:
                                        val_str = "0." + digits.zfill(dp)
                                    try:
                                        found_val = float(val_str)
                                        break
                                    except ValueError:
                                        pass
                            else:
                                nums = re.findall(r'-?\d+(?:\.\d+)?', clean_t)
                                if nums:
                                    try:
                                        found_val = float(nums[0])
                                        break
                                    except ValueError:
                                        pass

                        now_str = datetime.now().strftime("%H:%M:%S")
                        if self.running:
                            self.value_updated.emit(box, now_str, found_val, last_raw_str)

                    except Exception as e:
                        now_str = datetime.now().strftime("%H:%M:%S")
                        if self.running:
                            self.value_updated.emit(box, now_str, None, f"异常:{e}")

                elapsed = time.time() - start_time
                sleep_needed = max(0.05, self.interval - elapsed)
                end_time = time.time() + sleep_needed

                while self.running and time.time() < end_time:
                    rem = max(0.0, end_time - time.time())
                    self.countdown_tick.emit(rem)
                    self.msleep(50)


# ==================== 8. Flask 网页/手机端 WEB 交互界面 ====================
MOBILE_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="icon" href="/favicon.ico" type="image/x-icon">
    <link rel="shortcut icon" href="/favicon.ico" type="image/x-icon">
    <title>📱 中控数据面板</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #121218; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 12px; }
        
        .container { max-width: 600px; margin: 0 auto; width: 100%; }

        .header { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; background: #1a1a26; border-radius: 10px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.1); flex-wrap: wrap; gap: 8px; }
        .header-title-box { display: flex; flex-direction: column; gap: 2px; }
        .title { font-size: 15px; font-weight: bold; color: #00ff8c; cursor: pointer; display: flex; align-items: center; gap: 6px; user-select: none; }
        .status { font-size: 11px; color: #aaa; font-weight: bold; }

        .header-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
        .btn-top { background: #2e9a58; color: #fff; border: none; border-radius: 6px; padding: 6px 10px; font-size: 12px; font-weight: bold; cursor: pointer; transition: background 0.2s; }
        .btn-top:active { opacity: 0.8; }
        .btn-top.active { background: #b03a3a; }
        .btn-top.btn-grille { background: #0088cc; }
        .btn-top.btn-grille.active { background: #cc3333; }
        .btn-sound { background: rgba(255,255,255,0.15); color: #00ff8c; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; padding: 6px 8px; font-size: 12px; font-weight: bold; cursor: pointer; }

        .btn-fold-tool { background: rgba(255,255,255,0.1); color: #00ff8c; border: 1px solid rgba(0,255,140,0.3); border-radius: 6px; padding: 6px 8px; font-size: 12px; font-weight: bold; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; text-decoration: none; }
        .btn-fold-tool:active { background: rgba(0,255,140,0.2); }

        .login-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 6px; width: 100%; font-size: 12px; }

        .card { background: #1a1a26; border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.1); transition: all 0.3s; }
        
        .card.alarm { background:#fff3cd; border:2px solid #ffc107; border: 2px solid #ff4d4d; background: rgba(255, 77, 77, 0.08); animation: blink 1s infinite alternate; }
        @keyframes blink { from { box-shadow: 0 0 5px rgba(255,77,77,0.3); } to { box-shadow: 0 0 15px rgba(255,77,77,0.8); } }

        .card.warning { border: 2px solid #ffaa00; background: rgba(255, 170, 0, 0.08); }

        .card-header { display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: #888; font-weight: bold; }
        .card-title-box { display: flex; align-items: center; gap: 6px; cursor: pointer; flex-grow: 1; }
        .card-title { color: #ffffff; font-size: 15px; font-weight: bold; }

        .btn-action { color: #fff; border-radius: 6px; padding: 4px 8px; font-size: 11px; font-weight: bold; cursor: pointer; border: none; }
        .btn-action:active { opacity: 0.8; }
        .btn-clear { background: #ff4d4d; color: white; }

        .btn-alarm-on { background: #2e9a58; color: #ffffff; border: 1px solid #3fb950; }
        .btn-alarm-off { background: #4a4d52; color: #cccccc; border: 1px solid #666666; }

        .value-box { text-align: center; margin: 8px 0; display: flex; align-items: center; justify-content: center; gap: 10px; }
        .val-text { font-size: 32px; font-weight: bold; color: #00ff8c; font-family: monospace; }
        .val-text.alarm-text { color: #ff4d4d; }
        .val-text.warning-text { color: #ffaa00; }

        .fold-body { margin-top: 8px; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 8px; }

        .setting-row { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; font-size: 11px; flex-wrap: wrap; }
        .setting-row label { color: #ffaa00; font-weight: bold; }
        .setting-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 2px; width: 90px; text-align: center; font-size: 11px; }

        .log-title { margin-top: 6px; font-size: 11px; color: #888; font-weight: bold; }
        .log-list { margin-top: 4px; background: rgba(0,0,0,0.4); border-radius: 6px; padding: 6px 8px; font-size: 11px; font-family: monospace; height: 110px; overflow-y: auto; color: #00ff8c; }
        .log-list::-webkit-scrollbar { width: 4px; }
        .log-list::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 2px; }
        .log-item { padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.05); white-space: nowrap; }

        /* 模态框弹窗样式 */
        .modal-overlay { display: none; position: fixed; top:0; left:0; width:100%; height:100%; background: rgba(0,0,0,0.7); z-index: 1000; justify-content: center; align-items: center; }
        .modal-content { background: #1a1a26; border: 1px solid rgba(255,255,255,0.2); border-radius: 10px; width: 90%; max-width: 420px; padding: 16px; color: #e0e0e0; }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 8px; }
        .modal-close { cursor: pointer; color: #ff4d4d; font-weight: bold; font-size: 16px; }

        /* 【修改项 2 & 3 增加的 CSS 样式】 */
        .diff-text { font-size: 13px; font-weight: bold; font-family: monospace; padding: 2px 6px; border-radius: 4px; background: rgba(0,0,0,0.3); }
        .diff-up { color: #ff4d4d !important; }   /* 上涨 红色 */
        .diff-down { color: #00ff8c !important; } /* 下降 绿色 */
        .diff-zero { color: #888888 !important; }

        /* 布局容器模式 */
        #cards-container.strip-mode { display: flex; flex-direction: column; gap: 10px; }
        #cards-container.square-mode { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }

        /* 正方形卡片内部排版 */
        .square-card { min-width:280px; min-height:240px; text-align: center; display: flex; flex-direction: column; justify-content: center; align-items: center; padding: 14px 8px; }
        .square-card .sq-row1 { font-size: 18px; font-weight: bold; color: #ffffff; margin-bottom: 4px; width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .square-card .sq-row2 { font-size: 44px; font-weight: bold; font-family: monospace; color: #00ff8c; margin: 4px 0; }
        .square-card .sq-row3 { font-size: 13px; font-weight: bold; font-family: monospace; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-title-box">
                <div class="title">
                    📱 中控数据面板
                </div>
                <div id="status" class="status">初始化...</div>
            </div>
            <div class="header-actions">
                <button id="btn-mode-toggle" class="btn-top" style="background: #6c5ce7;" onclick="toggleDisplayMode()">模式切换</button>

                <!-- 登录按钮 -->
                <div id="login-box" style="display: inline-flex; align-items: center; gap: 4px;">
                    <button class="btn-fold-tool" style="background:#0088cc; color:white; border:none;" onclick="openLoginModal()">🔐 登录</button>
                </div>
                <div id="user-box" style="display: none; align-items: center; gap: 4px;">
                    <span id="current-username" style="color:#00ff8c; font-size:12px; font-weight:bold;">👤 已登录</span>
                    <button class="btn-fold-tool" style="background:#e65100; color:white; border:none;" onclick="openUserMgmtModal()">⚙️ 用户管理</button>
                    <button class="btn-fold-tool" style="background:#555; color:white; border:none;" onclick="handleLogout()">🚪 退出</button>
                </div>

                <button id="btn-sound" class="btn-sound" onclick="toggleWebSound()">🔊 网页声音</button>
                <button id="btn-monitor" class="btn-top" onclick="postAction('toggle_monitor', -1)">▶ 开始监控</button>
                <button id="btn-grille" class="btn-top btn-grille" onclick="postAction('toggle_grille', -1)">▶ 开始操作</button>
            </div>
        </div>

        <div style="margin-bottom:10px;color:#aaa;font-size:12px;">对比（分钟）：<input id="compare-min" class="setting-input" value="10" onchange="localStorage.setItem('compareMinutes',this.value)"></div><div id="cards-container" class="strip-mode"></div><script>localStorage.setItem("defaultFold","true");</script>
    </div>

    <!-- 独立登录界面弹窗 -->
    <div id="login-modal" class="modal-overlay">
        <div class="modal-content" style="max-width: 320px;">
            <div class="modal-header">
                <span style="font-weight:bold; color:#00ff8c; font-size:14px;">🔐 用户登录</span>
                <span class="modal-close" onclick="closeLoginModal()">✖</span>
            </div>
            <div style="display: flex; flex-direction: column; gap: 10px; margin-top: 8px;">
                <div>
                    <label style="font-size:12px; color:#aaa; font-weight:bold; display:block; margin-bottom:4px;">账号：</label>
                    <input type="text" id="login-user" placeholder="请输入账号" class="login-input" style="height: 32px; padding: 4px 8px;">
                </div>
                <div>
                    <label style="font-size:12px; color:#aaa; font-weight:bold; display:block; margin-bottom:4px;">密码：</label>
                    <input type="password" id="login-pass" placeholder="请输入密码" class="login-input" style="height: 32px; padding: 4px 8px;">
                </div>
                <button class="btn-action" style="background:#0088cc; color:white; height: 34px; margin-top: 6px; font-size: 13px;" onclick="handleLogin()">登录</button>
            </div>
        </div>
    </div>

    <!-- 用户管理模态框 -->
    <div id="user-modal" class="modal-overlay">
        <div class="modal-content">
            <div class="modal-header">
                <span style="font-weight:bold; color:#00ff8c; font-size:14px;">⚙️ 用户管理面板</span>
                <span class="modal-close" onclick="closeUserMgmtModal()">✖</span>
            </div>
            
            <!-- 修改密码 -->
            <div style="margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px dashed rgba(255,255,255,0.1);">
                <div style="font-size:12px; color:#aaa; margin-bottom:6px; font-weight:bold;">🔑 修改当前密码 (<span id="modal-curr-user" style="color:#00ff8c;"></span>)</div>
                <div class="setting-row">
                    <input type="password" id="old-pass" placeholder="旧密码" class="setting-input" style="width:85px;">
                    <input type="password" id="new-pass" placeholder="新密码" class="setting-input" style="width:85px;">
                    <button class="btn-action" style="background:#0088cc; color:white; margin-left: auto;" onclick="handleChangePassword()">修改密码</button>
                </div>
            </div>

            <!-- 新增与删除用户 -->
            <div>
                <div style="font-size:12px; color:#aaa; margin-bottom:6px; font-weight:bold;">➕ 新增用户</div>
                <div class="setting-row" style="margin-bottom:10px;">
                    <input type="text" id="new-user-name" placeholder="新账号" class="setting-input" style="width:85px;">
                    <input type="password" id="new-user-pass" placeholder="新密码" class="setting-input" style="width:85px;">
                    <button class="btn-action" style="background:#2e9a58; color:white; margin-left: auto;" onclick="handleAddUser()">添加用户</button>
                </div>

                <div style="font-size:12px; color:#aaa; margin-bottom:6px; font-weight:bold;">👥 用户账号列表</div>
                <div id="user-list-container" style="max-height: 120px; overflow-y: auto; background: rgba(0,0,0,0.3); padding: 6px; border-radius: 4px;">
                </div>
            </div>
        </div>
    </div>

    <script>
        const collapsedMap = {};
        let isMainPanelCollapsed = false;
        let isLoggedIn = localStorage.getItem('isLoggedIn') === 'true';
        let currentUser = localStorage.getItem('currentUser') || '';
        let lastLoggedInState = null;
        let webSoundEnabled = true;
        let audioCtx = null;
        let alarmTimer = null;
        let cachedBoxes = [];

        // 【修改项 2 & 3】本地数据对比与显示模式全局变量
        const historyStore = {}; // { boxId: [ { time: timestamp, val: number }, ... ] }
        let displayMode = localStorage.getItem('displayMode') || 'strip'; // 'strip' 或 'square'

        function toggleDisplayMode() {
            displayMode = (displayMode === 'strip') ? 'square' : 'strip';
            localStorage.setItem('displayMode', displayMode);
            updateDisplayModeUI();
            forceReRenderCards();
            refreshData();
        }

        function updateDisplayModeUI() {
            const btn = document.getElementById('btn-mode-toggle');
            const container = document.getElementById('cards-container');
            if (btn) {
                btn.innerText = (displayMode === 'strip') ? '模式切换' : '模式切换';
            }
            if (container) {
                container.className = (displayMode === 'square') ? 'square-mode' : 'strip-mode';
            }
        }

        // 记录数值历史用于对比
        function recordHistory(boxId, valStr) {
            const num = parseFloat(valStr);
            if (isNaN(num)) return;
            if (!historyStore[boxId]) historyStore[boxId] = [];
            const now = Date.now();
            historyStore[boxId].push({ time: now, val: num });
            // 保留最近 3 小时的历史点
            const threeHoursAgo = now - 3 * 3600 * 1000;
            historyStore[boxId] = historyStore[boxId].filter(h => h.time >= threeHoursAgo);
        }

        // 已关闭网页端时间对比功能
        function getCompareDiff(boxId, currentValStr) {
            const num = parseFloat(currentValStr);
            if (isNaN(num)) return {text:'', cls:'diff-zero'};
            const min = parseFloat(localStorage.getItem('compareMinutes') || '10');
            const old = (historyStore[boxId]||[]).filter(x=>Date.now()-x.time>=min*60000).pop();
            if (!old) return {text:'', cls:'diff-zero'};
            const d = num-old.val;
            if(d>0) return {text:'↑ '+d.toFixed(4), cls:'diff-up'};
            if(d<0) return {text:'↓ '+Math.abs(d).toFixed(4), cls:'diff-down'};
            return {text:'=', cls:'diff-zero'};
        }


        function openLogWindow(title, content) {
            const win = window.open('', 'logWindow', 'width=520,height=500');
            if (!win) return;
            win.document.write(`
                <html><head><title>${title}</title>
                <style>
                body{background:#1a1a26;color:#eee;font-family:Arial;padding:20px;}
                .log{padding:8px;border-bottom:1px solid #444;}
                </style></head>
                <body><h3>📜 ${title}</h3>
                <div>${content}</div></body></html>`);
            win.document.close();
        }
        function toggleMainPanelFold() {
            isMainPanelCollapsed = !isMainPanelCollapsed;
            updateMainPanelFoldUI();
        }

        function updateMainPanelFoldUI() {
            const icon = document.getElementById('main-fold-icon');
            const statusEl = document.getElementById('status');
            const actionsEl = document.querySelector('.header-actions');
            const cardsEl = document.getElementById('cards-container');

            if (isMainPanelCollapsed) {
                if (icon) icon.innerText = '▶';
                if (statusEl) statusEl.style.display = 'none';
                if (actionsEl) actionsEl.style.display = 'none';
                if (cardsEl) cardsEl.style.display = 'none';
            } else {
                if (icon) icon.innerText = '▼';
                if (statusEl) statusEl.style.display = 'block';
                if (actionsEl) actionsEl.style.display = 'flex';
                if (cardsEl) cardsEl.style.display = (displayMode === 'square') ? 'grid' : 'flex';
            }
        }

        function openLoginModal() {
            document.getElementById('login-modal').style.display = 'flex';
        }

        function closeLoginModal() {
            document.getElementById('login-modal').style.display = 'none';
        }

        function updateLoginUI() {
            const loginBox = document.getElementById('login-box');
            const userBox = document.getElementById('user-box');
            const usernameDisplay = document.getElementById('current-username');
            const btnMonitor = document.getElementById('btn-monitor');
            const btnGrille = document.getElementById('btn-grille');

            if (isLoggedIn) {
                if (loginBox) loginBox.style.display = 'none';
                if (userBox) userBox.style.display = 'inline-flex';
                if (usernameDisplay) usernameDisplay.innerText = `👤 ${currentUser}`;
                if (btnMonitor) btnMonitor.style.display = 'inline-block';
                if (btnGrille) btnGrille.style.display = 'inline-block';
            } else {
                if (loginBox) loginBox.style.display = 'inline-flex';
                if (userBox) userBox.style.display = 'none';
                if (btnMonitor) btnMonitor.style.display = 'none';
                if (btnGrille) btnGrille.style.display = 'none';
            }
        }

        async function handleLogin() {
            const u = document.getElementById('login-user').value.trim();
            const p = document.getElementById('login-pass').value.trim();
            if (!u || !p) {
                alert('请输入账号和密码！');
                return;
            }
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: u, password: p })
                });
                const data = await res.json();
                if (data.success) {
                    isLoggedIn = true;
                    currentUser = data.username;
                    localStorage.setItem('isLoggedIn', 'true');
                    localStorage.setItem('currentUser', currentUser);
                    closeLoginModal();
                    document.getElementById('login-user').value = '';
                    document.getElementById('login-pass').value = '';
                    updateLoginUI();
                    forceReRenderCards();
                    refreshData();
                } else {
                    alert(data.message || '登录失败！');
                }
            } catch(e) {
                alert('请求异常，请重试！');
            }
        }

        function handleLogout() {
            isLoggedIn = false;
            currentUser = '';
            localStorage.setItem('isLoggedIn', 'false');
            localStorage.removeItem('currentUser');
            updateLoginUI();
            forceReRenderCards();
            refreshData();
        }

        function openUserMgmtModal() {
            document.getElementById('user-modal').style.display = 'flex';
            document.getElementById('modal-curr-user').innerText = currentUser;
            loadUserList();
        }

        function closeUserMgmtModal() {
            document.getElementById('user-modal').style.display = 'none';
        }

        async function handleChangePassword() {
            const oldP = document.getElementById('old-pass').value.trim();
            const newP = document.getElementById('new-pass').value.trim();
            if (!oldP || !newP) {
                alert('请填写旧密码和新密码！');
                return;
            }
            try {
                const res = await fetch('/api/users/change_password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: currentUser, old_password: oldP, new_password: newP })
                });
                const data = await res.json();
                alert(data.message);
                if (data.success) {
                    document.getElementById('old-pass').value = '';
                    document.getElementById('new-pass').value = '';
                }
            } catch(e) {
                alert('修改密码异常！');
            }
        }

        async function handleAddUser() {
            const u = document.getElementById('new-user-name').value.trim();
            const p = document.getElementById('new-user-pass').value.trim();
            if (!u || !p) {
                alert('请输入新账号和新密码！');
                return;
            }
            try {
                const res = await fetch('/api/users/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: u, password: p })
                });
                const data = await res.json();
                alert(data.message);
                if (data.success) {
                    document.getElementById('new-user-name').value = '';
                    document.getElementById('new-user-pass').value = '';
                    loadUserList();
                }
            } catch(e) {
                alert('添加用户异常！');
            }
        }

        async function handleDeleteUser(username) {
            if (!confirm(`确定要删除用户 "${username}" 吗？`)) return;
            try {
                const res = await fetch('/api/users/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username })
                });
                const data = await res.json();
                alert(data.message);
                if (data.success) {
                    loadUserList();
                }
            } catch(e) {
                alert('删除用户异常！');
            }
        }

        async function loadUserList() {
            try {
                const res = await fetch('/api/users/list');
                const data = await res.json();
                const container = document.getElementById('user-list-container');
                if (data.users && data.users.length > 0) {
                    container.innerHTML = data.users.map(u => `
                        <div style="display:flex; justify-content:space-between; align-items:center; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size:12px;">
                            <span>👤 ${u}</span>
                            ${u !== 'admin' ? `<button class="btn-action" style="background:#ff4d4d; color:white;" onclick="handleDeleteUser('${u}')">删除</button>` : '<span style="color:#888; font-size:11px;">(默认管理员)</span>'}
                        </div>
                    `).join('');
                } else {
                    container.innerHTML = '<div style="color:#888; font-size:11px;">暂无其他用户</div>';
                }
            } catch(e) {
                console.error("加载用户列表失败:", e);
            }
        }

        function forceReRenderCards() {
            const container = document.getElementById('cards-container');
            if (container) container.innerHTML = '';
        }

        function initAudio() {
            if (!audioCtx) {
                audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (audioCtx.state === 'suspended') {
                audioCtx.resume();
            }
        }
        document.addEventListener('click', initAudio, { once: false });

        function toggleWebSound() {
            webSoundEnabled = !webSoundEnabled;
            const btn = document.getElementById('btn-sound');
            if (webSoundEnabled) {
                btn.innerText = "🔊 网页声音";
                btn.style.color = "#00ff8c";
            } else {
                btn.innerText = "🔇 网页静音";
                btn.style.color = "#aaa";
                stopWebAlarmSound();
            }
        }

        function triggerAlarmSoundLoop(play) {
            if (play && webSoundEnabled) {
                if (!alarmTimer) {
                    alarmTimer = setInterval(() => {
                        if (!webSoundEnabled) return;
                        try {
                            initAudio();
                            const osc = audioCtx.createOscillator();
                            const gain = audioCtx.createGain();
                            osc.type = 'sawtooth';
                            osc.frequency.setValueAtTime(850, audioCtx.currentTime);
                            gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
                            gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.25);
                            osc.connect(gain);
                            gain.connect(audioCtx.destination);
                            osc.start();
                            osc.stop(audioCtx.currentTime + 0.25);
                        } catch(e) {}
                    }, 400);
                }
            } else {
                stopWebAlarmSound();
            }
        }

        function stopWebAlarmSound() {
            if (alarmTimer) {
                clearInterval(alarmTimer);
                alarmTimer = null;
            }
        }

        async function postAction(action, boxId, data = {}) {
            try {
                await fetch('/api/action', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action, id: boxId, data })
                });
                refreshData();
            } catch(e) {
                console.error("操作失败:", e);
            }
        }

        function toggleFold(boxId) {
            collapsedMap[boxId] = !collapsedMap[boxId];
            refreshData();
        }

        function saveLimits(boxId) {
            const lowerVal = parseFloat(document.getElementById(`input-lower-${boxId}`).value);
            const midVal = parseFloat(document.getElementById(`input-mid-${boxId}`).value);
            const upperVal = parseFloat(document.getElementById(`input-upper-${boxId}`).value);
            if (!isNaN(lowerVal) && !isNaN(midVal) && !isNaN(upperVal)) {
                postAction('set_limits', boxId, { lower: lowerVal, mid_val: midVal, upper: upperVal });
            } else {
                alert("请输入有效的数值！");
            }
        }

        function renderCardDOM(cardEl, b, isCollapsed, isWarning, currentTimeStr) {
            const currentFoldState = cardEl.getAttribute('data-collapsed');
            const stateChanged = (currentFoldState !== String(isCollapsed));

            let valColor = '#00ff8c';
            if (b.is_alarm) {
                valColor = '#ff4d4d';
            } else if (isWarning) {
                valColor = '#ffaa00';
            }

            // 【修改项 2 & 3】获取自定义对比差值
            const diff = getCompareDiff(b.id, b.value);

            // 【修改项 3】正方形模式渲染逻辑（第一行名字，第二行大数字，固定显示）
            if (displayMode === 'square') {
                cardEl.className = `card square-card ${b.is_alarm ? 'alarm' : (isWarning ? 'warning' : '')}`;
                cardEl.innerHTML = `
                    <div class="sq-row1">${b.name}</div>
                    <div class="sq-row2" style="color: ${valColor};">${b.value}</div>
                    <div class="sq-row3 diff-text ${diff.cls}">${diff.text}</div>
                `;
                return;
            }

            // 长条模式渲染逻辑
            if (stateChanged) {
                cardEl.setAttribute('data-collapsed', String(isCollapsed));
                
                if (isCollapsed) {
                    cardEl.innerHTML = `
                        <div class="card-header" onclick="toggleFold(${b.id})" style="cursor:pointer; padding: 4px 0;">
                            <div class="card-title-box">
                                <span class="card-title">${b.name}</span>
                                <span style="font-size:12px; color:#888; margin-left:4px;">▶</span>
                            </div>
                            
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span id="diff-tag-${b.id}" class="diff-text ${diff.cls}">${diff.text}</span>
                                <span id="collapsed-val-${b.id}" style="font-size: 16px; font-weight: bold; font-family: monospace; color: ${valColor};">${b.value}</span>
                            </div>
                        </div>
                    `;
                    return;
                } else {
                    let logsHtml = (b.logs && b.logs.length > 0)
                        ? b.logs.map(l => `<div class="log-item" onclick="openLogWindow('历史日志', JSON.stringify(l).replace(/"/g, "&quot;"))">${l}</div>`).join('')
                        : '<div class="log-item">无历史记录</div>';

                    cardEl.innerHTML = `
                        <div class="card-header">
                            <div class="card-title-box" onclick="toggleFold(${b.id})">
                                <span class="card-title">${b.name}</span>
                                <span style="font-size:12px; color:#888; margin-left:4px;">▼</span>
                            </div>
                            <div style="display: flex; gap: 6px; align-items: center;" id="action-btns-${b.id}">
                            </div>
                        </div>
                        <div class="value-box">
                            <!-- 已删除中控数据面板下方时间显示 -->
                            <div class="val-text" id="val-text-${b.id}">${b.value}</div>
                        </div>
                        <div class="fold-body">
                            <div class="setting-row" id="setting-row-${b.id}">
                                
                                <input id="input-lower-${b.id}" class="setting-input" type="number" style="width:140px" step="0.0001" value="${b.lower}">
                                <label>预警值:</label>
                                <input id="input-mid-${b.id}" class="setting-input" type="number" style="width:140px" step="0.0001" value="${b.mid_val}">
                                <label>上限:</label>
                                <input id="input-upper-${b.id}" class="setting-input" type="number" style="width:140px" step="0.0001" value="${b.upper}">
                                <button class="btn-action" style="background:#0088cc; color:white; margin-left:auto;" onclick="saveLimits(${b.id})">💾 保存</button>
                            </div>
                            <div class="log-title">📜 历史日志:</div>
                            <div class="log-list" id="log-list-${b.id}">${logsHtml}</div>
                        </div>
                    `;
                }
            }

            if (isCollapsed) {
                const cValEl = document.getElementById(`collapsed-val-${b.id}`);
                if (cValEl) {
                    cValEl.innerText = b.value;
                    cValEl.style.color = valColor;
                }
            } else {
                const actionBtns = document.getElementById(`action-btns-${b.id}`);
                if (actionBtns) {
                    if (isLoggedIn) {
                        actionBtns.innerHTML = `
                            ${b.is_alarm ? `<button class="btn-action btn-clear" onclick="postAction('clear_alarm', ${b.id})">🚨 消除报警</button>` : ''}
                            <button class="btn-action ${b.is_muted ? 'btn-alarm-off' : 'btn-alarm-on'}" onclick="postAction('toggle_mute', ${b.id})">
                                ${b.is_muted ? '🔕 报警关' : '🔔 报警开'}
                            </button>
                        `;
                    } else {
                        actionBtns.innerHTML = '';
                    }
                }

                const settingRow = document.getElementById(`setting-row-${b.id}`);
                if (settingRow) {
                    settingRow.style.display = isLoggedIn ? 'flex' : 'none';
                }

                const valEl = document.getElementById(`val-text-${b.id}`);
                if (valEl) {
                    valEl.innerText = b.value;
                    if (b.is_alarm) {
                        valEl.className = 'val-text alarm-text';
                    } else if (isWarning) {
                        valEl.className = 'val-text warning-text';
                    } else {
                        valEl.className = 'val-text';
                    }
                }

                if (isLoggedIn) {
                    const lowerInput = document.getElementById(`input-lower-${b.id}`);
                    const midInput = document.getElementById(`input-mid-${b.id}`);
                    const upperInput = document.getElementById(`input-upper-${b.id}`);

                    if (lowerInput && document.activeElement !== lowerInput) lowerInput.value = b.lower;
                    if (midInput && document.activeElement !== midInput) midInput.value = b.mid_val;
                    if (upperInput && document.activeElement !== upperInput) upperInput.value = b.upper;
                }

                const logListEl = document.getElementById(`log-list-${b.id}`);
                if (logListEl) {
                    let logsHtml = (b.logs && b.logs.length > 0)
                        ? b.logs.map(l => `<div class="log-item" onclick="openLogWindow('历史日志', JSON.stringify(l).replace(/"/g, "&quot;"))">${l}</div>`).join('')
                        : '<div class="log-item">无历史记录</div>';
                    logListEl.innerHTML = logsHtml;
                }
            }

            const diffTag = document.getElementById(`diff-tag-${b.id}`);
            if (diffTag) {
                diffTag.innerText = diff.text;
                diffTag.className = `diff-text ${diff.cls}`;
            }
        }

        async function refreshData() {
            try {
                updateLoginUI();
                updateDisplayModeUI();

                if (lastLoggedInState !== isLoggedIn) {
                    lastLoggedInState = isLoggedIn;
                    forceReRenderCards();
                }

                const res = await fetch('/api/data');
                const data = await res.json();

                const statusEl = document.getElementById('status');
                statusEl.innerText = data.time;

                const btnMonitor = document.getElementById('btn-monitor');
                if (data.monitoring) {
                    btnMonitor.className = 'btn-top active';
                    btnMonitor.innerText = '⏹ 停止监控';
                } else {
                    btnMonitor.className = 'btn-top';
                    btnMonitor.innerText = '▶ 开始监控';
                }

                const btnGrille = document.getElementById('btn-grille');
                if (data.grille_running) {
                    btnGrille.className = 'btn-top btn-grille active';
                    const m = Math.floor(data.grille_cd / 60);
                    const s = Math.floor(data.grille_cd % 60);
                    const timeStr = String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
                    btnGrille.innerText = `⏹ 停止操作 (${timeStr})`;
                } else {
                    btnGrille.className = 'btn-top btn-grille';
                    btnGrille.innerText = '▶ 开始操作';
                }

                const container = document.getElementById('cards-container');

                if (!data.boxes || data.boxes.length === 0) {
                    container.innerHTML = '<div style="text-align:center; padding: 40px; color: #666; grid-column: 1 / -1;">未添加监控选框</div>';
                    stopWebAlarmSound();
                    return;
                }

                cachedBoxes = data.boxes;
                let hasAnyWebAlarm = false;

                data.boxes.forEach(b => {
                    recordHistory(b.id, b.value);

                    if (collapsedMap[b.id] === undefined) {
                        collapsedMap[b.id] = true;
                    }

                    if (b.is_alarm && !b.is_muted) {
                        hasAnyWebAlarm = true;
                    }

                    const numVal = parseFloat(b.value);
                    const isWarning = (!b.is_alarm && !isNaN(numVal) && numVal > b.mid_val);

                    let cardEl = document.getElementById(`card-${b.id}`);
                    if (!cardEl) {
                        cardEl = document.createElement('div');
                        cardEl.id = `card-${b.id}`;
                        container.appendChild(cardEl);
                    }

                    const isCollapsed = false;
                    
                    if (b.is_alarm) {
                        cardEl.className = (displayMode === 'square') ? 'card square-card alarm' : 'card alarm';
                    } else if (isWarning) {
                        cardEl.className = (displayMode === 'square') ? 'card square-card warning' : 'card warning';
                    } else {
                        cardEl.className = (displayMode === 'square') ? 'card square-card' : 'card';
                    }

                    renderCardDOM(cardEl, b, false, isWarning, data.time);
                });

                triggerAlarmSoundLoop(hasAnyWebAlarm);

            } catch(e) {
                console.error("加载失败:", e);
            }
        }

        updateMainPanelFoldUI();
        updateDisplayModeUI();
        setInterval(refreshData, 1000);
        refreshData();
    </script>
</body>
</html>
"""

