# 中国联通 · 日常任务合集（图形版）

把联通手机营业厅的日常任务（签到、抽奖、积分）做成 Windows 图形程序：
多账号管理、可视开关、实时日志、结果导出 Excel，无需配置环境变量。

- **内核**：中国联通 v1.2.1（11 个业务模块）
- **界面**：tkinter，6 个选项卡
- **登录**：支持 `Token#AppId`，也支持**手机号 + 短信验证码**在界面内获取凭证

---

## ⚠️ 免责声明（请务必阅读）

**本项目仅供学习与技术研究使用。使用即表示你已知悉并自行承担以下全部风险：**

1. **会违反中国联通用户协议**。此类自动化操作可能触发风控，**可能导致账号被限制或封禁**。
2. **账号与数据风险自担**。作者不对账号封禁、数据泄露、设备故障、财产损失承担任何责任。
3. **源码非本项目原创**。`core/legacy.py` 取自第三方脚本库（`345yun`），其文件头自带声明：
   脚本库不审核脚本内容，风险由使用者自担；`unicom_login_server.py` 移植自开源项目
   `canxin121/china-unicom-rs` 所逆向的官方 App 接口协议。**再分发前请自行确认合规性。**
4. **部分模块会改动联通侧真实配置**。安全管家会增删账号的黑名单 / 通讯录 / 拦截规则
   （多为写死的测试数据，但请求真实提交）。
5. **抢兑模式风控特征明显**：9:58 / 17:58 并发抢券，请自行权衡风险。
6. **AI入戏会上传图片**：联通云盘的「海岛逐浪 / AI入戏」会把图片上传到联通云盘与芒果接口，
   请只放你愿意上传的图片。

**请勿用于任何商业用途或大规模滥用。作者不提供任何形式的担保。**

---

## 快速开始

### 方式一：直接运行（推荐，无需装 Python）

双击 `启动程序.bat`，或直接双击 `中国联通日常任务.exe`。

> 若仓库里没有 exe（体积大，通常不提交），用方式二。

### 方式二：源码运行

```bash
pip install requests pycryptodome openpyxl
python main.py
```

需要 **Python 3.10+**（`tkinter` 随官方安装包自带）。
首次运行会自动在 `%APPDATA%\UnicomAllIn1\` 建立配置目录，无需手工准备。

### 重新打包 exe

```bash
python -m PyInstaller --noconfirm --onefile --windowed --name UnicomDaily \
  --icon assets/app.ico --hidden-import notify --hidden-import unicom_login_server main.py
```

> ⚠️ 若不清空 `dist/` 与 `build/work/`，PyInstaller 会复用缓存，**产出与旧构建逐字节相同的文件**
> （看起来构建成功，其实没重建）。
>
> ⚠️ `--hidden-import unicom_login_server` **必须加**。协议层是用变量动态 import 的，
> PyInstaller 静态分析看不见，漏了它会导致打包版点「短信登录」只弹「协议层不可用」。

---

## 账号配置

「账号管理」页添加，每行一个，支持 `&` 或换行分隔：

| 格式 | 说明 |
|---|---|
| `token#appId` | ★ **推荐**，唯一稳定方式 |
| `token` | 仅 Token（appId 自动生成） |
| `18600000000` | 纯手机号，读本地 12h 缓存（前提：先用 Token 成功登录过） |
| `18600000000#密码` | ⚠️ 联通已要求密码登录叠加短信验证码，**纯密码无法自动完成** |

## 手机号 + 短信验证码登录

「账号管理」页点 **📱 手机号验证码登录…**：

1. 填手机号 → 点「发送验证码」
2. 若联通要求安全验证 → **自动打开浏览器**，在网页里完成腾讯验证码
3. 收到 6 位短信码 → 回到程序填入 → 点「登录」
4. 成功后点按钮把 `token#appId` 导入账号列表（自动去重）

**两处限制**：

- 腾讯验证码是网页 JS 组件，**必须在浏览器里完成**（程序内无法绘制），这是设计如此。
- 真实的短信登录流程**未在真机上端到端验证过**（需要真实手机收码）。
  程序保证的是：代码路径正确、离线单测通过、界面可用、协议层已正确打包进 exe。
  **能否真的登录成功，请自行实测。**

## 人脸图（联通云盘 · AI入戏）

「设置」页 →「联通云盘 · 海岛逐浪 / AI入戏」：

- 点「添加图片…」选 jpg/jpeg/png（可多选），运行时按随机顺序逐个尝试直到通过
- 一张都不选时，自动回落到数据目录下的 `face_images/`
- 「清空」只清清单，不删除图片文件

---

## 自检（可选）

```bash
python main.py --selftest      # 离线自检，期望 通过 13 / 失败 0
python test_gui.py             # 界面冒烟，期望 通过 14 / 失败 0
python test_sms_login.py       # 短信登录离线单测（mock 网络，不发短信），23 项
python verify_patch.py         # 内核符号契约，39 项
中国联通日常任务.exe --selftest # 交付 exe 自检，退出码 0 即通过
```

---

## 隐私与安全

**本仓库不含任何真实凭证。** 以下文件已在 `.gitignore` 中排除，且当前仓库内确认不存在：

`unicom_sms_creds.json`（登录 token/appId/cookie）、`unicom_cookie_line.txt`、
`unicom_token_cache.json`、`session_cookies*.json`、`*_state.json`、
`unicom_qr*.png`、`accounts.json`、`settings.json`、`run_*.log`

使用者首次运行时会**自行生成**这些文件到自己的 `%APPDATA%\UnicomAllIn1\`。

仓库内会扫描到几个手机号（`18600000000` / `13800000000` / `13088330789` / `13105750575`），
**均为原脚本作者的测试样例，非真实个人号码**。详见 `SECURITY-NOTICE.md`。

---

## 目录结构

```
├── main.py                  程序入口（自检 / CLI / 图形界面）
├── app/                     装配层：gui / settings / runner / sms_login / records ...
├── core/legacy.py           业务内核（中国联通 v1.2.1）
├── unicom_login_server.py   短信登录协议层（官方 App 接口，含本地网页验证码）
├── 启动程序.bat / 打包EXE.bat
├── test_*.py / verify_patch.py / probe_ttlxj.py   测试与契约校验
├── SECURITY-NOTICE.md       安全与来源说明（提交前请读）
└── .gitignore               凭证与产物排除规则
```

---

## 许可

本项目为个人学习用途整理，**不提供任何担保**。
内含的第三方脚本与逆向协议实现，其权利归原作者所有；
再分发前请自行确认合规性。
