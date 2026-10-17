# 安全与来源说明（上传 Git 前请阅读）

> 本文件面向**仓库维护者**。若你只下载运行，请看 `README.md`。
> 最后更新：2026-10-17

## 一、本仓库不含任何真实凭证

已系统排查并确认**不包含**以下内容（`.gitignore` 已同步排除）：

| 类别 | 具体文件 | 状态 |
|---|---|---|
| 短信登录凭证 | `unicom_sms_creds.json`（token_online / app_id / cookie） | 已排除 |
| 登录配置行 | `unicom_cookie_line.txt`（`Token#AppId`） | 已排除 |
| 登录态缓存 | `unicom_token_cache.json` | 已排除 |
| 会话 Cookie | `session_cookies.json` / `session_cookies2.json` | 已排除 |
| 登录中间态 | `sms_login_state.json` / `sms_state.json` / `qr_state.json` | 已排除 |
| 二维码 | `unicom_qr.png` | 已排除 |
| 奖品缓存 | `unicom_prize_cache.json` | 已排除 |
| 账号/配置/记录 | `accounts.json` / `settings.json` / `wins.json` / `results.json` | 已排除 |
| 运行日志 | `run_*.log` | 已排除 |

**已核实**：全仓库扫描未发现 608 位 `token_online`、160 位 `app_id`、
`chinaUnicomCookie="<真实值>"` 或 `acw_tc`/`ecs_token`/`JUT` 等真实 cookie。
使用者首次运行时，程序会在自己的 `%APPDATA%\UnicomAllIn1\` 下**自行创建**配置。

## 二、已脱敏的本机信息

上传前已把开发机专属路径替换为通用占位符（仅出现在注释/文档字符串，不影响运行）：

- Windows 用户目录下的桌面路径 → `<桌面>` / `<官方原始脚本路径>` / `<你的Python路径>`
- 个人工作盘上的项目路径 → `<项目目录>` / `<工作区>`

已复核：仓库内**无** Windows 用户名、个人工作盘路径、`C:\Users\` 等本机标识残留。

## 三、⚠️ 源码来源与版权

**`core/legacy.py` 与 `unicom_login_server.py` 不是本仓库原创**：

- `core/legacy.py` = 中国联通自动化脚本 **v1.2.1**，取自第三方脚本库（`script.345yun.cn`）。
  其文件头自带免责声明，明确写明：脚本库**不审核**脚本内容，账号安全、
  数据泄露、设备故障、封号、财产损失等风险**由使用者自担**。
- `unicom_login_server.py` = 移植自开源项目 `canxin121/china-unicom-rs`（2026-07）
  所逆向的官方 App 接口协议。

**上传前请自行确认**：你是否有权再分发这些来源的代码。如需合规，
建议只提交你自己撰写的部分（GUI 装配层 `app/`、测试、打包脚本），
把上述两个文件作为依赖说明或由使用者自行获取。

## 四、⚠️ 使用风险（务必在 README 中明示）

1. **违反服务条款 / 封号风险**：本项目调用中国联通接口自动执行签到、抽奖、
   抢兑等；抢兑模式用并发线程 + 固定时间点，风控特征明显。
   这可能违反联通用户协议，**有封号可能**。
2. **安全管家模块会改动联通侧真实配置**：增删账号的黑名单 / 通讯录 / 拦截规则
   （多为写死的测试数据，但确实会提交请求）。
3. **明文 HTTP**：安徽超级星期五使用 `http://123.138.11.116:8080`。
4. **AI入戏会上传图片**：联通云盘「海岛逐浪 / AI入戏」会把图片上传到
   联通云盘（`panservice.mail.wo.cn`）与芒果接口（`mgcact.api.mgtv.com`）。
   请只放愿意上传的图片。
5. **公开仓库的连带影响**：一旦公开，任何人都可下载使用上述自动化能力。

## 五、安全性核查结论（对 v1.2.1 内核）

已复查整份内核（`core/legacy.py`）：

- 危险构造 **0 命中**：`exec(` / `eval(` / `subprocess` / `os.system` /
  `os.popen` / `__import__` / `pickle` / `compile(`（唯一 `compile(` 是 `re.compile`）。
- **212 个 URL 字面量 / 32 个唯一主机**，全部为联通系（`*.10010.com`、
  `*.wo.cn`、`*.wostore.cn`）与合作方（`*.mgtv.com`、`linktech.hk`）域名。
- 脚本库域名（`345yun`）**只出现在文件头注释里**，无任何回传请求。

## 六、仓库内出现的手机号说明

扫描会在仓库中匹配到几个号码，**均为原脚本作者的测试/示例数据，非真实个人号码**：

| 号码 | 出处 | 性质 |
|---|---|---|
| `18600000000` | `README.md`、测试用例、内核配置示例 | 通用示例占位号 |
| `13800000000` | `core/legacy.py` 兜底默认值 | 代码 fallback |
| `13088330789` | `core/legacy.py` 安全管家测试数据（标注"疑似诈骗"） | 作者写死样例 |
| `13105750575` | `core/legacy.py` 通讯录测试数据（`addressBookName: 可乐`） | 作者写死样例 |

打包产物 `中国联通日常任务.exe` 内另有一处 `13333333333` 字节序列，
系依赖/编译器内嵌数据，非个人号码。

**如你仍介意**，可把上表 4 个号码统一替换为 `13800000000` 全零样式占位符。

## 七、提交前自查清单

```powershell
# 1) 确认无凭证文件被跟踪
git status --short | Select-String "creds|cookie|token_cache|_state|accounts.json|settings.json"

# 2) 确认无本机路径残留 (按你自己的用户名/盘符替换 <user>)
Select-String -Path *.py,*.md,*.bat -Pattern "<user>|[A-Z]:\\Users\\" -Encoding UTF8

# 3) 确认无真实凭证内容
Select-String -Path *.py,*.md,*.txt -Pattern "chinaUnicomCookie=`"[0-9a-f]{50,}" -Encoding UTF8

# 4) 确认可清缓存后重新打包（若提交 exe）
#    注意：不清 dist 与 build\work 时 PyInstaller 会复用缓存 TOC，
#    产出与旧构建逐字节相同的文件（"假重建"）
```

## 八、可移植性（已在模拟环境验证）

本仓库（源码模式）**不依赖开发机**：

- `app/paths.py` 用 `__file__` / `sys.executable` / `%APPDATA%` 动态解析路径，
  无硬编码绝对路径。
- `启动程序.bat` 用 `%~dp0`（脚本自身目录），可放在任意位置。
- `打包EXE.bat` 优先使用本机 `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`，
  找不到则回退 `python`。

**实测**：把整个目录复制到另一路径（`%TEMP%\git_sim_test`）并指定全新的空数据目录后，
`main.py --selftest` 13/13、`test_gui.py` 14/14、`test_sms_login.py` 23/23、
`verify_patch.py` 39/39、`probe_ttlxj.py` 23/23 —— 全部通过。

**他人电脑的前置条件**：

1. 若用打包好的 exe：装 Windows 即可，无需 Python。
2. 若跑源码：需 **Python 3.10+**，并 `pip install requests pycryptodome openpyxl`。
   （`tkinter` 随 Python 官方安装包自带；Linux 上需另装 `python3-tk`。）
3. 首次运行会自动在 `%APPDATA%\UnicomAllIn1\` 建立配置目录，无需手工准备。
