# 公开发布准备

## 当前状态

本目录已作为公开 GitHub 仓库 [zhjnerv/ip-practice-workbench-skills](https://github.com/zhjnerv/ip-practice-workbench-skills) 发布，默认分支为 `main`，首次提交为 `d9022fb`。仓库公开不改变线上服务各自的能力、版本和访问规则，也不声明任何线上入口已经随本次更新。

## 公开内容

根 README、MIT LICENSE、维护说明、验证脚本与三个技能目录组成候选。每个技能包含独立 LICENSE 和 NOTICE，供单独安装时一并保留。

`.local/`、根 TASK_PLAN、运行缓存、下载产物和环境变量文件由 [.gitignore](../.gitignore) 排除。发布时核对实际 Git 清单，不复制整个原工作区。

## 公开后的维护事项

1. 审阅 [MIT 文件](../LICENSE) 和 [数据、模板来源范围](../DATA_SOURCES.md)。确认需要公开的数据包及其权利依据；当前本地迁移没有补齐来源证据的事实。
2. 后续继续补充数据、模板和附件的来源与再分发依据；如发现权利或隐私问题，及时调整公开内容。
3. 维护公开页面、安装说明、默认分支与仓库内容的一致性。
4. 处理 `myskill` 移除与入口替换；如需要门户新增开源入口，再同步门户源文件与发布目录。

## 验证入口

```bash
python -B -S -X utf8 scripts/verify.py
```

实际验收结果记录于 [迁移记录](migration.md)。离线测试不替代数据来源审查或联网能力验证。
