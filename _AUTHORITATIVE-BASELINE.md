# 权威基线登记（避免拿错上游比对）

> 建立于 2026-10-17。起因：独立验证员（t13）**自己**因拿错副本当上游，误算出
> 「4 个变化方法」（多出一个假的 `woread_task`）。本文件用于杜绝同类误判。

## 一、做「内核差异比对」时，唯一权威上游是桌面那份

| 角色 | 路径 | 大小 | SHA-256（前 24 位） | 说明 |
|---|---|---|---|---|
| ✅ **权威上游** | `<官方原始脚本路径>/中国联通v1.2.1.py` | 356,811 B | `960c3cfaa6a970cc6eb6ea87` | 官方原始脚本，比对基准 |
| ✅ **交付内核** | `unicom_allin1\core\legacy.py` | 361,153 B | `2e64c8932ba5c19d16f907e1` | 上游 + 5 类授权改动 |
| ⛔ **非权威旧副本** | `unicom_allin1\_NON-AUTHORITATIVE_old-copy_unicom_v121_new.py` | 356,609 B | `d025b36f19fbd26deb7cd031` | **不要当上游用** |

> 完整 SHA-256：
> - 权威上游 `960c3cfaa6a970cc6eb6ea87f03c071f5cece3cb843dcd72e26ca59179434590`
> - 交付内核 `2e64c8932ba5c19d16f907e12242b06ecd5e82b3eaf3f39c0bd7002e92d8830d`
> - 非权威副本 `d025b36f19fbd26deb7cd031a6b492d14ad11857fc91c018deb36885a5062950`

## 二、那个旧副本为什么危险

原名 `unicom_v121_new.py` —— 名字像「v1.2.1 新版」，实际是**状态更旧**的副本：

| 位置 | 权威上游（桌面） | 旧副本 |
|---|---|---|
| `globalConfig.enable_woread` | `True`（2026-10-15 开启） | `False` |
| `woread_task()` 末尾 | 抽奖调用**已注释停用**（2026-10-15 实测活动已下线） | 抽奖调用**仍启用** |

两处差异共 7 行（difflib 计）。若拿它当上游，会误判交付内核「多改了 `woread_task`」。

已于 2026-10-17 重命名为 `_NON-AUTHORITATIVE_old-copy_unicom_v121_new.py`
（**内容逐字节未变**，仅改名以自明状态）。全仓库**无任何代码引用**该文件，
`grep unicom_v121_new` 仅命中报告文档。

## 三、复现比对（每次做差异比对前先跑一遍）

```powershell
$py = '<你的Python路径>'
# 1) 先确认基线身份
Get-FileHash '<官方原始脚本路径>/中国联通v1.2.1.py' -Algorithm SHA256   # 应为 960c3cfa…
Get-FileHash '<项目目录>\core\legacy.py' -Algorithm SHA256  # 应为 2e64c893…
# 2) 再做差异比对（以桌面那份为上游）
& $py -X utf8 -c "import difflib;a=open(r'<官方原始脚本路径>/中国联通v1.2.1.py',encoding='utf-8').read().splitlines();b=open(r'<项目目录>\core\legacy.py',encoding='utf-8').read().splitlines();o=difflib.SequenceMatcher(None,a,b,autojunk=False).get_opcodes();print('add',sum(j2-j1 for t,i1,i2,j1,j2 in o if t in('insert','replace')),'del',sum(i2-i1 for t,i1,i2,j1,j2 in o if t in('delete','replace')))"
# 预期: add 116 del 5
```

## 四、预期结论（供交叉核对）

- 差异区 **16 个**，`+116 / -5`，净 `+111`
- 方法体变化 **恰 3 个**：`unicom_login` / `ensure_login` / `execute_daily_tasks`
- 新增 **3 个**顶层函数：`_stopped` / `_check_stop` / `_sleep`；无方法消失
- **11 个日常任务模块入口方法体逐字节相同**

> ⚠️ 关于「未改动方法数」：不同统计口径（是否计入嵌套函数、是否按方法名去重）会得到
> 不同分母（观察值 304 / 313 / 318 / 319 等）。**比对时只陈述不依赖分母的不变量**：
> 变化的方法恰为上列 3 个、11 个业务模块方法体逐字节相同。
