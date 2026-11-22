# 区分表数据集规范与结构说明 (Data Schema)

本 Skill 自带完整的中国《类似商品和服务区分表》（尼斯分类）离线结构化数据集，包含 45 个大类、498 个类似群以及 31,749 项商品/服务条目。所有文件存储在 `data/` 目录下，以 JSON 格式分层组织。

---

## 目录与文件布局

```
data/
├── manifest.json       # 数据集元数据与统计清单
├── classes.json        # 45 个大类定义与官方注释
├── groups/             # 45 个大类的类似群索引
│   ├── 01.json
│   ├── ...
│   └── 45.json
└── details/            # 498 个类似群的具体明细（商品/服务项与审查注）
    ├── 0101.json
    ├── ...
    └── 4506.json
```

---

## 核心数据结构

### 1. `manifest.json`
数据集清单文件，记录当前数据的版本、抓取时间与节点规模。
```json
{
  "version": "1.0.0",
  "crawledAt": "2026-06-09T18:55:37.991Z",
  "status": "complete",
  "classCount": 45,
  "groupCount": 498,
  "detailCount": 498
}
```

### 2. `classes.json`
记录 45 个大类的定义、标题范围及官方排他性与包含性注释。
```json
[
  {
    "classCode": "09",
    "className": "第九类-科学仪器",
    "description": "科学、研究、导航、测量、摄影、电影、视听、光学、衡具、量具、信号...",
    "notes": "[注释] 第九类主要包括科学或研究用装置和仪器...本类尤其包括...本类尤其不包括...",
    "crawledAt": "2026-06-09T18:55:38.441Z"
  }
]
```

### 3. `groups/{classCode}.json`
每个大类对应一个群组索引文件，记录该大类下设的所有类似群。
```json
[
  {
    "groupCode": "0901",
    "groupName": "电子计算机及其外部设备",
    "classCode": "09"
  },
  {
    "groupCode": "0902",
    "groupName": "记录、记数检测器",
    "classCode": "09"
  }
]
```

### 4. `details/{groupCode}.json`
每个类似群一个明细文件，包含完整的官方审查注意事项、规范分段商品项及非规范收录项目。
```json
{
  "groupCode": "0901",
  "groupName": "电子计算机及其外部设备",
  "classCode": "09",
  "notes": [
    "注:1. 光盘，CD 盘(只读存储器)与 0908 CD 盘(音像)类似，交叉检索；",
    "2. 电子出版物（可下载）与 0908 唱片、录音带类似；",
    "9. 智能手表，智能手表（数据处理）与 1404 类似。"
  ],
  "sections": [
    {
      "label": "（一）",
      "items": [
        {
          "name": "加法器",
          "code": "090019",
          "type": "standard",
          "section": "（一）"
        },
        {
          "name": "计算机",
          "code": "090372",
          "type": "standard",
          "section": "（一）"
        }
      ]
    }
  ],
  "nonstandardItems": [
    {
      "name": "计算机键盘控制器",
      "code": "",
      "type": "nonstandard"
    }
  ],
  "crawledAt": "2026-06-09T18:57:29.268Z"
}
```

---

## 字段含义与枚举

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `classCode` | string | 2 位大类编号（如 `"01"` 至 `"45"`） |
| `groupCode` | string | 4 位类似群编号（如 `"0901"`、`"2114"`） |
| `type` | string | 项目类型：`"standard"`（官方标准项，有 6 位码）、`"marked"`（官方星号项/重点项）、`"nonstandard"`（非规范可申报项） |
| `code` | string | 6 位商品/服务项官方编码（如 `"090372"`）；非规范项此字段通常为空字符串 |
| `section` | string | 类似群内部的分段标签（如 `"（一）"`、`"（二）"`）；不同段落商品可能不判定为类似商品 |
| `notes` | list[string] | 类似群审查官方注，明确列出跨类别、跨群组交叉检索及商品互斥规则 |

---

## 数据版本与构建说明

- **基础版本**：对应国家知识产权局商标局公布的《类似商品和服务区分表》（基于尼斯分类第十二版/2026过渡期最新数据）。
- **更新与校验**：可直接运行 `scripts/build_data.py --validate-only` 进行完整引用完整性检查。如果需要从外部数据源重新构建，可指定 `--source` 与 `--output` 路径。
