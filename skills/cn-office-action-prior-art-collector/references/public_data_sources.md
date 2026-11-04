# 公开专利数据源与网络下载机制

本 Skill 采用公开、合法的全球专利开放接口与链接规则获取案卷材料，不依赖任何付费商业商业数据库 API 或专有 Cookie。

---

## 1. Google Patents 检索与下载机制

### 1.1 申请号查询公开文献号 (XHR Query API)
- **请求接口**：
  ```text
  GET https://patents.google.com/xhr/query?url=q%3D({query})&exp=&tags=
  ```
- **参数说明**：
  - `{query}`：经过 URL 编码的申请号（必须先剥离校验位，例如 `202410361819` 或 `CN202410361819`）。
- **返回结构**：
  返回标准 JSON。结果位于 `results.cluster[0].result[0].patent`：
  - `publication_number`：公开文献号（如 `CN118161961A`）。
  - `title`：专利名称。
  - `assignee`：申请人。
  - `inventor`：发明人。
  - `publication_date`：公开日期。
  - `pdf`：PDF 存储相对路径（如 `a1/b2/c3/.../CN118161961A.pdf`）。

### 1.2 说明书 PDF 下载候选链与优先级
针对给定的公开号（如 `CN114528944A`），脚本按如下顺序尝试获取 PDF：
1. **直接存储路径**（若 XHR 返回了 `pdf` 字段）：
   `https://patentimages.storage.googleapis.com/pdf/{pdf_path}`
2. **官方中文说明书链接**：
   `https://patents.google.com/patent/{PID}/zh.pdf`
3. **官方英文/原文说明书链接**：
   `https://patents.google.com/patent/{PID}/en.pdf`

### 1.3 PDF 响应校验标准
下载完成后必须执行双重完整性校验，严禁将异常响应写入 `.pdf`：
- **Magic Header 校验**：二进制首 10 字节必须包含 `b"%PDF-"`。
- **最小体积校验**：字节流长度必须 $> 1000$ 字节（排除部分反爬页面返回 200 OK 的空白或短 HTML）。

---

## 2. 欧洲专利局 (Espacenet) 官方备用入口

### 2.1 备用链接生成算法
当因网络受阻、源站未收录 PDF 或海外访问受限时，脚本自动根据文献号生成 Espacenet 官方文献著录与公开文本入口：
- **URL 模板**：
  ```text
  https://worldwide.espacenet.com/publicationDetails/biblio?CC={CC}&NR={NR}{KC}&KC={KC}&FT=D
  ```
- **示例**：
  - `CN114528944A` -> `https://worldwide.espacenet.com/publicationDetails/biblio?CC=CN&NR=114528944A&KC=A&FT=D`
  - `US20200234567A1` -> `https://worldwide.espacenet.com/publicationDetails/biblio?CC=US&NR=20200234567A1&KC=A1&FT=D`
  - `WO2019123456A1` -> `https://worldwide.espacenet.com/publicationDetails/biblio?CC=WO&NR=2019123456A1&KC=A1&FT=D`

---

## 3. 限流保护与重试策略

- **指数退避**：遭遇 HTTP 429（Too Many Requests）或 503（Service Unavailable）时，等待 $2^{\text{attempt}} + \text{uniform}(0.5, 1.5)$ 秒后重试。
- **批量请求间隔**：批量下载对比文件时，各文件之间主动休眠 1.0 ~ 2.0 秒，避免触发源站的 IP 频率限制。
- **超时控制**：默认单次连接与读取超时设置为 30 秒，防止因单篇文献停滞阻塞整体案卷取材。
