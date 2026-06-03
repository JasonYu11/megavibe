# 静态检查 → 运行 双屏障策略

> 核心思想：写完代码先静态检查通过，再运行。两重屏障拦截低级错误。

---

## 问题

当前 agent 写完代码直接 `python_run` 或 `bash npm test`。如果代码有语法错误、类型不匹配、import 遗漏，运行会失败，agent 需要多一轮往返才能定位。浪费 token 和时间。

## 方案：write_file/edit_file 之后自动插入检查

### 不新增独立工具，改了现有 execute 行为

在 `write_file` 和 `edit_file` 的 execute 方法中，写完后自动跑一次轻量静态检查，输出附带到工具结果里。

```
write_file("foo.py", code) 返回:
  ✓ wrote foo.py (120 lines)
  🔍 static check passed  ← 自动附加
```

如果是失败：
```
write_file("foo.py", code) 返回:
  ✓ wrote foo.py (120 lines)
  ⚠ static check: 2 issues
    - line 45: NameError: name 'counter' is not defined
    - line 67: TypeError: 'int' object is not subscriptable
  Model: 看到这个应该主动修复
```

### 检查策略 — 按语言分级

| 级别 | 检查器 | 触发条件 | 耗时 |
|---|---|---|---|
| **快速** (默认) | Python: `py_compile`; TS: `tsc --noEmit`; JS: `node --check` | 每次 write_file/edit_file | < 200ms |
| **标准** | flake8 / eslint | `python_run` 或 `bash` 执行前 | < 2s |
| **深度** | mypy / pyright | agent 主动调用 `static_check` 工具 | < 10s |

### 修改文件

```
mini_agent_lab/tool/builtin.py
  WriteFileTool.execute()  → 写完跑 quick_check(path)
  EditFileTool.execute()   → 改完跑 quick_check(path)

新增: mini_agent_lab/tool/static_check.py
  QuickCheck  → py_compile / tsc --noEmit / node --check
  FullCheck   → flake8 / eslint（agent 主动调用）
  TypeCheck   → mypy --strict / pyright
```

### quick_check 实现

```python
def _quick_check(path: str) -> str:
    suffix = Path(path).suffix
    cmd = None
    if suffix == ".py":
        cmd = [sys.executable, "-m", "py_compile", path]  # 仅语法检查，不执行
    elif suffix in (".ts", ".tsx"):
        cmd = ["npx", "tsc", "--noEmit", "--pretty", path]  # 需有 tsconfig
    elif suffix == ".js":
        cmd = ["node", "--check", path]
    
    if cmd:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return "static check passed"
        return f"static check: {result.stderr.strip()[:500]}"
    
    return ""  # 不支持的文件类型，跳过
```

### Agent Prompt 新增规则

加到 Work Protocol 的步骤 4 (Execute Incrementally) 后面：

```
4a. After every write_file or edit_file, the tool result includes a static check.
     If the check fails, fix the errors before proceeding to the next step.
     Do not run code that has static check failures.

4b. Before running any Python/Node script that you just wrote or edited,
     run a quick static check first: python -m py_compile <file> or node --check <file>.
```

### 验收标准

- [ ] agent 写 Python 文件后自动看到语法错误，主动修复而不是直接运行
- [ ] agent 写 TS 文件后 tsc --noEmit 错误被拦截
- [ ] 一轮 edit → check → fix 循环不超过 2 次
- [ ] 不增加用户可见的延迟（quick_check < 500ms）
