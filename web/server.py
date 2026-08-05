import sys, os, json, time, re, threading, ctypes, socket, urllib.request
from io import BytesIO
from datetime import datetime
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
import mss
import numpy as np
import cv2

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

        .header { display: flex; flex-direction: column; padding: 10px 14px; background: #1a1a26; border-radius: 10px; margin-bottom: 12px; border: 1px solid rgba(255,255,255,0.1); gap: 8px; }
        .header-top-row { display: flex; justify-content: space-between; align-items: center; width: 100%; }
        .title { font-size: 15px; font-weight: bold; color: #00ff8c; }
        .status { font-size: 11px; color: #aaa; font-weight: bold; }

        .header-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; width: 100%; }
        .btn-top { background: #2e9a58; color: #fff; border: none; border-radius: 6px; padding: 6px 10px; font-size: 12px; font-weight: bold; cursor: pointer; transition: background 0.2s; }
        .btn-top:active { opacity: 0.8; }
        .btn-top.active { background: #b03a3a; }
        .btn-top.btn-grille { background: #0088cc; }
        .btn-top.btn-grille.active { background: #cc3333; }
        .btn-sound { background: rgba(255,255,255,0.15); color: #00ff8c; border: 1px solid rgba(255,255,255,0.2); border-radius: 6px; padding: 6px 8px; font-size: 12px; font-weight: bold; cursor: pointer; }

        .btn-fold-tool { background: rgba(255,255,255,0.1); color: #00ff8c; border: 1px solid rgba(0,255,140,0.3); border-radius: 6px; padding: 6px 8px; font-size: 12px; font-weight: bold; cursor: pointer; }
        .btn-fold-tool:active { background: rgba(0,255,140,0.2); }

        .login-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 6px; width: 100%; font-size: 12px; }

        /* 卡片容器与视图模式 */
        #cards-container.list-view { display: flex; flex-direction: column; gap: 10px; }
        
        #cards-container.grid-view { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 10px; }
        #cards-container.grid-view .card { margin-bottom: 0; height: 130px; display: flex; flex-direction: column; justify-content: space-between; padding: 10px; text-align: center; }
        #cards-container.grid-view .card .val-text { font-size: 26px; }
        #cards-container.grid-view .card .fold-body { display: none !important; }

        .card { background: #1a1a26; border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; border: 1px solid rgba(255,255,255,0.1); transition: all 0.2s; user-select: none; }
        .card.dragging { opacity: 0.4; border: 2px dashed #00ff8c; }
        .card[draggable="true"] { cursor: grab; }
        .card[draggable="true"]:active { cursor: grabbing; }

        .card.alarm { border: 2px solid #ff4d4d; background: rgba(255, 77, 77, 0.08); animation: blink 1s infinite alternate; }
        @keyframes blink { from { box-shadow: 0 0 5px rgba(255,77,77,0.3); } to { box-shadow: 0 0 15px rgba(255,77,77,0.8); } }

        .card.warning { border: 2px solid #ffaa00; background: rgba(255, 170, 0, 0.08); }

        .card-header { display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: #888; font-weight: bold; }
        .card-title-box { display: flex; align-items: center; gap: 8px; cursor: pointer; flex-grow: 1; }
        .card-title { color: #ffffff; font-size: 15px; font-weight: bold; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

        .btn-action { color: #fff; border-radius: 6px; padding: 4px 8px; font-size: 11px; font-weight: bold; cursor: pointer; border: none; }
        .btn-action:active { opacity: 0.8; }
        .btn-clear { background: #ff4d4d; color: white; }

        .btn-alarm-on { background: #2e9a58; color: #ffffff; border: 1px solid #3fb950; }
        .btn-alarm-off { background: #4a4d52; color: #cccccc; border: 1px solid #666666; }

        .value-box { text-align: center; margin: 8px 0; }
        .val-text { font-size: 32px; font-weight: bold; color: #00ff8c; font-family: monospace; }
        .val-text.alarm-text { color: #ff4d4d; }
        .val-text.warning-text { color: #ffaa00; }

        .fold-body { margin-top: 8px; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 8px; }

        .setting-row { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; font-size: 11px; flex-wrap: wrap; }
        .setting-row label { color: #ffaa00; font-weight: bold; }
        .setting-input { background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; color: #00ff8c; font-weight: bold; padding: 4px 2px; width: 50px; text-align: center; font-size: 11px; }

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
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <!-- 统一顶部栏：需求四 添加收起展开图标 -->
            <div class="header-top-row">
                <div style="display: flex; align-items: center; gap: 6px;">
                    <div class="title">📱 中控数据面板</div>
                    <span id="header-fold-btn" onclick="toggleHeaderFold()" style="cursor: pointer; font-size: 14px; color: #00ff8c;" title="收起/展开控制区">🔼</span>
                </div>
                <div id="status" class="status">初始化...</div>
            </div>
            <div id="header-actions" class="header-actions">
                <button id="btn-toggle-all" class="btn-fold-tool" onclick="toggleCollapseAll()">📂 展开</button>
                <button id="btn-layout" class="btn-fold-tool" onclick="toggleLayoutView()">🔲 方块视图</button>

                <!-- 登录按钮 -->
                <div id="login-box" style="display: inline-flex; align-items: center; gap: 4px;">
                    <button class="btn-fold-tool" style="background:#0088cc; color:white; border:none;" onclick="openLoginModal()">🔐 登录</button>
                </div>
                <div id="user-box" style="display: none; align-items: center; gap: 4px;">
                    <span id="current-username" style="color:#00ff8c; font-size:12px; font-weight:bold;">👤 已登录</span>
                    <button class="btn-sound" style="background:#e65100; color:white; border:none;" onclick="openUserMgmtModal()">⚙️ 用户管理</button>
                    <button class="btn-sound" style="background:#555; color:white; border:none;" onclick="handleLogout()">🚪 退出</button>
                </div>

                <button id="btn-sound" class="btn-sound" onclick="toggleWebSound()">🔊 声音</button>
                <button id="btn-monitor" class="btn-top" onclick="postAction('toggle_monitor', -1)">▶ 开始监控</button>
                <button id="btn-grille" class="btn-top btn-grille" onclick="postAction('toggle_grille', -1)">▶ 开始操作</button>
            </div>
        </div>

        <div id="cards-container" class="list-view"></div>
    </div>

    <!-- 登录弹窗 -->
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
            
            <div style="margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px dashed rgba(255,255,255,0.1);">
                <div style="font-size:12px; color:#aaa; margin-bottom:6px; font-weight:bold;">🔑 修改当前密码 (<span id="modal-curr-user" style="color:#00ff8c;"></span>)</div>
                <div class="setting-row">
                    <input type="password" id="old-pass" placeholder="旧密码" class="setting-input" style="width:85px;">
                    <input type="password" id="new-pass" placeholder="新密码" class="setting-input" style="width:85px;">
                    <button class="btn-action" style="background:#0088cc; color:white; margin-left: auto;" onclick="handleChangePassword()">修改密码</button>
                </div>
            </div>

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
        let isAllCollapsed = true;
        let isLoggedIn = localStorage.getItem('isLoggedIn') === 'true';
        let currentUser = localStorage.getItem('currentUser') || '';
        let lastLoggedInState = null;
        let webSoundEnabled = true;
        let audioCtx = null;
        let alarmTimer = null;
        let cachedBoxes = [];
        let isGridView = localStorage.getItem('isGridView') === 'true';
        let customBoxOrder = JSON.parse(localStorage.getItem('customBoxOrder') || '[]');
        let draggedItem = null;
        let isHeaderFolded = false;

        function toggleHeaderFold() {
            isHeaderFolded = !isHeaderFolded;
            const actionsEl = document.getElementById('header-actions');
            const foldBtn = document.getElementById('header-fold-btn');
            if (isHeaderFolded) {
                if (actionsEl) actionsEl.style.display = 'none';
                if (foldBtn) foldBtn.innerText = '🔽';
            } else {
                if (actionsEl) actionsEl.style.display = 'flex';
                if (foldBtn) foldBtn.innerText = '🔼';
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

        function toggleLayoutView() {
            isGridView = !isGridView;
            localStorage.setItem('isGridView', isGridView);
            applyLayoutView();
        }

        function applyLayoutView() {
            const container = document.getElementById('cards-container');
            const btnLayout = document.getElementById('btn-layout');
            if (isGridView) {
                container.className = 'grid-view';
                btnLayout.innerText = '☰ 长条视图';
            } else {
                container.className = 'list-view';
                btnLayout.innerText = '🔲 方块视图';
            }
            refreshData();
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

        function toggleCollapseAll() {
            isAllCollapsed = !isAllCollapsed;
            cachedBoxes.forEach(b => {
                collapsedMap[b.id] = isAllCollapsed;
            });
            const btn = document.getElementById('btn-toggle-all');
            if (btn) {
                btn.innerText = isAllCollapsed ? "📂 展开" : "📁 收起";
            }
            refreshData();
        }

        function toggleWebSound() {
            webSoundEnabled = !webSoundEnabled;
            const btn = document.getElementById('btn-sound');
            if (webSoundEnabled) {
                btn.innerText = "🔊 声音";
                btn.style.color = "#00ff8c";
            } else {
                btn.innerText = "🔇 静音";
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

        function formatTwoHourCompare(b, currentTimeStr) {
            const currVal = parseFloat(b.value);
            const dp = b.decimal_places !== undefined ? b.decimal_places : 2;
            
            if (isNaN(currVal) || !b.logs || b.logs.length === 0 || !currentTimeStr) {
                return '<span style="font-size:11px; color:#666;">(--)</span>';
            }

            function timeToSec(tStr) {
                const p = tStr.split(':').map(Number);
                return (p[0] || 0) * 3600 + (p[1] || 0) * 60 + (p[2] || 0);
            }

            const nowSec = timeToSec(currentTimeStr);
            let bestVal = null;
            let minErr = Infinity;

            for (let log of b.logs) {
                const m = log.match(/\[(\d{2}:\d{2}:\d{2})\]\s*(-?\d+(?:\.\d+)?)/);
                if (m) {
                    const logSec = timeToSec(m[1]);
                    const logVal = parseFloat(m[2]);
                    if (isNaN(logVal)) continue;

                    let elapsed = nowSec - logSec;
                    if (elapsed < 0) elapsed += 86400;

                    const err = Math.abs(elapsed - 7200);
                    if (err < minErr && elapsed >= 900) {
                        minErr = err;
                        bestVal = logVal;
                    }
                }
            }

            if (bestVal === null) {
                return '<span style="font-size:11px; color:#666;">(--)</span>';
            }

            const diff = currVal - bestVal;
            let diffStr = (diff >= 0 ? '+' : '') + diff.toFixed(dp);
            let color = '#888';
            let arrow = '→';

            if (diff > 0) {
                color = '#ff4d4d';
                arrow = '↑';
            } else if (diff < 0) {
                color = '#00ff8c';
                arrow = '↓';
            }

            return `<span style="font-size:11px; color:#aaa;" title="历史数值对比 (${bestVal.toFixed(dp)})">` +
                   `${bestVal.toFixed(dp)} <span style="color:${color}; font-weight:bold;">(${arrow}${diffStr})</span>` +
                   `</span>`;
        }

        function attachDragEvents(cardEl, boxId) {
            if (!isLoggedIn) {
                cardEl.removeAttribute('draggable');
                cardEl.ondragstart = null;
                cardEl.ondragover = null;
                cardEl.ondrop = null;
                cardEl.ondragend = null;
                return;
            }

            cardEl.setAttribute('draggable', 'true');

            cardEl.ondragstart = (e) => {
                draggedItem = cardEl;
                cardEl.classList.add('dragging');
                e.dataTransfer.effectAllowed = 'move';
            };

            cardEl.ondragover = (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
            };

            cardEl.ondrop = (e) => {
                e.preventDefault();
                if (draggedItem && draggedItem !== cardEl) {
                    const container = document.getElementById('cards-container');
                    const children = Array.from(container.children);
                    const draggedIdx = children.indexOf(draggedItem);
                    const targetIdx = children.indexOf(cardEl);

                    if (draggedIdx < targetIdx) {
                        container.insertBefore(draggedItem, cardEl.nextSibling);
                    } else {
                        container.insertBefore(draggedItem, cardEl);
                    }

                    const newOrder = Array.from(container.children).map(el => parseInt(el.id.replace('card-', '')));
                    customBoxOrder = newOrder;
                    localStorage.setItem('customBoxOrder', JSON.stringify(customBoxOrder));
                }
            };

            cardEl.ondragend = () => {
                if (draggedItem) {
                    draggedItem.classList.remove('dragging');
                    draggedItem = null;
                }
            };
        }

        function renderCardDOM(cardEl, b, isCollapsed, isWarning, currentTimeStr) {
            const expectedState = isGridView ? 'grid' : String(isCollapsed);
            const currentFoldState = cardEl.getAttribute('data-collapsed');
            const stateChanged = (currentFoldState !== expectedState);

            let valColor = '#00ff8c';
            if (b.is_alarm) {
                valColor = '#ff4d4d';
            } else if (isWarning) {
                valColor = '#ffaa00';
            }

            const compareHtml = formatTwoHourCompare(b, currentTimeStr);
            attachDragEvents(cardEl, b.id);

            if (stateChanged) {
                cardEl.setAttribute('data-collapsed', expectedState);
                
                if (isGridView) {
                    cardEl.innerHTML = `
                        <div class="card-header" onclick="toggleFold(${b.id})" style="cursor:pointer; justify-content:center; width:100%;">
                            <span class="card-title" style="text-align:center; width:100%;">${b.name}</span>
                        </div>
                        <div class="value-box" style="flex:1; display:flex; align-items:center; justify-content:center; margin:0;">
                            <div class="val-text" id="grid-val-${b.id}" style="font-size:26px; color:${valColor};">${b.value}</div>
                        </div>
                        <div style="text-align:center; font-size:11px;" id="grid-diff-${b.id}">
                            ${compareHtml}
                        </div>
                    `;
                    return;
                } else if (isCollapsed) {
                    cardEl.innerHTML = `
                        <div class="card-header" onclick="toggleFold(${b.id})" style="cursor:pointer; padding: 2px 0;">
                            <span class="card-title">${b.name}</span>
                            <div style="display: flex; align-items: center; gap: 4px;">
                                <span id="collapsed-diff-${b.id}">${compareHtml}</span>
                                <span id="collapsed-val-${b.id}" style="font-size: 15px; font-weight: bold; font-family: monospace; color: ${valColor};">${b.value}</span>
                                <span style="font-size:12px; color:#888;">▶</span>
                            </div>
                        </div>
                    `;
                    return;
                } else {
                    let logsHtml = (b.logs && b.logs.length > 0)
                        ? b.logs.map(l => `<div class="log-item">${l}</div>`).join('')
                        : '<div class="log-item">无历史记录</div>';

                    cardEl.innerHTML = `
                        <div class="card-header">
                            <div class="card-title-box" onclick="toggleFold(${b.id})">
                                <span class="card-title">${b.name}</span>
                                <span style="font-size:12px; color:#888;">▼</span>
                            </div>
                            <div style="display: flex; gap: 6px; align-items: center;" id="action-btns-${b.id}">
                            </div>
                        </div>
                        <div class="value-box">
                            <div class="val-text" id="val-text-${b.id}">${b.value}</div>
                        </div>
                        <div class="fold-body">
                            <div class="setting-row" id="setting-row-${b.id}">
                                <label>下限:</label>
                                <input id="input-lower-${b.id}" class="setting-input" type="number" step="0.1" value="${b.lower}">
                                <label>预警值:</label>
                                <input id="input-mid-${b.id}" class="setting-input" type="number" step="0.1" value="${b.mid_val}">
                                <label>上限:</label>
                                <input id="input-upper-${b.id}" class="setting-input" type="number" step="0.1" value="${b.upper}">
                                <button class="btn-action" style="background:#0088cc; color:white; margin-left:auto;" onclick="saveLimits(${b.id})">💾 保存</button>
                            </div>
                            <div class="log-title">📜 历史日志:</div>
                            <div class="log-list" id="log-list-${b.id}">${logsHtml}</div>
                        </div>
                    `;
                }
            }

            if (isGridView) {
                const gValEl = document.getElementById(`grid-val-${b.id}`);
                if (gValEl) {
                    gValEl.innerText = b.value;
                    if (b.is_alarm) {
                        gValEl.className = 'val-text alarm-text';
                    } else if (isWarning) {
                        gValEl.className = 'val-text warning-text';
                    } else {
                        gValEl.className = 'val-text';
                    }
                }
                const gDiffEl = document.getElementById(`grid-diff-${b.id}`);
                if (gDiffEl) {
                    gDiffEl.innerHTML = compareHtml;
                }
            } else if (isCollapsed) {
                const cValEl = document.getElementById(`collapsed-val-${b.id}`);
                if (cValEl) {
                    cValEl.innerText = b.value;
                    cValEl.style.color = valColor;
                }
                const cDiffEl = document.getElementById(`collapsed-diff-${b.id}`);
                if (cDiffEl) {
                    cDiffEl.innerHTML = compareHtml;
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
                        ? b.logs.map(l => `<div class="log-item">${l}</div>`).join('')
                        : '<div class="log-item">无历史记录</div>';
                    logListEl.innerHTML = logsHtml;
                }
            }
        }

        async function refreshData() {
            try {
                updateLoginUI();

                if (lastLoggedInState !== isLoggedIn) {
                    lastLoggedInState = isLoggedIn;
                    forceReRenderCards();
                }

                const res = await fetch('/api/data');
                const data = await res.json();

                const statusEl = document.getElementById('status');
                if (statusEl) statusEl.innerText = data.time;

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
                    container.innerHTML = '<div style="text-align:center; padding: 40px; color: #666;">未添加监控选框</div>';
                    stopWebAlarmSound();
                    return;
                }

                cachedBoxes = data.boxes;
                
                let sortedBoxes = [...data.boxes];
                if (customBoxOrder && customBoxOrder.length > 0) {
                    sortedBoxes.sort((a, b) => {
                        let idxA = customBoxOrder.indexOf(a.id);
                        let idxB = customBoxOrder.indexOf(b.id);
                        if (idxA === -1) idxA = 999;
                        if (idxB === -1) idxB = 999;
                        return idxA - idxB;
                    });
                }

                let hasAnyWebAlarm = false;

                sortedBoxes.forEach(b => {
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

                    const isCollapsed = collapsedMap[b.id];
                    
                    if (b.is_alarm) {
                        cardEl.className = 'card alarm';
                    } else if (isWarning) {
                        cardEl.className = 'card warning';
                    } else {
                        cardEl.className = 'card';
                    }

                    renderCardDOM(cardEl, b, isCollapsed, isWarning, data.time);
                });

                triggerAlarmSoundLoop(hasAnyWebAlarm);

            } catch(e) {
                console.error("加载失败:", e);
            }
        }

        applyLayoutView();
        setInterval(refreshData, 1000);
        refreshData();
    </script>
</body>
</html>
"""

class WebServerThread(QThread):
    action_requested = Signal(str, int, dict)

    def __init__(self, main_panel, host='0.0.0.0', port=5000, parent=None):
        super().__init__(parent)
        self.main_panel = main_panel
        self.host = host
        self.port = port
        self.server = None

    def run(self):
        if not FLASK_AVAILABLE:
            return

        app = Flask(__name__)

        @app.route('/')
        def index():
            return render_template_string(MOBILE_HTML_TEMPLATE)

        @app.route('/favicon.ico')
        def favicon():
            script_dir = os.path.dirname(os.path.abspath(__file__))
            return send_from_directory(script_dir, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

        @app.route('/api/login', methods=['POST'])
        def api_login():
            data = request.get_json() or {}
            u = data.get('username', '').strip()
            p = data.get('password', '').strip()
            users = self.main_panel.users
            if u in users and users[u] == p:
                return jsonify({'success': True, 'username': u})
            return jsonify({'success': False, 'message': '账号或密码错误！'})

        @app.route('/api/users/list', methods=['GET'])
        def api_users_list():
            return jsonify({'users': list(self.main_panel.users.keys())})

        @app.route('/api/users/add', methods=['POST'])
        def api_users_add():
            data = request.get_json() or {}
            u = data.get('username', '').strip()
            p = data.get('password', '').strip()
            if not u or not p:
                return jsonify({'success': False, 'message': '账号或密码不能为空！'})
            if u in self.main_panel.users:
                return jsonify({'success': False, 'message': '该账号已存在！'})
            self.main_panel.users[u] = p
            self.main_panel.save_users()
            return jsonify({'success': True, 'message': '新增用户成功！'})

        @app.route('/api/users/delete', methods=['POST'])
        def api_users_delete():
            data = request.get_json() or {}
            u = data.get('username', '').strip()
            if u not in self.main_panel.users:
                return jsonify({'success': False, 'message': '用户不存在！'})
            if u == 'admin':
                return jsonify({'success': False, 'message': '默认管理员 admin 不可删除！'})
            del self.main_panel.users[u]
            self.main_panel.save_users()
            return jsonify({'success': True, 'message': '用户已删除！'})

        @app.route('/api/users/change_password', methods=['POST'])
        def api_users_change_password():
            data = request.get_json() or {}
            u = data.get('username', '').strip()
            old_p = data.get('old_password', '').strip()
            new_p = data.get('new_password', '').strip()
            if u not in self.main_panel.users:
                return jsonify({'success': False, 'message': '用户不存在！'})
            if self.main_panel.users[u] != old_p:
                return jsonify({'success': False, 'message': '原密码错误！'})
            if not new_p:
                return jsonify({'success': False, 'message': '新密码不能为空！'})
            self.main_panel.users[u] = new_p
            self.main_panel.save_users()
            return jsonify({'success': True, 'message': '密码修改成功！'})

        @app.route('/api/data')
        def get_data():
            boxes_data = []
            for b in self.main_panel.boxes:
                logs = []
                for i in range(min(30, b.list_widget.count())):
                    logs.append(b.list_widget.item(i).text())

                boxes_data.append({
                    'id': b.box_id,
                    'name': b.name,
                    'value': b.lbl_result.text(),
                    'lower': b.lower,
                    'mid_val': getattr(b, 'mid_val', 50.0),
                    'upper': b.upper,
                    'decimal_places': getattr(b, 'decimal_places', 2),
                    'is_alarm': b.is_alarm,
                    'is_muted': b.is_muted,
                    'logs': logs
                })

            grille_running = bool(self.main_panel.grille_thread and self.main_panel.grille_thread.isRunning())

            return jsonify({
                'monitoring': self.main_panel.monitoring,
                'monitor_cd': getattr(self.main_panel, 'curr_monitor_cd', 0.0),
                'grille_running': grille_running,
                'grille_cd': getattr(self.main_panel, 'curr_grille_cd', 0.0),
                'time': datetime.now().strftime("%H:%M:%S"),
                'boxes': boxes_data
            })

        @app.route('/api/action', methods=['POST'])
        def handle_action():
            data = request.get_json() or {}
            action = data.get('action')
            box_id = data.get('id')
            payload = data.get('data', {})

            if action:
                self.action_requested.emit(action, box_id if box_id is not None else -1, payload)
                return jsonify({'status': 'ok'})
            return jsonify({'status': 'error', 'message': 'Invalid parameters'}), 400

        from werkzeug.serving import make_server
        try:
            self.server = make_server(self.host, self.port, app, threaded=True)
            self.server.serve_forever()
        except Exception as e:
            print("Web Server Error:", e)

    def stop(self):
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass



