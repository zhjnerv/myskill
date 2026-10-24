# 度衍（uyanip.com）命令检索 SOP

> **在本仓库中的定位**：本 SOP 是 `cn-patent-application-creator` 检索阶段的首选渠道说明。
> `generate_search_query.py` 输出的 `search-query.json` 中 `uyanip_plan`（`priority=1`）字段即按本文件构造；
> 候选范本的逐篇 IPC 核验仍走 EPO OPS → 分类缓存 → 候选输入的原定顺序（见 `references/template-ipc-selection.md`）。

> 实测日期：2026-09-23
> 账号：**普通会员**（非精英版）
> 适用：中国专利检索（命令检索模式）+ 结果页结构 + 可复用 URL

## 1. 账号与权限

- 本账号为**普通会员**：带 `*` 的字段是**增值字段，需精英版及以上**才可用。普通会员应避开这些字段，否则可能报错或返回空结果。
- 登录态由用户在真实 Chrome 会话里自行维护；自动化流程不代填账号密码、不读取 cookie/token。

## 2. 入口与页面控件

- 命令检索页：`https://www.uyanip.com/search/command`
- 关键控件（实测 DOM）：

| 控件 | 选择器 | 说明 |
| --- | --- | --- |
| 表达式输入框 | `textarea#exp-text.command-exp` | placeholder「表达式」 |
| 检索 | `button#search` | 提交检索 |
| 清空 | `button#clear` | 清空表达式 |
| 逻辑连接符 | `.btn.logic-btn` | AND / OR / NOT |
| 全选 | `input#source-all` | 数据源全选 |
| 中国 / 外国 | `#china-all` / `#foreign-all` | 区域组 |
| 组织区域 | `#qglzz` `#oumeng` `#dongmeng` `#yidaiyilu` `#wujvhezuo` `#jinzhuanguojia` | 常用国家和地区组织 |
| 国家粒度 | `.source-chk.front-country.<CC>` | 如 `.front-country.CN` |
| 文献类型粒度 | `.source-chk.front-dbtype.<CC>` | 实用/外观/授权/公开 |

## 3. 命令语法

- 基本形态：`字段代码:(值)`
- 多条件：用逻辑连接符连接，例：`ZLMC:(新能源汽车) AND IPC:(B60L)`
- 括号必须成对，**不要多写或少写括号**（多一个右括号会导致检索无反应或结果异常）。
- 日期区间：`GKR:(2022-03-07 TO 2022-03-07)`
- 号码类：`GKH:(CN109977334A)`、`SQH:(CN201310651864.5)`

### 页面「命令与用法」原样记录（完整字段表）

```text
命令与用法
所有字段 KEYWORD:(升降机系统)
专利名称 ZLMC:(升降机系统)
摘要 ZY:(中小型工业)
权利要求 QLYQ:(汽车)
首项权利要求 SXQLYQ:(汽车)
独立权利要求 DLQLYQ:(汽车)
专利名称/摘要 ZLMC_ZY:(中小型工业)
专利名称/摘要/权利要求 ZLMC_ZY_QLYQ:(汽车)
法律状态 FLZTA:(授权)
法律事件 FLSJ:(权力转移)
案件信息 ZLWS:(口审)
IPC分类号 IPC:(A01)
IPC主分类号 MIPC:(A01)
IPC分类-部 IPCL1:(A)
IPC分类-大类 IPCL2:(A01)
IPC分类-小类 IPCL3:(A01B)
IPC分类-大组 IPCL4:(A01B1)
IPC分类-小组 IPCL5:(A01B1/02)
外观设计分类 IPC:(01)
外观设计分类-大类 WGFL_B:(01)
外观设计分类-小类 WGFL:(01-01)
CPC分类 CPC:(A01)
CPC分类-部 CPC1:(A)
CPC分类-大类 CPC2:(A01)
CPC分类-小类 CPC3:(A01B)
CPC分类-大组 CPC4:(A01B3)
CPC分类-小组 CPC5:(A01B3/02)
F-Term英文/日文 FTERM4:(2C088)
F-Term-大类 FTERM1:(2C)
F-Term-小类 FTERM2:(2C088)
F-Term-大组 FTERM3:(2C088/AA)
F-Term-小组 FTERM4:(2C088/AA03)
国民经济行业分类 GMJJHY:(011)
国民经济行业分类-大类 GMJJHY_IPC_LAYER1:(A)
国民经济行业分类-小类 GMJJHY_IPC_LAYER2:(01)
国民经济行业分类-大组 GMJJHY_IPC_LAYER3:(011)
国民经济行业分类-小组 GMJJHY_IPC_LAYER4:(0111)
 
公开(公布)号 GKH:(CN109977334A)
申请号 SQH:(CN201310651864.5)
优先权号 YXQH:(CN201310692639)
公开(公布)日 GKR:(2022-03-07 TO 2022-03-07)
申请日 SQR:(2022-03-07 TO 2022-03-07)
授权(公告)日 SHOUQR:(2022-03-07 TO 2022-03-07)
优先权日 YXQR:(2022-03-07 TO 2022-03-07)
最早优先权日 ZZYXQR:(2022-03-07 TO 2022-03-07)
(预计)到期日 EXPIRE_DATE:(2022-03-07 TO 2022-03-07)
PCT进入国家阶段日 PCT_COUNTRY_DATE:(2022-03-07 TO 2022-03-07)
引用专利 YYZL:(CN201310651864.5)
被引用专利 BYYZL:(CN201310651864.5)
简单同族 JDTZ:(CN201310651864.5)
专利奖 HJQK:(优秀奖)
标准 BZ:(3GPP5GNR)
标准号 BZH:(TS38.331)
申请方式 APPLY_TYPE:(一案双申/分案申请)
转让年 * ZRSXR:(2021)
质押年 * ZYSXR:(2021)
失效年 * SXN:(2021)
许可年 * XKSXR:(2021)
审查时长 * REVIEW_DAYS:(12-18个月)
复审决定年 * FSJDRRL:(2021)
无效决定年 * WXJDR:(2021)
口审年 * ORAL_HEAR_NOTICE:(2021)
复审决定 * REVIEW_DECISION:(维持驳回)
无效决定 * INVALID_DECISION:(全部无效)
转让类型 * ZRLX:(申请权转让)
许可类型 * XKLX:(独占许可)
质押类型 * ZYLX:(保全)
权项数 QXS:(10)
被引证数 * BE_CITATIONED_BY_APPLICANT_COUNT:(1)
被审查员引证数 * BE_CITATIONED:(1)
引用专利国别数 * CITATION_COUNTRY_COUNT:(1)
引用非专利文献数 * CITATION_UN_PT:(1)
引证专利数 * CITATION:(4)
IPC部数 * IPC_BS:(1)
IPC小类数 * IPC_XLS:(1)
独权数 * INDEP_CLAIM_COUNT:(1)
主权项数字数 * MAIN_CLAIM_WORD_COUNT:(50)
说明书页数 * SMSYS:(10)
 
申请(专利权)人 SQREN:(清华大学)
第一申请(专利权)人 DYSQR:(清华大学)
第一申请(专利权)人类型 * APPLICANT_TYPE:(企业/个人/高校/科研院所/国企事业单位)
发明人 FMR:(潘杰)
第一发明人 DYFMR:(潘杰)
当前专利权人 DQQLR:(清华大学)
当前第一专利权人 DYDQQLR:(清华大学)
当前第一权利人类型 * CUR_APPLICANT_TYPE:(企业/个人/高校/科研院所/国企事业单位)
中间权利人 * ZJQLR:(清华大学)
中间权利人类型 * MID_APPLICANT_TYPE:(企业/个人/高校/科研院所/国企事业单位)
代理人 DLR:(汤东风)
代理机构 DLJG:(方圆)
当前代理人 DQDLR:(汤东风)
当前代理机构 DQDLJG:(方圆)
地址 DZ:(北京市永定路4号)
当前地址 DQQLRDZ:(北京市永定路4号)
当前区域 * DQQLRQY:(浙江省 杭州市 拱墅区)
同族国家 * FAMILYS_COUNTRY:(US)
被引证国别 * BE_CITATION_COUNTRY:(US)
引证国别 * CITATION_COUNTRY:(US)
优先权国别 * YXQGB:(US)
转让人 * BGQZRR:(清华大学)
许可人 * XKR:(清华大学)
被许可人 * BXKR:(清华大学)
当前被许可人 * CUR_PROMISED:(清华大学)
出质人 * CZR:(清华大学)
质权人 * ZQR:(清华大学)
当前质权人 * CUR_PLEDGE:(清华大学)
复审请求人 * FSQQR:(清华大学)
无效请求人 * FSWXQQR:(清华大学)
布局国家数 * FAMILYS_COUNTRY_COUNT:(1)
PCT同族申请 * IF_PCT:(是)
存活期(年) * SURVIVE_YEARS:(1)
同族数 * FAMILYS_COUNT:(1)
三方专利(美日欧) * IF_THIRD_PARTY:(1)
剩余有效期(年) * LEFT_YEARS:(1)
无效次数 * INVALID_COUNT:(1)
转让次数 * TRANS_COUNT:(1)
许可次数 * PROMISE_COUNT:(1)
质押次数 * PLEDGE_COUNT:(1)```

## 4. 数据源范围

- 命令页默认全选数据源。
- 点击检索时，站点把范围拼成 `GJ:(...)` 追加到表达式：
  `sourceStr = 'AND GJ:(' + window.sources.join(' OR ') + ')'`
- 结果页 URL 的 `country` 参数就是这个 `sourceStr`，可为空（默认范围）。

## 5. 执行检索

### 5.1 人工路径

1. 打开 `https://www.uyanip.com/search/command`
2. 在表达式框输入检索式，如 `ZLMC:(新能源汽车)`
3. 按需勾选数据源范围（默认全选可不动）
4. 点「检索」→ 新标签页打开结果页

### 5.2 URL 直开（推荐自动化路径）

站点点击检索的真实行为：

```js
window.open('/result?fromMode=5&exp=' + $('#exp-text').val() + '&country=' + sourceStr, '_blank')
```

因此可直接构造结果页 URL：

```text
https://www.uyanip.com/result?fromMode=5&exp=<URL编码的表达式>&country=<URL编码的范围>
```

- 示例（已验证可打开）：`https://www.uyanip.com/result?fromMode=5&exp=ZLMC%3A(%E6%96%B0%E8%83%BD%E6%BA%90%E6%B1%BD%E8%BD%A6)&country=`
- 优点：绕开 `window.open` 的**用户手势限制**（自动化点击常被拦下、表现为「点了没反应」）。
- 注意：`exp` 必须整体 URL 编码，中文用 `encodeURIComponent`。

## 6. 结果页结构

- 结果计数：`共 N 件专利`
- 左侧筛选：数据源、专利类型、IPC 国际分类号、LOC 洛迦诺分类、申请人、当前权利人、发明人、代理机构、代理人、申请年、公开年、授权年、法律状态、法律事件、案件信息、权项数、专利奖、ETSI 标准、ETSI 标准号、自定义；`重置` / `筛选`
- 二次检索区：`检索`（结果集内二次检索）、`保存检索式`、`扩展检索`、`关键词不拆分`
- 排序：相关度排序 / 申请日升序·降序 / 公开日升序·降序 / 授权日升序·降序
- 每页条数：10 / 20 / 40 / 100
- 展示模式：图文展示 / 表格展示 / 多图展示 / 首图展示
- 单条记录字段：类型标签（如 `[发明授权]`）、申请号、名称、法律状态（如「有效-审定授权著录变更」）、公开(公布)号、公开(公布)日、申请日、IPC 分类号、当前权利人、权项数、摘要
- 单条操作入口：`著录项信息`、`权利要求`、`说明书`、`授权文本`、`法律状态文本下载`、`同族信息`
- 同页其他入口：`下载历史`（`/user/download/history`）、`检索历史`（`/user/search/history`）

## 7. 相关页面（实测链接）

| 功能 | URL |
| --- | --- |
| 简单检索 | `/` |
| 高级检索 | `/search/keyword` |
| 法律检索 | `/search/legal-status` |
| 命令检索 | `/search/command` |
| 批量检索 | `/search/batch` |
| 分类号检索 | `/search/classify` |
| 检索历史 | `/user/search/history` |
| 下载历史 | `/user/download/history` |
| 智能检索 | `/aiqa/aiSearch` |

## 8. 自动化注意事项

- `window.open` 需要真实用户手势：脚本内 `element.click()` 通常被拦截 → 优先用 5.2 的 **URL 直开**。
- 登录态依赖用户自己的 Chrome 会话；过期时需要用户重新登录。
- 普通会员不要依赖带 `*` 的增值字段。
- 结果页是 SPA，读取列表前要等渲染完成（约 1–3 秒稳定）。
- 检索式里的中文需要 URL 编码。

## 9. 实测结论（2026-09-23 自由探测，均有件数/文件证据）

### 9.1 范围与国家

| 实验 | 表达式 | country 参数 | 结果 |
| --- | --- | --- | --- |
| 基线 | `ZLMC:(新能源汽车)` | 空 | 45,240 |
| 显式中国 | 同上 | `AND GJ:(CN)` | 45,240（与空一致 → **默认即中国**） |
| 美国 | 同上 | `AND GJ:(US)` | 0（中文名在美国库无匹配） |
| 美国（英文） | `KEYWORD:(battery)` | `AND GJ:(US)` | 415,122 |
| WO（英文） | `KEYWORD:(battery)` | `AND GJ:(WO)` | 208,675 |

- 国家代码即专利国别代码：CN / TW / HK / MO / US / EP / WO / JP / GB / DE / KR 等
- 每个国家可再按文献类型勾选（实用/外观/授权/公开），对应 `.source-chk.front-dbtype.<CC>`
- 自动化推荐：`country=AND GJ:(CN)`，或留空（默认中国）

### 9.2 布尔运算与检索式

| 实验 | 结果 | 说明 |
| --- | --- | --- |
| `ZLMC:(新能源汽车)` | 45,240 | 基线 |
| `... AND ZY:(电池)` | 13,837 | AND 收窄 |
| `... OR ZLMC:(电动车)` | 135,262 | OR 扩大 |
| `... NOT ZY:(电池)` | 31,403 | NOT 排除 |
| `(ZLMC:(汽车) OR ZLMC:(车辆)) AND ZY:(电池)` | 100,429 | 括号分组有效 |
| `ZLMC:(汽车) AND (ZY:(电池) OR ZY:(电机))` | 146,204 | 嵌套括号有效 |
| `ZLMC:(新能源*)` | 93,726 | 通配符 `*` 有效 |

字段语义对照（同一关键词「电池」）：

| 字段 | 结果 | 含义 |
| --- | --- | --- |
| `KEYWORD:(电池)` | 2,585,639 | 所有字段 |
| `ZY:(电池)` | 1,716,011 | 摘要 |
| `ZLMC_ZY:(电池)` | 1,726,453 | 名称+摘要（去重并集） |
| `ZLMC:(电池)` | 817,289 | 名称 |

日期区间：`GKR:(2020-01-01 TO 2021-12-31)` 实测生效（与 `ZLMC:(汽车)` 组合 160,265 件）。

### 9.3 详情页与正文读取

- 详情页：`https://www.uyanip.com/detail?aid=<申请号>`
  - 权利要求 `/detail?aid=<申请号>&i=b`；说明书 `&i=c`；法律状态 `&o=f`；同族 `&o=d`
- 正文在 DOM 中直接可读（实测 CN201810328676.1）：
  - 权利要求 tab → 权项全文；说明书 tab → 全文带段号 `[0001]`–`[0018]`
  - 页面另有「复制权利要求」「复制说明书」按钮（`class="copy-text"`）
- 读取方式：点击 `#item-detail-a-b`（权利要求）/ `#item-detail-a-c`（说明书）/ `#item-detail-a-d`（附图）/ `#item-detail-a-e`（pdf在线浏览）后读 `document.body.innerText`

### 9.4 专利附图

- 附图 tab：`#item-detail-a-d`；点击后触发 `interPdfFetch?aid=<申请号>&pid=<公开号>`
- 附图地址：`http://picnew.duyandb.com/img/<长hash>`（页面标注「摘要附图(1)、说明书附图(2)」）
- 实测可直接下载（带 Referer `https://www.uyanip.com/`）：HTTP 200，GIF 89a，1000×758 / 1000×378
- 示例（CN201810328676.1）3 张附图已保存至 `~/下载/CN201810328676.1_附图/`

### 9.5 PDF 下载（已完整实测）

- 按钮：详情页固定工具条 `span#pdf-download[title="PDF下载"]`
- 页面变量 `pdfItemInfo`：

