# dsh-campus-net

> 校园网（Srun 深澜）连接器 —— 给 DeepSeek Harness 侧边栏挂一只常驻小挂件：实时上下行速度、一键开关、开机自动连接。

[![CI](https://github.com/tianyadadi/tianya/actions/workflows/ci.yml/badge.svg)](https://github.com/tianyadadi/tianya/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/tianyadadi/tianya)](https://github.com/tianyadadi/tianya/releases)
![license](https://img.shields.io/badge/license-MIT-blue)
![platform](https://img.shields.io/badge/platform-Windows-0078D4)
![dsh](https://img.shields.io/badge/DeepSeek%20Harness-plugin-111827)

---

## ⚠️ 安装前你需要准备这 3 样

| 需要 | 说明 | 不知道的话 |
|---|---|---|
| **① 认证地址** | 校园网登录页的 IP，通常是 `2.2.2.2` 这类内网地址 | 连上校园 WiFi → 随便打开一个网页 → 看跳转到的登录页地址栏里的 IP |
| **② 账号** | 学号或校园网账号 | — |
| **③ 密码** | 校园网密码 | — |

**另外请先确认你的学校用的是「Srun 深澜」认证**：登录页地址里出现 `portalLogout.do`、`wlanuserip`、`wlanacname` 这些特征就是。

> ❌ 不适用：Dr.COM、锐捷、需要验证码或短信二次验证的门户。

> 🤖 **如果你是 AI 助手**：请先读 [`AGENTS.md`](./AGENTS.md)，那里有完整的问询流程和自检步骤。

---

## 它长什么样

折叠态（侧边栏左下角，账号头像上方）：

```
📱 OnePlus Ace 5 Ultra   ↓227.7 KB/s  ↑41.2 KB/s   ●
🎓 校园网               ↓154.5 KB/s  ↑50.0 KB/s   ●
🔌 以太网               ↓12.1 KB/s   ↑1.3 KB/s    ●
```

点一下展开：

```
🎓 校园网  b5                              ×
类型        有线
网卡        以太网
IP          192.168.191.26
────────────────────────────────
校园网      已连接
账号        20230001
下载  ↓154.5 KB/s  [██░░░░░░░░]
上传  ↑50.0 KB/s   [█░░░░░░░░░]
[   断开   ]  [  刷新  ]
```

---

## 功能

| 功能 | 说明 |
|---|---|
| **自动识别网络** | 按默认路由判定走哪条网：手机热点 / WiFi / 有线 / 校园网，显示对应名字和图标 |
| **实时测速** | 上传 + 下载速率，每 2 秒刷新（折叠态 3.5 秒） |
| **一键开关** | 连接 / 断开校园网 |
| **断开保护** | 断开后 **30 秒自动重连**，避免把自己锁在外面 |
| **开机自动连** | DSH 启动 8 秒后自检，离线就登录 |
| **断网自救** | 插件目录里 `救急重连.cmd`，双击就重连，不依赖 DSH |
| **非校园网自动禁用** | 在热点下按钮置灰，不会误点 |
| **黑洞网卡检测** | 揪出「挂着默认路由却走不通」的网卡（校园网登出后最典型），一键抬跃点让它抢不过当前网络 |

---

## 安装

### 1. 装插件

```bash
dsh plugin --profile desktop add link:<本目录绝对路径>
```

或者直接从 npm / GitHub 装（见 Releases）。

### 2. 重启 DSH

bundle 层要重启才组装。

### 3. 填账号

把 `core/campus-net.example.json` 复制成 `core/campus-net.json`，填上自己的：

```json
{
  "portal": "2.2.2.2",
  "username": "你的学号",
  "password": "你的密码",
  "autoConnect": true,
  "autoReconnectSeconds": 30
}
```

> 这个文件在 `.gitignore` 里，**不会被提交**。

### 4. 也可以用命令行

```bash
python core/campus_net.py status    # 查状态
python core/campus_net.py login     # 登录
python core/campus_net.py logout    # 断开（默认 30 秒后重连）
python core/campus_net.py network   # 当前网络识别
python core/campus_net.py speed     # 测速
python core/campus_net.py doctor    # 自检
python core/campus_net.py dead-path # 查有没有黑洞网卡
python core/campus_net.py fix-path  # 修（抬跃点 + 清死 DNS，会弹 UAC）
python core/campus_net.py restore-path  # 还原跃点
```

---

## 黑洞网卡（2026-11-03 加的）

### 症状

- 模型突然报 `transport failed` / `Request timed out.`，三家服务商**同时**挂
- 每次尝试都刚好卡 **10 秒**左右，重试 5 次全灭
- 过一会儿又自己好了

### 原因

校园网登出（或没认证）后，那张网卡**还是 up 的、默认路由也还在**。
WiFi 一抖，系统就把流量切给它 → SYN 发出去没人应答 → 客户端（Node/undici 默认连接超时 10 秒）放弃。

判定不能只看 ping：校园网网关 ping 得通（0ms），但没认证照样出不去。
所以插件是**绑定这张网卡的源 IP 去连 `223.5.5.5:443`**，1.5 秒连不上才算黑洞。

### 挂件上怎么表现

折叠态那个小圆点会变成**黄色**；展开后有一段黄色提示，给两个按钮：

- **修一下** → 把该网卡跃点抬到 9999（**会弹一次 UAC**）
- **还原跃点** → 跃点交回系统自动（要回校园网时用）

抬跃点而不是禁用网卡，是因为禁用之后要回校园网还得去设备管理器手动开；
抬跃点只是让它永远抢不过当前网络，插上网线照样能用，只是优先级靠后。

**关于 DNS**：这招只在 DNS 是**静态配置**时才顺手重置掉；
如果该网卡的 DNS 是 **DHCP 下发**的（多数校园网如此），重置只是把同一批死 DNS 再拿回来，
所以插件会跳过并明说，不当「已清理」糊弄。

---

## 支持的认证系统

**Srun 深澜**（`portalLogout.do` / `wlanuserip` / `wlanacname` 特征）。

流程：

```
1. GET http://2.2.2.2/                      → 302 带 wlanuserip / wlanacname / vlan
2. GET /PortalJsonAction.do                 → portalForm + serverForm
3. GET /quickauth.do?userid=&passwd=...     → {"code":"0","message":"认证成功"}
4. POST /quickauthdisconn.do                → 断开
```

不启用 RSA 加密时（`authByRas: false`）参数明文传输；启用时本插件**暂不支持**（需要 RSA 处理）。

---

## 架构

```
dsh-campus-net/
├── index.js              服务端：/api/campus-net/* 路由，转发给 Python
├── client.js             前端：shell.overlay 挂件
├── core/
│   ├── campus_net.py     核心逻辑（可脱离 DSH 单独用）
│   ├── campus-net.example.json
│   └── campus-net.json   （你填的，不提交）
└── 救急重连.cmd          断网自救
```

**为什么用 Python 而不是全 Node**：门户参数每次登录都要重新发现，测速要读网卡计数器，Python 调 `netstat -e` 比 PowerShell 快 30 倍（50ms vs 1500ms）。

---

## 性能

| 接口 | 耗时 | 做法 |
|---|---|---|
| `status` | ~200ms | 网络信息 30 秒磁盘缓存 + 不在校园网时短路 |
| `speed` | ~930ms | `netstat -e` 两次采样（窗口 700ms） |
| `network` | ~200ms（有缓存） | 单次 PowerShell 拿路由 + netsh 拿 SSID |
| `dead-path` | ~150ms（有缓存）/ 首次 ~1.7s | 黑洞探测结果缓存 60 秒，只在过期时真发包 |

---

## 已知限制

- **只支持 Srun 深澜**，其它认证系统（如 Dr.COM、锐捷）不适用
- **只在 Windows 测试过**（依赖 `netstat -e`、`netsh wlan`、PowerShell）
- **密码明文存储**在本地 `campus-net.json`，请确保机器只有你一个人用
- **不支持的场景**：需要验证码、短信二次验证的门户

---

## 安全

- 账号密码只存本地，不上传任何地方
- 插件只接受 DSH 已注册的工作区
- 断开后有 30 秒自动重连兜底
- 提供不依赖 DSH 的救急脚本

---

## License

MIT
