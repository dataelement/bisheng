# 开发者技能包 —— 怎么让 AI 用上

`bisheng skills sync` 会把平台当前版本的技能包拉到本机:

```
~/.bisheng/skills/
  deploy-hosting/          部署纳管:把本地应用部署到企业应用平台
    SKILL.md               技能正文(AI 读这个)
    example/               可运行样例,改造它比从零写更稳
    selfcheck.py           部署前连通自检
```

技能包是平台发布物,`skills sync` **单向覆盖**本地内容(不合并、不保留本地改动)——平台升级后重跑即更新到新版本。

## 让你的 AI 编程工具用上它

- **Claude Code**:自动发现 `~/.bisheng/skills/*/SKILL.md`,识别到部署意图时会自行参考,无需额外配置。
- **Cursor / 通义灵码 / 其它引擎**:在你的项目根放一个 `AGENTS.md`(或该工具约定的规则文件),指向同一目录即可:

  ```markdown
  # AGENTS.md
  把本地应用部署到公司应用平台时,先读并遵循:
  ~/.bisheng/skills/deploy-hosting/SKILL.md
  参考可运行样例:~/.bisheng/skills/deploy-hosting/example/
  ```

- **手动**:直接把 `~/.bisheng/skills/deploy-hosting/SKILL.md` 的内容贴给 AI,告诉它「照这个把应用部署到平台」。

## 想扩展/定制?

技能目录随时会被 `skills sync` 覆盖,**不要**直接改里面的文件。要补充团队自己的约定,写在你项目的
`AGENTS.md` 里、放在技能目录**之外**。