```json
{"pdfKeyValid":true,"pdfKey":"95BF5DAE-1E47-46C8-A991-CB9D54EFB339","pubNumber":"CN108583297A","wordWildPdf":null,"dbType":1,"aid":"CN201810328676.1","foreign":false}
```

- 下载地址模式：

```text
https://api.duyandb.com/search/search/pdfByKey/download/<公开号>/<pdfKey>
```

- 交互逻辑（源码实测）：
  - 无 `access_token` cookie → 打开登录框
  - `pdfKeyValid === true` → `window.open(下载地址)`
  - `pdfKeyValid === false` → 提示「今日免费pdf查看，下载的次数已达到上限，【开通会员】」
- 实测：直接导航到下载地址即触发下载（绕开 `window.open` 手势限制），文件落到 `~/下载/`：
  `CN201810328676.1__郑州檀乐科技有限公司__新能源汽车的车体及新能源汽车__发明专利.pdf`（PDF 1.4，4 页，318,581 bytes）
- 文件命名模式：`{申请号}__{申请人}__{名称}__{类型}.pdf`
- 站点 API 域名：`https://api.duyandb.com`

### 9.6 自动化落地要点

1. 检索：`/result?fromMode=5&exp=<编码表达式>&country=<编码范围>` 直接导航
2. 详情：`/detail?aid=<申请号>` 直接导航；正文靠点击 tab 后读 `innerText`
3. 附图：抓 `img[src*=picnew.duyandb.com]`，带 Referer 下载
4. PDF：读 `pdfItemInfo` → 拼下载 URL → 直接导航触发下载（需登录态 + `pdfKeyValid=true`）
5. 一律优先「URL 直开/导航」，规避 `window.open` 手势限制与 `alert` 阻塞

### 9.7 关键前提：window.open 类操作必须在「前台标签页」执行（根因结论）

**结论：检索、PDF 下载等走 `window.open` 的操作，要求目标标签页处于前台激活状态，否则静默失败。**

- 后台标签（`document.visibilityState !== "visible"` 或 `document.hasFocus() === false`）时：
  - 点击 `#search` / `#pdf-download` **无任何反应**（无网络请求、无下载、无弹窗）
  - 既不是登录问题，也不是选择器问题
- 正确做法：点击前先执行 CDP `Page.bringToFront`，确认 `{hidden:false, vis:"visible", hasFocus:true}`，再用 `Input.dispatchMouseEvent` 发真实点击
- 实测证据（CN201810328676.1，详情页前台点击 `#pdf-download`）：
  - `onDownloadChange: id=12, status=started`
  - `onDownloadChange: id=12, status=complete`
  - 落盘：`~/下载/CN201810328676.1__郑州檀乐科技有限公司__新能源汽车的车体及新能源汽车__发明专利 (1).pdf`（PDF 1.4 / 4 页 / 318,581 bytes）
- 应急路径（前台条件不满足时）：直接 `Page.navigate` 到下载 URL，同样能触发下载（已实测）
- 另注意：页面 `alert()` 会阻塞后续脚本操作，需用 `Page.handleJavaScriptDialog` 处理

### 9.8 详情页标题区三图标（用户指出并实测确认）

标题行 `div#tip-item.iconfont.result-nav-btn`（位于「寄售 / 购买」左侧）内三个图标，从左到右：

| 位置 | 元素 | 作用 |
| --- | --- | --- |
| 左 1 | `span#pdf-download[title="PDF下载"]` | 点击即下载 PDF（与页面固定工具条同一 handler） |
| 左 2 | `span#open-collect[title="关注"]` | 关注 |
| 左 3 | `span#open-highlight[title="高亮"]` | 高亮 |

实测（2026-09-23，样本 CN201810328676.1）：

- 前台标签（`Page.bringToFront` → `hasFocus()===true`，`pdfKeyValid===true`）+ 真实鼠标点击左 1 图标
- `onDownloadChange: id=13, status=started` → `status=complete`
- 落盘：`~/下载/CN201810328676.1__郑州檀乐科技有限公司__新能源汽车的车体及新能源汽车__发明专利 (2).pdf`
- 校验：PDF 1.4 / 4 页 / 318,581 bytes / 文件头 `%PDF-1.4`

结论：这组图标与固定工具条的 PDF 下载是同一套逻辑；前提仍是标签页处于前台，否则点击静默失败。
