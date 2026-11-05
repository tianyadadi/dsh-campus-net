# dsh-campus-net

> 校园网（Srun 深澜）连接器 —— 给 DeepSeek Harness 侧边栏挂一只常驻小挂件：实时上下行速度、一键开关、开机自动连接。

**Srun campus network (深澜) connector for DeepSeek Harness** — a persistent sidebar widget with real-time upload/download speed, one-click login/logout, auto-connect on boot, black-hole NIC detection, traffic stats, multi-account support and automatic retry outside allowed hours.

`deepseek-harness` · `dsh-plugin` · `campus-network` · `srun` · `network-authentication` · `wifi` · `python` · `windows` · `cli`

[![CI](https://github.com/tianyadadi/dsh-campus-net/actions/workflows/ci.yml/badge.svg)](https://github.com/tianyadadi/dsh-campus-net/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/tianyadadi/dsh-campus-net)](https://github.com/tianyadadi/dsh-campus-net/releases)
[![npm](https://img.shields.io/npm/v/dsh-campus-net)](https://www.npmjs.com/package/dsh-campus-net)
![license](https://img.shields.io/badge/license-MIT-blue)
![platform](https://img.shields.io/badge/platform-Windows-0078D4)
![dsh](https://img.shields.io/badge/DeepSeek%20Harness-plugin-111827)

## 目录

- [安装前你需要准备这 3 样](#安装前你需要准备这-3-样)
- [它长什么样](#它长什么样)
- [功能](#功能)
- [安装](#安装)
- [命令行](#命令行)
- [流量统计](#流量统计)
- [多账号](#多账号)
- [非上网时段自动重试](#非上网时段自动重试)
- [黑洞网卡](#黑洞网卡)
- [支持的认证系统](#支持的认证系统)
- [架构](#架构)
- [性能](#性能)
- [已知限制](#已知限制)
- [安全](#安全)

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

![折叠态](docs/widget.png)

```
📱 OnePlus Ace 5 Ultra   ↓227.7 KB/s  ↑41.2 KB/s   ●
🎓 校园网               ↓154.5 KB/s  ↑50.0 KB/s   ●
🔌 以太网               ↓12.1 KB/s   ↑1.3 KB/s    ●
```

点一下展开：

```
🎓 校园网  b7                              ×
类型        有线
网卡        以太网
IP          192.168.191.26
────────────────────────────────
校园网      已连接
账号        20230001
已连        2 小时 13 分
今日        ↓1.24 GB  ↑356.8 MB
本次        ↓412.3 MB  ↑88.1 MB
开机以来    ↓6.81 GB  ↑1.24 GB
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
| **流量统计** | 今日 / 本次登录 / 开机以来，上下行分开算（`netstat -e` 计数，30 秒节流） |
| **在线时长** | 显示本次已连多久，断开自动清零 |
| **多账号** | 宿舍 / 实验室多个号，面板下拉切换 |
| **非上网时段自动重试** | 学校说「不在上网时段」时每 10 分钟自动试一次，连上就停 |

---

## 安装

### 1. 装插件

**从 npm 安装（推荐）**：

```bash
dsh plugin --profile desktop add dsh-campus-net
```

**从 GitHub 安装**：

```bash
dsh plugin --profile desktop add github:tianyadadi/dsh-campus-net
```

**本地开发（改了代码要热更）**：

```bash
dsh plugin --profile desktop add link:<本目录绝对路径>
```

### 2. 重启 DSH

bundle 层要重启才组装。

### 3. 验证是否装好

重启后看两点：

1. **侧边栏左下角**（账号头像上方）出现挂件
2. 命令行自检通过：

```bash
python core/campus_net.py doctor
```

没出现的话，先看 DSH 日志里有没有 `dsh-campus-net` 的加载错误。

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

## 命令行

```bash
python core/campus_net.py status    # 查状态
python core/campus_net.py login     # 登录
python core/campus_net.py logout    # 断开（默认 30 秒后重连）
python core/campus_net.py network   # 当前网络识别
python core/campus_net.py speed     # 测速
python core/campus_net.py doctor    # 自检
python core/campus_net.py dead-path # 查有没有黑洞网卡
python core/campus_net.py fix-path  # 修（抬跃点；DNS 是静态时才重置，会弹 UAC）
python core/campus_net.py restore-path  # 还原跃点
python core/campus_net.py traffic   # 流量（今日 / 本次 / 开机以来）
python core/campus_net.py accounts  # 列出所有账号
python core/campus_net.py switch-account 实验室   # 切号（也可写序号）
```

---

## 流量统计（2026-11-03 加的）

数据源是 `netstat -e` 的**全机聚合累计值**（自开机起），所以：

- 「今日」「本次」「开机以来」都是靠前后两次采样做差；
- 采样有 **30 秒节流**，面板每 3 秒轮询不会真的每次都去读；
- 计数变小 = 机器重启过，此时把当前值当增量，不会算出负数或天文数字；
- 跨天会自动把昨天归档，只保留最近 7 天；
- **第一次运行**只建立基线（今日从 0 起），不会把「开机以来」误算成「今天」。

⚠️ 因为它读的是全机计数，**所有网卡的流量合在一起**，不区分走的是哪张卡。

---

## 多账号（2026-11-03 加的）

`core/campus-net.json` 支持两种写法，**老配置不用改**：

```json
{ "username": "学号", "password": "密码" }
```

```json
{ "accounts": [
    { "name": "宿舍",   "username": "111", "password": "p1" },
    { "name": "实验室", "username": "222", "password": "p2" }
  ],
  "current": 0 }
```

- 只有一个号时面板直接显示账号；多于一个会变成下拉框，选了立刻生效
- 切号会把选中账号**镜像回 `username`/`password`**，
  所以 `救急重连.cmd` 之类只认老字段的调用方照样能用
- 在线时切号**不会踢掉当前会话**，只影响下次登录

---

## 非上网时段自动重试（2026-11-03 加的）

学校在非上网时段会返回「不允许上网时间段，请在上网时段认证」。
以前遇到就停在那儿，得自己想起来再点一次；现在：

- 识别到这类错误就**每 10 分钟自动试一次**，最多 60 次（≈10 小时）
- 一旦连上就停；手动登录成功也会立刻停掉排队
- 面板上显示「⏳ 现在是非上网时段，8 分钟后自动重试（第 3/60 次）」
- 判断逻辑在 `retry.js`，单独抽出来是为了能单测（测试里用 50ms 间隔跑）

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
├── retry.js              非上网时段的自动重试控制器（可单测）
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
| `status` | ~200ms | 网络信息 30 秒磁盘缓存 + 不在校园网时短路 + 流量 30 秒节流 |
| `speed` | ~930ms | `netstat -e` 两次采样（窗口 700ms） |
| `network` | ~200ms（有缓存） | 单次 PowerShell 拿路由 + netsh 拿 SSID |
| `dead-path` | ~150ms（有缓存）/ 首次 ~1.7s | 黑洞探测结果缓存 60 秒，只在过期时真发包 |
| `traffic` | ~65ms（过期时）/ 0ms（缓存） | `netstat -e` 单次读取 |

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
