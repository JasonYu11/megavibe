# 分级安全审批方案

## 问题

当前 `bash_policy.default: "ask"` — **所有 bash 命令都要审批**，过于激进。
低风险命令（`ls`、`git status`、`npm test`）无谓打断 agent 流程。

## 方案：三级审批

```
TIER 0 安全命令        → 自动放行 (allow)
TIER 1 有影响命令       → AutoReviewAgent 审查 (auto_review)  
TIER 2 危险命令         → 人工审批 (escalate → ask)
```

### Tier 0 — 自动放行

命令以这些前缀开头或在安全列表内：

```
Safe patterns:
  ls, cat, echo, pwd, which, whoami, uname, date, env, printenv
  head, tail, wc, sort, uniq, cut, tr, awk, sed -n
  grep, rg, find (无 -exec/-delete)
  git status, git diff, git log, git branch, git show, git stash list
  mkdir, touch, cp, mv, ln -s (workspace 内)
  python, python3, node (运行脚本/测试)
  npm test, npm run build, npm run dev, npm run lint, npx
  pip install, npm install (--save-dev)
  curl, wget (GET 请求)
  pgrep, ps, top, df, du, free
```

### Tier 1 — AutoReviewAgent 审查

不在 Tier 0 且不匹配 Tier 2 的命令：

```
Triggers:
  git commit, git push, git rebase, git merge
  npm publish, npm unpublish
  docker run, docker build, docker-compose up
  rm, rmdir (非递归/非 root)
  write_file / edit_file (outside workspace)
  python_run (写入文件操作)
```

### Tier 2 — 人工审批

```
Patterns (must escalate):
  rm -rf /, rm -rf ~, rm -rf /*
  sudo, su
  chmod -R /, chown -R /
  mkfs, dd if=, fdisk
  shutdown, reboot, halt
  git push --force main/master
  :(){ :|:& };: (fork bomb)
  eval (可疑)
  curl/wget | bash/sh
```

---

## 实现改动

### 1. `mcode-policy.json` — 新增 tier 配置

```json
{
  "bash_policy": {
    "default": "auto_review",
    "auto_allow_patterns": [
      {"pattern": "^(ls|cat|echo|pwd|which|whoami|uname|date|env|printenv)\\b", "reason": "read-only"},
      {"pattern": "^(head|tail|wc|sort|uniq|cut|tr)\\b", "reason": "text processing"},
      {"pattern": "^(grep|rg|find)\\s", "reason": "searching files"},
      {"pattern": "^git\\s+(status|diff|log|branch|show|stash\\s+list)\\b", "reason": "git read-only"},
      {"pattern": "^(mkdir|touch|cp|mv)\\s", "reason": "safe file ops in workspace"},
      {"pattern": "^(python3?|node)\\s", "reason": "runtime execution"},
      {"pattern": "^(npm|npx|yarn|pnpm)\\s+(test|run|build|lint|dev|start)", "reason": "dev scripts"},
      {"pattern": "^(pip3?|npm)\\s+install", "reason": "package install"}
    ],
    "escalate_patterns": [
      {"pattern": "\\brm\\s+-[^\\n;]*r[^\\n;]*f\\s+[/~]", "reason": "recursive force delete"},
      {"pattern": "\\bsudo\\b", "reason": "sudo"},
      {"pattern": "\\b(chmod|chown)\\s+-[^\\n;]*R\\b", "reason": "recursive permission change"},
      {"pattern": "\\b(mkfs|dd\\s+if=|fdisk|shutdown|reboot|halt)\\b", "reason": "system command"},
      {"pattern": "git\\s+push\\s+.*--force", "reason": "force push"},
      {"pattern": "\\|\\s*(ba)?sh\\b", "reason": "pipe to shell"}
    ]
  }
}
```

### 2. `safety.py` — 分级判断逻辑

```python
def _classify_bash_risk(self, command: str) -> tuple[str, str]:
    """
    Returns (decision, reason)
    decision: "allow" | "auto_review" | "escalate"
    """
    # Tier 2: check escalate patterns first
    for rule in self.bash_policy.get("escalate_patterns", []):
        if re.search(rule["pattern"], command):
            return ("escalate", rule["reason"])
    
    # Tier 0: check auto-allow patterns
    for rule in self.bash_policy.get("auto_allow_patterns", []):
        if re.search(rule["pattern"], command):
            return ("allow", rule["reason"])
    
    # Tier 1: auto_review for everything else
    default = self.bash_policy.get("default", "auto_review")
    return (default, "requires review")
```

当前硬编码在 `_check_bash` 中的 `"ask"` 换成调用 `_classify_bash_risk`，按返回值分发。

### 3. AutoReviewAgent 调整

`auto_review.py` 的 `strictness` 映射改为：
```json
{
  "bash": "normal",    // 只审 bash Tier 1 命令，不再审所有
  "write_file": "low",    // workspace 内自动允许
  "edit_file": "low",
  "python_run": "normal",
  "git_commit": "normal"
}
```

---

## 验收

- [ ] `ls` / `git status` / `npm test` → 自动放行，无审批
- [ ] `git commit -m "fix"` → AutoReviewAgent 审查
- [ ] `rm -rf /` → 弹出人工审批
- [ ] `sudo npm install` → 弹出人工审批
- [ ] 用户不感到审批打断正常开发流程
