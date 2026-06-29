# Claude Code Workflow Tool — Playbook

> 整合官方開發手冊 (https://code.claude.com/docs/en/workflows) 與
> integration-test 專案四輪迭代 (v1 → v4) 踩過的所有坑。
>
> **撰寫日期**: 2026-06-20 · **基於 Claude Code v2.1.183**
> **對象**: 開發者 (寫 workflow script) + 維運者 (監看 / 調試 workflow run)
> **專案上下文**: harness-methodology v2.12 Phase 1 Requirements workflow

---

## 1. 什麼是 Workflow(快速對齊)

| 物件 | 誰持有計畫 | 中間結果 | 中斷恢復 | 規模 |
|------|----------|---------|---------|------|
| **Subagent** | Claude 每輪決策 | 進入主對話 context | 整輪重來 | 每輪幾個 |
| **Skill** | Claude 依照指示 | 進入主對話 context | 重來 | 同 subagent |
| **Agent team** | Lead agent 監看 peer | 共享 task list | Peer 持續跑 | 一群長期 |
| **Workflow** | **Script 本身** | **Script 變數** | **同 session 內 resume** | **數十到數百個 agents** |

**Workflow = 把 plan 寫成 code**。Script 持有 loop、branching、中間結果;主對話 context 只看到最後答案。

**決策何時用 workflow**(滿足任一):
- 任務需要比單一對話能協調更多的 agents
- 想要 orchestration 寫成可讀、可重跑的 script
- 想套用可重複的 quality pattern(例: 對抗式 review、多角度草稿、獨立交叉查證)

**不要用 workflow**(滿足任一):
- 任務可在主對話 1-2 輪解決
- 結果只是探索性單一答案(不需要 adversarial review)
- 任務需要 mid-run 的人為決策 → 拆成多個小 workflow(因為 runtime 無 mid-run user input)

---

## 2. 檔案位置與啟動方式

### 存放位置(由近到遠)

| 路徑 | 範圍 | 適用 |
|------|------|------|
| `./<cwd>/.claude/workflows/<name>.js` | 該 package | 套件層級 workflow |
| `./<repo>/.claude/workflows/<name>.js` | 該 repo | 專案層級 (建議放這裡) |
| `~/.claude/workflows/<name>.js` | 全域個人 | 個人跨專案用 |

**Monorepo 行為** (v2.1.178+): 從 cwd 沿路往上找最近的 `.claude/workflows/`;若多個 `.claude/` 都定義同名 workflow,執行最近的那個。

**衝突規則**: Project workflow 優先於 Personal workflow(同名時)。

### 啟動方式

```bash
# 1. Slash command (最常用)
> /my-workflow-name arg1 arg2

# 2. /workflows view → 按 Enter → 選 saved workflow
> /workflows

# 3. 透過 ultracode 自動觸發
> ultracode: audit every API endpoint under src/routes/ for missing auth checks
> /effort ultracode    # 全 session 自動用 workflow

# 4. Programmatic(Agent 內)
Workflow({ script: "..." })              # inline script
Workflow({ scriptPath: "/abs/path.js" }) # 絕對路徑 (推薦)
Workflow({ name: "phase1-requirements" })# 用 name (有 cache 風險,見 §6.5)
Workflow({ scriptPath, resumeFromRunId: "wf_xxx" })  # resume
```

---

## 3. Script 結構 — meta 物件

### 必要欄位

```javascript
export const meta = {
  name: 'phase1-requirements',              // 必填,識別用
  description: 'Phase 1 Requirements ...',  // 必填,出現在 /workflows list
  whenToUse: 'optional; 顯示在 workflow list', // optional
  phases: [                                 // optional,顯示在 progress view
    { title: 'Preflight' },
    { title: 'Sub-Task 1/4 — SRS.md' },
    ...
  ],
}
```

### meta 規則(Validator hard errors)

| 規則 | 違規 → 結果 |
|------|-----------|
| 必須 FIRST statement | `ERROR: export const meta must be the FIRST statement` |
| 必須是純 literal | `ERROR: meta contains a spread`, `ERROR: meta contains a template literal`, `ERROR: meta appears to contain a function call` |
| 不能用 `__proto__` / `constructor` / `prototype` 當 key | `ERROR: meta uses reserved key` |
| 必須含 `name` 欄位 | `ERROR: meta is missing a name field` |
| 必須含 `description` 欄位 | `ERROR: meta is missing a description field` |

**正確範例**:
```javascript
export const meta = {
  name: 'my-workflow',
  description: 'Does X then Y',
  phases: [{ title: 'Phase 1' }, { title: 'Phase 2' }],
}
```

**錯誤範例**(會被 validator 擋):
```javascript
const prefix = 'my-'
export const meta = { name: prefix + 'workflow', ... }  // ❌ 函式呼叫
export const meta = { name: 'my-workflow', desc: `template` } // ❌ template literal
export const meta = { name: 'my-workflow', __proto__: {} }   // ❌ reserved key
```

---

## 4. Script 語法限制 — 什麼不能用

### Hard errors (validator + runtime 都會擋)

| 違規 | 原因 | 解法 |
|------|------|------|
| `Date.now()` | 破壞 resume(時間漂移) | 由 args 傳入 timestamp,或 workflow 回傳後再 stamp |
| `Math.random()` | 破壞 resume | 由 args 傳入 seed,或用 prompt 加 index 區分 |
| `new Date()` 無參數 | 同上 | 同上 |
| 檔案大小 > 524288 bytes (512 KB) | runtime 拒絕解析 | 拆 workflow 或縮減 prompt |

### Warnings (validator 警告 + runtime 直接 throw)

| 違規 | Runtime 行為 | 解法 |
|------|-------------|------|
| `import('node:fs')` / `await import()` | **runtime 直接 throw** | 用 `agent()` 委派檔案 I/O |
| `fs.*` / `path.*` / `process.*` / `require()` | runtime 直接 throw | 同上 |
| `import ... from ...` (靜態) | runtime 直接 throw | 同上 |

> **v1 踩坑**: shipped workflow 用了 `const fs = await import('node:fs')`。
> Validator 只 warn,runtime 直接 throw — 因為 script 沒有 Node API 存取權。
> **正確解法**: 從 script 移除所有 host API;檔案讀寫交給 agent()。

### 語言限制

- ✅ **純 JavaScript** (不用 TypeScript,type annotation 會 parse error)
- ✅ 無 `import()` / `require()`
- ❌ TypeScript 型別註記(會被 parser 拒絕)
- ❌ `node:fs` / `node:path` 等 Node 模組

### Runtime 限制 (runtime 的額外約束,validator 抓不到)

| 約束 | 影響 |
|------|------|
| 無 mid-run user input | 唯一能 pause 的是 agent permission prompt;要在 stage 之間人工 sign-off → 拆成多個 workflow |
| 無 fs / shell access from script | 所有 I/O 透過 agent() |
| ≤ 16 concurrent agents (CPU cores - 2 取小) | 超過會 queue |
| ≤ 1000 agents total per run | runaway backstop |
| ≤ 4096 items per parallel/pipeline 呼叫 | 超過是顯式 error |

---

## 5. Script API — agent / parallel / pipeline / phase / log

### 5.1 `agent(prompt, opts)`

```javascript
const result = await agent(prompt, {
  label: 'a1-srs-r1',           // 顯示在 progress view
  phase: 'Sub-Task 1/4',        // 分組到 phase box
  agentType: 'general-purpose', // 'general-purpose' | 'Explore' | 'Plan' | 自訂
  model: 'haiku',               // 覆寫 session model (cheaper reviewers 用 haiku)
  effort: 'medium',             // 'low' | 'medium' | 'high' | 'xhigh' | 'max'
  schema: SCHEMA,               // JSON Schema → 強制 agent 呼叫 StructuredOutput tool
  isolation: 'worktree',        // 給 agent 獨立 git worktree (expensive!)
})
```

**回傳值**:
- 沒 `schema:` → 字串 (agent 最終訊息)
- 有 `schema:` → 已驗證的 object (runtime 幫你 JSON.parse + AJV validate)

### 5.2 `schema:` 行為 — **踩坑重點**

- `schema:` 強制 subagent 呼叫 `StructuredOutput` tool
- Agent 必須以 tool call 形式回 JSON,**不能用 plain text**
- 若 agent 回 text, runtime 會 retry 2 次 → 仍失敗 → **整個 workflow fail**

> **v2 踩坑**: workflow 用 `schema: B_SCHEMA` 給 B-review agent。
> 一個 B-review agent 多次返回 JSON-as-text,runtime throw:
> `agent({schema}): subagent completed without calling StructuredOutput (after 2 in-conversation nudges)`
> 整個 workflow 直接 fail。

> **v3 正確解法**: 移除 `schema:`,改用 balanced-brace JSON parser 自己解析 agent 回的 plain text:

```javascript
function balancedJsonAt(text, start) {
  if (text[start] !== '{' && text[start] !== '[') return null
  let depth = 0, inStr = false, esc = false
  for (let i = start; i < text.length; i++) {
    const c = text[i]
    if (esc) { esc = false; continue }
    if (c === '\\') { esc = true; continue }
    if (c === '"') { inStr = !inStr; continue }
    if (inStr) continue
    if (c === '{' || c === '[') depth++
    else if (c === '}' || c === ']') {
      depth--; if (depth === 0) return text.slice(start, i + 1)
    }
  }
  return null
}

function extractLastJson(text) {
  let last = null
  for (let i = 0; i < text.length; i++) {
    if (text[i] === '{' || text[i] === '[') {
      const block = balancedJsonAt(text, i)
      if (block) {
        try { last = JSON.parse(block); i += block.length - 1 } catch {}
      }
    }
  }
  return last
}
```

### 5.3 Schema 必須是 top-level const(踩坑)

> **v2 踩坑**: 在 `agent(prompt, { schema: { type:'object', properties:{...} } })` 裡
> 直接放複雜 inline schema 物件 → runtime parse error: `Unexpected token (330:62)`。

> **正確**: schema 必須是 top-level const:

```javascript
const B_SCHEMA = {
  type: 'object',
  properties: {
    review_status: { type: 'string', enum: ['APPROVE', 'REJECT'] },
    reason: { type: 'string' },
    citations: { type: 'array', items: { type: 'string' } },
    gaps: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['low', 'medium', 'high'] },
          message: { type: 'string' },
          fr_id: { type: ['string', 'null'] },
        },
        required: ['severity', 'message', 'fr_id'],
        additionalProperties: false,
      },
    },
  },
  required: ['review_status', 'reason', 'citations', 'gaps'],
  additionalProperties: false,
}
```

### 5.4 `parallel(thunks)` vs `pipeline(items, ...stages)`

| 函式 | 語義 | 用法 |
|------|------|------|
| `parallel([t1, t2, ...])` | 所有 thunks 並行,**barrier**:全部完成才回 | 需要 dedup 全部結果、early-exit |
| `pipeline(items, stage1, stage2, ...)` | 每個 item 跑完所有 stages,**stage 間不 barrier** | item 獨立任務串接 |

> **Pipeline by default** — Workflow tool 文件原文:
> "Only reach for a barrier (parallel between stages) when you genuinely need ALL prior-stage results together."

```javascript
// ✅ Pipeline(預設): 3 個 FR 各自 A→B→C,不互相等待
const results = await pipeline(
  frIds,
  fr => agent(`Author ${fr}`, { label: `a-${fr}`, phase: 'Author' }),
  rev => agent(`Review`, { label: `b-${rev.frId}`, phase: 'Review' }),
  fix => agent(`Fix`, { label: `c-${fix.frId}`, phase: 'Fix' }),
)

// ❌ Barrier (不必要): 全部 A 完才跑任何 B
const aResults = await parallel(frIds.map(fr => () => agent(`Author ${fr}`)))
const bResults = await parallel(aResults.map(a => () => agent(`Review ${a.frId}`)))
```

### 5.5 `phase(title)` 與 `log(message)`

```javascript
phase('Sub-Task 1/4 — SRS.md')   // 開始一個 phase box,後續 agent() 歸到這 box
log('SRS.md: Agent A + Agent B') // 顯示一行 narrator 訊息
```

### 5.6 `workflow(nameOrRef, args)` — 巢狀 workflow(只能一層)

```javascript
const result = await workflow('sub-helper', { some: 'input' })
```

- Nesting depth 限制 1 (workflow() 內不能再 workflow())
- 與 parent 共享 concurrency cap + agent counter + token budget

### 5.7 `args` 全域變數

- 由 `Workflow({ args: ... })` 傳入
- 可能是 string (JSON-encoded) 或 object (structured)
- **Workflow tool 文件說**: "Claude passes the list as structured data, so the script can call array and object methods on `args` directly without parsing it first"

> **踩坑**: 透過某些 Agent tool format 呼叫 `Workflow({ scriptPath: ... })` 時,**args 完全沒傳過去**
> (silently undefined)。解法:在 script 內設 default fallback:

```javascript
const DEFAULT_REPO = '/Users/johnny/projects/integration-test'
let REPO = DEFAULT_REPO
if (args && typeof args === 'object' && typeof args.repo === 'string') {
  REPO = args.repo
}
```

### 5.8 `budget` 物件(token budget tracking)

```javascript
while (budget.total && budget.remaining() > 50_000) {
  const result = await agent("Find bugs", { schema: BUG_SCHEMA })
  bugs.push(...result.bugs)
}
log(`${bugs.length} found, ${Math.round(budget.remaining()/1000)}k remaining`)
```

- `budget.total` = `null` 表示沒設 target
- `budget.spent()` = 整個 turn 主 loop + 所有 workflows 累計
- `budget.remaining()` = `Math.max(0, total - spent())` 或 `Infinity`(沒 target)

---

## 6. 啟動與管理 Workflow

### 6.1 三種 launch 方式

```javascript
Workflow({ script: "..." })                    // inline,debugging
Workflow({ scriptPath: "/abs/path.js" })      // 絕對路徑(推薦)
Workflow({ name: "phase1-requirements" })     // 用 name,從 .claude/workflows/ 找
```

### 6.2 /workflows view 控制

| Key | 動作 |
|-----|------|
| `↑` / `↓` | 選 phase 或 agent |
| `Enter` / `→` | 鑽進去看 prompt + tool calls + result |
| `Esc` | 退出 |
| `j` / `k` | 細節 overflow 時捲動 |
| `p` | pause / resume |
| `x` | 停選定 agent;若焦點在 run 則停整個 workflow |
| `r` | 重啟選定 agent |
| `s` | 存成可重用的 command |

### 6.3 Resume

```javascript
// Pause 後,workflow 內已完成 agent() 回傳 cached result;未跑的才 live 重跑
Workflow({ scriptPath, resumeFromRunId: "wf_xxx" })
```

- **限制**: 必須同 session;離開 Claude Code → 下個 session 從頭跑
- 為了 cache 命中,**script 不能改**;改了只 cache 到第一個改動的 agent() call

### 6.4 Permission prompt

| Permission mode | 啟動時是否問 |
|-----------------|-------------|
| Default / accept edits | 每次都問 (除非已 "don't ask again") |
| Auto | 第一次問,Yes 後記住;ultracode on 時跳過 |
| Bypass permissions / `claude -p` / Agent SDK | 從不問,直接跑 |

Subagent 永遠跑在 `acceptEdits` 模式,繼承你的 tool allowlist;檔案 edit 自動批准。

### 6.5 Name resolver cache bug(踩坑)

> **v2 踩坑**: shipped workflow 檔案已修改(27,123 bytes 新版),
> 但 runtime persisted 還是舊版(19,085 bytes 預先 snapshot)。
> 用 `Workflow({ name: 'phase1-requirements' })` 啟動 → 跑的還是舊版。

> **正確解法**: 用絕對路徑 `scriptPath:` 跳過 name resolver cache。

### 6.6 停不掉舊 run(踩坑)

Agent 工具**無法**直接停 workflow run。只能:
1. 請 user 在 `/workflows` view 按 `x`
2. 或讓 workflow 自己跑到出錯/完成

---

## 7. 子 Agent 與 Tool 行為

### 7.1 Agent 怎麼選 tool

`agentType` 影響可用 tool:
- `general-purpose` — 預設,全部工具
- `Explore` — read-only 搜尋(不可寫)
- `Plan` — read-only 設計規劃

**自訂 agent type** 透過 `subagent_type` (e.g. `Explore`, `code-reviewer`)。

### 7.2 Stateless agent sandbox(踩坑)

B-review agent **無 file access**。`Read` tool 也可能 hallucinate(見 §8.2)。

> **正確解法**: 將需要 review 的完整內容 **embed 在 prompt 內**,絕對不要只給路徑:

```javascript
function buildBPrompt(role, docs, checklist) {
  let p = 'You are ' + role + '.\n'
  p += 'You have NO access to any files — all context is provided below.\n\n'
  for (const [label, content] of docs) {
    p += '=== [' + label + '] ===\n' + content + '\n\n'
  }
  p += 'Review checklist:\n' + checklist + '\n\n'
  p += 'Return JSON only.'
  return p
}
```

### 7.3 Do-not 列表 — 防止 agent over-reach(踩坑)

> **v2 踩坑**: 一個 preflight agent 拿到含完整 P1 plan 的 prompt,
> general-purpose agent 判定「我可以全部做完」,3 分鐘做完整個 P1。

> **正確解法**: 每個 agent prompt 加明確的 **SCOPE RULES (DO NOT)**:

```javascript
const A_SCOPE_RULES = '\n\nSCOPE RULES (you MUST obey):\n'
  + '- DO NOT write any deliverable OTHER than the one specified in step 2.\n'
  + '- DO NOT run git commit, git push, advance-phase, push-checkpoint, or any phase-transition command.\n'
  + '- DO NOT run constitution-check, peer-review, or any quality-gate command.\n'
  + '- DO NOT spawn other agents or do the work of downstream sub-tasks.\n'
  + '- ONLY do steps 1-4 above. Return the JSON when done.\n'
```

---

## 8. 反覆踩過的真實坑(必讀)

### 8.1 P1 ❌ `import('node:fs')` 讓 shipped workflow 起不來

**症狀**: `import() is not available in workflow scripts`

**根因**: Script 想讀檔,寫了 `const fs = await import('node:fs')`。Validator 只 warn,runtime 直接 throw。

**正確解法**: Script 不做 I/O,改叫 `agent()` 帶 Bash tool:

```javascript
const fileContent = await agent(
  'Use Bash to run: cat /abs/path/file.md\n'
  + 'Return the EXACT stdout as your final message. No commentary.',
  { label: 'load-file', agentType: 'general-purpose' }
)
```

### 8.2 P2 ❌ Read tool 會 hallucinate 檔案內容

**症狀**: Brief loader agent 用 Read tool 讀 `PROJECT_BRIEF.md`,
回傳內容卻是 CLAUDE.md / memory 裡的描述(完全不同檔)。

**根因**: LLM agent 的 Read tool 拿到路徑後會用訓練資料「猜」內容;若同目錄有其他檔案,可能混淆。

**正確解法**: 用 Bash `cat` 取絕對位元組 — stdout 唯一通道就是檔案內容,LLM 無法替換:

```javascript
const brief = await agent(
  'Use ONLY the Bash tool. Run EXACTLY: cat ' + REPO + '/PROJECT_BRIEF.md\n'
  + 'Do NOT use Read tool. Return EXACT stdout.',
  { label: 'load-brief', agentType: 'general-purpose' }
)
// + defensive validation: 必須以 "# Project Brief" 開頭 + 長度 >=50
```

### 8.3 P3 ❌ B-review reject loop 沒 revise step → 無限循環

**症狀**: B-agent 一直 REJECT SRS,理由幾乎相同 (placeholder、NFR count)。
A 已經從 on-disk 讀檔返回正確內容,B 的高 severity gaps 是 reviewer 對「完整性」的過度解讀。Loop 跑滿 5 輪還沒收斂。

**正確解法**:
1. Loop 滿 `MAX_B_ROUNDS` 時 **ESCALATE**(return error),不要再 continue
2. A agent 在 round > 1 必須 review previous B-2 review JSON 並**套用 HIGH severity 修正**(surgical Edit,不是 rewrite)

### 8.4 P4 ❌ `schema:` 讓 B-review agent fail

**症狀**: `agent({schema}): subagent completed without calling StructuredOutput (after 2 in-conversation nudges)`
整個 workflow 直接 fail。

**根因**: `schema:` 強制 subagent 呼叫 StructuredOutput tool,不能用 plain text。
某些 B-review agent 偏偏就回 plain-text JSON。

**正確解法**: 移除 `schema:`,用 §5.2 的 balanced-brace parser 自己 parse。

### 8.5 P5 ❌ Schema 必須 top-level const

**症狀**: `Script parse error: Unexpected token (330:62)`

**根因**: Inline 複雜 schema 物件 → runtime parser 拒絕。

**正確解法**: 把所有 schema 提到 top-level `const`,如 §5.3 範例。

### 8.6 P6 ❌ Name resolver 給 stale cache

**症狀**: 改完 workflow 檔,launch 卻跑舊版。

**正確解法**: 用 `scriptPath: '/abs/path.js'` 而非 `name: 'xxx'`。

### 8.7 P7 ❌ Inline schema 改物件後忘了改 schema 物件定義

**症狀**: 改 `schema:` 物件失敗,runtime 報 unexpected token 但 line number 指錯位置。

**正確解法**: §5.3 — top-level const。

### 8.8 P8 ❌ args 不會自動 fallback,workflow 立即 fail

**症狀**: 透過 Agent 工具呼叫 `Workflow({ scriptPath: ... })` 完全沒帶 args → script 內 `args === undefined` → 立即 return error。

**正確解法**: §5.7 — script 內設 `DEFAULT_XXX` fallback。

### 8.9 P9 ❌ Agent 回「BAD JSON shape」繼續 retry 浪費 token

**症狀**: Round 1 agent 返回 invalid JSON (沒 `files[0].content`),script 只 log + continue,跑完整輪才 escalate。

**正確解法**: Parse failure 立即 hard error return,不要 retry(重試不會自己修好):

```javascript
try {
  a = parseAgentJson(aResult, 'A-r' + round)
} catch (e) {
  return { error: 'A parse failed (round ' + round + ')', detail: e.message }
}
```

### 8.11 P11 ❌ TaskStop 殺死 agent → journal result 未寫入 → resume 重複執行

**症狀**: Agent 完成工作（已寫檔案、已回傳 JSON），但 journal 只有 STARTED 沒有 RESULT。Resume 時 agent 被重試。常見於「agent 在主 context 呼叫 TaskStop 時剛好完成最後一步但 runtime 還沒 flush journal」。

**影響**: Agent 重跑一次（通常很快，因為 self-check pattern 會看到檔案已存在），但浪費 token 且 wall-clock 增加。

**正確處理**:
1. **不要在 agent 跑到一半時呼叫 TaskStop**。只在確認 workflow task 已完成（收到通知）或明確中止整個流程時才停。
2. Resume 是無害的：重試 agent 只是重讀已存在的檔案並快速回傳 OK。
3. **設計 Agent A 為冪等**：先 `test -f <file>` → 若 EXISTS 就直接讀 + return OK，不 overwrite。

```javascript
// ✅ Agent A 冪等範例
'1. Self-check: test -f ' + REPO + '/02-architecture/SAD.md && echo EXISTS || echo MISSING\n'
+ '   - If EXISTS: Read it. If complete, return OK without rewriting.\n'
+ '2. If MISSING: author the full deliverable.\n'
+ 'Return compact JSON only.\n'
```

### 8.10 P10 ❌ 兩個 workflow run 競爭同一組 deliverables

**症狀**: 舊 v2 run 還在跑、新的 v3 又 launch → 兩 run 互相覆寫同一個 SRS.md,內容不一致。

**正確解法**: User 必須手動 `/workflows` view 按 `x` 停舊 run。Agent 工具沒 API 可停 workflow。

---

## 9. 設計模式 — 從四輪迭代萃取

### 9.1 HybridWorkflow(HR-04)

- Agent A 負責 author(寫 deliverable)
- Agent B 負責 review(評 A 的產出)
- **絕不自己 role-play A 或 B**(orchestrator 只看 result)

### 9.2 STATELESS B-review sandbox

- B 無 file access → 必須 embed 完整 doc 內容在 prompt
- 這是「force function」:迫使 B 不依賴外部狀態,review 可重現

### 9.3 A self-check pattern

- Round 1: A 先 `test -f <deliverable>`,如果存在就 Read + return JSON(快速通過)
- Round > 1: A 先 review previous B-2 review JSON,套用 HIGH severity 修正,surgical Edit
- 避免 A 每次都 overwrite 整個檔案(surgical 才不會破壞既有合約)

### 9.4 B-2 loop logic(HR-12 + phase1_plan.md B-2)

```
APPROVE + all gaps low          → break (continue to next sub-task)
APPROVE + any med/high gap      → A fixes → re-dispatch B (round 2)
REJECT                           → A fixes → re-dispatch B
MAX_B_ROUNDS (5) without resolve → ESCALATE (hard return error, not silent break)
```

### 9.10 Compact JSON + disk read pattern（Agent A 禁止嵌入檔案內容）

Agent A 在 JSON response 內嵌入完整檔案內容 → 輸出 token 超限 → JSON 截斷 → orchestrator 拿到 null → abLoop 誤認為失敗。

**規則**: Agent A 的 JSON response **禁止**包含 `files[].content`。orchestrator 自己從磁碟讀。

```javascript
// ✅ 正確：compact JSON + 分開讀磁碟
// Agent A prompt 結尾:
'Return ONLY this compact JSON — do NOT embed file content (content is read from disk separately):\n'
+ '{"status":"OK","confidence":"high|medium|low","citations":["..."],"summary":"<1-2 lines>"}\n'

// Orchestrator 拿到 aResult 後:
let a
try { a = parseAgentJson(aResult, 'A-sad-r' + round) }
catch (e) { log('A JSON parse fail (likely truncated): ' + e.message.slice(0, 80)); a = null }
// 不論 a 是否 null，都從磁碟讀內容:
content = await loadFileViaBash(cfg.diskPath, cfg.diskPrefix || '', cfg.phaseName)
if (content.startsWith('ERROR:') || content.length < 50) {
  return { error: cfg.deliverable + ' not found on disk after A' }
}
```

**附加防護**: `loadFileViaBash` 加 `expectPrefix` 驗證，防止 agent 讀到錯誤檔案：

```javascript
async function loadFileViaBash(relPath, expectPrefix, phaseName) {
  const res = await agent(`cat ${REPO}/${relPath}`, { model: 'haiku', ... })
  const content = (typeof res === 'string' ? res : String(res ?? '')).trim()
  if (expectPrefix && content.length > 50 && !content.startsWith(expectPrefix) && !content.startsWith('ERROR:')) {
    return 'ERROR: content-mismatch — expected prefix "' + expectPrefix + '", got: ' + content.slice(0, 120)
  }
  return content
}
// 呼叫時指定各 deliverable 的前綴:
// SAD.md → '# SAD'
// adr/ADR.md → '# Architecture Decision Records'
// TEST_SPEC.md → '#'
```

### 9.5 Bash cat > Read tool for content loading

```javascript
// ✅ Reliable: bash cat (stdout = exact bytes)
const content = await agent(`Use ONLY Bash. Run: cat ${PATH}. Return stdout verbatim.`, opts)

// ❌ Unreliable: Read tool (LLM may hallucinate)
const content = await agent(`Use Read tool on ${PATH}. Return content.`, opts)
```

### 9.6 模型選擇(cost optimization)

```javascript
{ agentType: 'general-purpose' }              // 預設,用 session model
{ model: 'haiku' }                            // 6x 便宜,給 B-review 用
{ model: 'haiku', effort: 'low' }             // 更省
```

### 9.7 Preflight agent 要 super narrow

> 不給 preflight agent 看完整 P1 plan;只給「跑 3 個 bash 命令並回報」。
> 這樣它不會自行決定「既然能跑完,就全做完吧」。

### 9.8 Push + Advance 拆兩階段(per phase1_plan.md)

```javascript
phase('Push');     // push-checkpoint --phase 1 (retry until success, no --no-verify)
phase('Advance');  // advance-phase --completed 1 + verify HANDOVER.md
```

Push 沒成功就不 advance;Advance 失敗就保留 P1 狀態由人工介入。

### 9.9 Subagent prompt 結構樣板

```
You are <ROLE>. Your task: <ONE-LINE TASK>.
You have NO access to any files — all context is provided below.

=== [DOC 1: <LABEL>] ===
<content>

=== [DOC 2: <LABEL>] ===
<content>

<CHECKLIST_OR_INSTRUCTIONS>

SCOPE RULES (you MUST obey):
- DO NOT <bad action 1>
- DO NOT <bad action 2>
- ONLY do <good action 1> through <good action N>.

Return JSON only:
{...schema...}
```

---

## 10. 監看與調試

### 10.1 找到 run 狀態

```
/workflows    # 列出所有 run,選一個鑽進去看
```

每個 run:
- Phase box(顯示 agent count + token total + elapsed time)
- Agent detail: prompt、recent tool calls、result

### 10.2 Transcript 路徑

每個 run 的 script + 每個 agent 的逐字 transcript 寫到:

```
~/.claude/projects/<session-hash>/subagents/workflows/<run-id>/
  journal.jsonl                           # script 的 started/result 事件
  agent-<uuid>.jsonl                      # 該 agent 的完整 message log
  agent-<uuid>.meta.json                  # {agentType: 'general-purpose'}
```

讀 journal 找失敗根因:

```bash
JOURNAL=~/.claude/projects/<session>/subagents/workflows/wf_xxx/journal.jsonl
grep '"type":"result"' $JOURNAL | python3 -c "
import json, sys
for line in sys.stdin:
    d = json.loads(line)
    r = d.get('result', {})
    print(f\"{d['agentId'][:12]}: status={r.get('review_status') or r.get('status')} gaps={len(r.get('gaps') or [])}\")
"
```

### 10.3 用 validator 預檢 script

```bash
# /tmp/validate-workflow.mjs 是 ray-amjad/claude-code-workflow-creator 官方 validator 副本
node /tmp/validate-workflow.mjs /abs/path/workflow.js

# 輸出:
# ok — phase1-requirements.js passes (36539 bytes)
# 3 error(s) in xxx.js — fix before running.
```

### 10.4 Token 估算(節錄自 v4 經驗)

| Phase | Agents | Tokens |
|-------|--------|--------|
| Preflight | 1 | 15-25k |
| Brief loader | 1 | 5k |
| 4 × (A-read + B-review) | 8 | 40k |
| Constitution check | 1 | 5-10k |
| Peer review | 1 | 8-12k |
| Push + Advance | 2 | 30-50k |
| **小計(順利 1 輪)** | **14** | **~100-150k** |

若 B 反覆 REJECT,每多一輪 +30k。設 budget cap 避免失控。

---

## 11. Turn off / Disable

若不想用 workflow:

| 方式 | 範圍 | 持續 |
|------|------|------|
| `/config` → 關閉 "Dynamic workflows" | 個人 | 永久 |
| `~/.claude/settings.json` 加 `"disableWorkflows": true` | 個人 | 永久 |
| 環境變數 `CLAUDE_CODE_DISABLE_WORKFLOWS=1` | 該啟動 | session |

關閉後 `/deep-research` 不可用、`ultracode` 關鍵字無效。

---

## 12. 速查表

| 我想做... | 做法 |
|----------|------|
| 寫新 workflow | 1. 寫 `.claude/workflows/<name>.js` (export const meta 第一行)<br>2. `node /tmp/validate-workflow.mjs <path>`<br>3. `Workflow({ scriptPath: '/abs/path' })` |
| 改 workflow | `Workflow({ scriptPath, resumeFromRunId: 'wf_old' })` cache 命中已完成部分 |
| 停 workflow | 請 user 在 `/workflows` view 按 `x` |
| 監看 | `/workflows` |
| B-review | stateless prompt,完整 embed 文件 |
| 讀檔 | Bash cat (不用 Read tool) |
| 解析 agent JSON | balanced-brace parser(若用 schema: 風險見 §5.2/§8.4) |
| 省 token | B-review 用 `model: 'haiku'` |
| 防 over-reach | 加 SCOPE RULES (DO NOT) |
| Parse failure | 立即 hard error,不要 retry |

---

## 附錄 A: integration-test 真實案例時序

| 版本 | 症狀 | 根因 | 修法 |
|------|------|------|------|
| **v1** shipped | `import() is not available in workflow scripts` | `const fs = await import('node:fs')` 想要 fs I/O | 全移除,改叫 agent() |
| **v1** shipped | `Script parse error: Unexpected token (330:62)` | inline schema 太複雜 | schema 提到 top-level const |
| **v2** | general-purpose preflight agent 3 分鐘做完 P1 | prompt 包含完整 P1 plan | 加 SCOPE RULES DO-NOT |
| **v2** run | name resolver cache 給舊版 | shipped file 已 cp 但 runtime persisted 預先 snapshot | `Workflow({ scriptPath })` 取代 `name` |
| **v2** run | `subagent completed without calling StructuredOutput` | `schema:` 強制 tool call,某 agent 回 text | 移除 `schema:`,改 balanced-brace parser |
| **v3** run | B-review 無限 REJECT(>3 輪) | Brief loader agent 用 Read tool 讀 PROJECT_BRIEF.md,回傳 hallucinated 內容(來自 CLAUDE.md / memory) | 改 Bash `cat` + 加 defensive validation |
| **v4** run | (進行中) | — | — |

## 附錄 B: 官方/社群資源

- 官方手冊: https://code.claude.com/docs/en/workflows
- 文件索引: https://code.claude.com/docs/llms.txt
- Validator 來源: https://github.com/ray-amjad/claude-code-workflow-creator (main/scripts/validate-workflow.mjs)
- Subagent 文件: https://code.claude.com/docs/en/sub-agents
- 設定文件: https://code.claude.com/docs/en/settings
- 權限模式: https://code.claude.com/docs/en/permission-modes

---

## 附錄 C: Phase 1 workflow v17 → v33b 完整踩坑盤點 (2026-06-28..29)

**範圍**：本輪 P1 workflow 從「sub-task approval 寫入失敗」到「advance-phase PASS」,橫跨 17 個 commit + 9 個 workflow run。僅列**已驗證事實**（commit hash / transcript log / disk state / harness test suite）。未證實的歸因標 [UNVERIFIED]。

### C.0 鐵律總覽 (從本輪直接萃取)

1. **agent 是不可靠黑盒** — 任何多步驟指令 (multi-step MCP / multi-line bash / step-by-step prompt) 都會在大 context 退化。**只用單步 Bash tool-call** (cat / wc -c / read-file CLI + cat)。
2. **LLM emit 可靠性遞減序**：`single-line bash` > `MCP native tool` > `multi-line compound bash` > `multi-step instruction prompt`。workflow JS 的「殼」只挑前者。
3. **Retry 永遠在 orchestrator,不在 tool call 內** — AWS SDK / Stripe SDK / github-actions/retry-step 同樣原則。包 try/catch 重試整個 outer agent() 呼叫,不要在 single prompt 內嵌 for/if 迴圈。
4. **CLI 是 deterministic 邊界,workflow JS 是 orchestrator** — LLM 只做「shell wrapper」emit + cat relay,所有 prefix/length/SHA/JSON 驗證在 Python side (`harness_cli.py`)。
5. **diskPrefix 必須符合 file_loader Bug v8 契約** = first_line **startswith** expect_prefix,而非 contain。Markdown deliverable 的 caller 必須傳 `# Title` 完整,不能只傳 Title。
6. **每個 fix 必須有 smoke test + 1 個獨立 test suite 驗證** — fix loader → smoke test 4 個 deliverable + harness test_file_loader.py 全綠;fix approval → smoke test 寫入後 json.load() == dict。

### C.1 時序 (commit + run)

| commit | 症狀 | 根因 (已驗證) | 修法 |
|--------|------|---------------|------|
| `bc913a0` persist Agent B approval JSONs | 早期 advance-phase 缺 approval | 沒呼叫 persistApproval | 加 helper |
| `cd70f67` Bug v18/v19 + advance-phase PASSES P1→P2 | 多個 v17/v18/v19 bug | (見下表細項) | 多項 fix |
| `70544a9` v22 architectural fix — persistApproval routes through `harness_cli.py write-approval` | approval 寫入不可靠 | 直接 Edit node:fs 違反 sandbox | 路由 CLI;**6/6 advance-phase PASS** 黃金基線 |
| `3ee3dd5` v27 persistApproval retry-with-verify (compound bash) | v22 偶發 1/6 失敗 | wrap retry 寫成 12 行 compound bash | — |
| `c672591` v28 outer-level retry + mcp__filesystem__ | v27 4/4 → 2/4 regression | LLM emit reliability 在 multi-line indented compound bash 下降 | orchestrator-level try/catch 3次,單步 MCP tool |
| `7dd5cc0` v29 loadFileViaPython mcp__filesystem__read_file | loadFileViaBash 10% LLM hallucinate | Bash `cat` 殼子 LLM 幻覺 | 改 MCP native API |
| `7b97ab1` v30 revert persistApproval to v22 + outer retry; loadFileViaPython mcp+v16 fallback; Agent B schema 嚴格化 | v28 整體穩定但仍有小問題 | v28 persistApproval MCP path 在 sub-task stage 仍有 variance | 拆兩個問題各別修 |
| `02d0f18` v31 single-line JSON + single-quote wrap | persistApproval CLI 報 `invalid JSON payload: line 1 column 2` | zsh 把 `[...]` 當 glob 展開 → JSON word-split | 1) `JSON.stringify({...})` 無 indent → single-line; 2) shell cmd 字串內顯式 single-quote wrap |
| `cd45284` v32 loadFileViaPython fallback inline Python read (bypass CLI flag) | v31 smoke OK 但 run-time 仍 fail | `--content-out` flag 與 `--content` 旗標 argparse 衝突 | fallback 改 inline Python `open(argv[1]).read()` |
| **`c9d49ad` v33** drop MCP read; align diskPrefix with file_loader startswith | v32 run: Peer Review round 1 fail "mcp attempts exhausted reason=mcp-error" | 1) MCP 多步驟指令在大 context 退化; 2) 三個 markdown diskPrefix 漏 `#` 違反 startswith 契約 (被 MCP 繞過 file_loader 遮蔽) | 1) loadFileViaPython 回到單步 Bash `read-file + cat`; 2) diskPrefix 補 `# ` (3 處) |
| **`dd6b242` v33b** drop redundant JSON.stringify in persistApproval | v33 run: `data.get("review_status")` AttributeError on str (4/4 approval) | v31 commit 把 single-line JSON 的 `JSON.stringify(approvalPayload)` 多包一層,變 JSON string-of-string,CLI json.loads() 拿到 str 而非 dict | `escapedPayload = approvalPayload.replace(...)` 拿掉多餘的 `JSON.stringify` |
| `a3facb9` phase1(review-complete) | — | (handover 標記) | — |

### C.2 三個獨立真因 (v33 + v33b 治本)

#### 真因 1: MCP read 在大 context 不可靠 (v29 引入)

**症狀**：Peer Review round 1 load SRS.md fail, log:
```
[01-requirements/SRS.md] mcp attempts exhausted (reason=mcp-error)
[01-requirements/SRS.md] mcp attempts exhausted (reason=mcp-error)
[01-requirements/SRS.md] mcp attempts exhausted (reason=mcp-error)
ERROR: LOADER_FAILED_AFTER_3_ATTEMPTS + FALLBACK: 01-requirements/SRS.md
```

**同檔案 sub-task stage 正常 load** (14673 chars)。差異 = accumulated context size。

**根因** [部分 UNVERIFIED]：MCP 路徑 prompt 是多步驟指令 ("call mcp__filesystem__read_file → 轉述 bytes")。在大 context 下 sub-agent emit `ERROR_LOAD_FAILED` 不 invoke tool。具體 trigger (context size threshold / 累積效應) 未獨立驗證。

**為何 v30/v32 fallback 修不好**：fallback 本身也是 LLM-as-shell-wrapper (`open(sys.argv[1]).read()`),繼承同樣脆弱性 → fallback 也 fail。

**正解** (v33 `c9d49ad`)：放棄 MCP read,回到 v22 單步 Bash 模式:
```js
const pythonCmd = PY + ' ' + REPO + '/harness_cli.py read-file --file ' + JSON.stringify(filePath)
  + ' --expect-prefix ' + JSON.stringify(expectPrefix)
  + ' --content --content-out ' + contentOut + ' --json-out ' + jsonOut + ' --quiet'
// prompt: "Bash tool to run EXACTLY this command" + "Bash tool to run `cat <contentOut>`"
```
**為何穩定**：單步 Bash tool-call 是 dominant LLM pattern;`read-file` 在 Python 端做 prefix/length/SHA 驗證 server-side;`cat` 是另一個單步 Bash。

#### 真因 2: markdown diskPrefix 漏 `#` (違反 file_loader Bug v8 契約)

**症狀**：handover 拿到的磁盤檔案第一行是 `# Software Requirements Specification (SRS) — taskq`;workflow 傳 expect_prefix = `Software Requirements Specification`(無 `#`)→ `first_line.startswith(...)` False → `PREFIX_MISMATCH` → CLI 從不 emit content → 寫入 `contentOut` 跳過 → cat 失敗。

**為何 v29-v32 沒暴露**：MCP 繞過 file_loader。

**正解** (v33 `c9d49ad`)：phase1 三個 markdown diskPrefix 補回 `# ` (SRS/SPEC_TRACKING/TRACEABILITY)。TEST_INVENTORY 本就帶 `#` 不動。phase2 caller 本就帶 `#` 不動。

**契約文件** (harness/scripts/file_loader.py:178 + tests/test_file_loader.py:170-175 註解 + test `test_prefix_is_not_substring_search`):
```python
# Bug v8 regression: prefix MUST be at start of first line, not anywhere
# 防止 LLM agent 把 "fabricated content" 注入並 startswith 假 prefix
```

**所有 caller 一覽** (after v33):

| phase | deliverable | diskPrefix |
|-------|-------------|------------|
| 1 | SRS.md | `# Software Requirements Specification` |
| 1 | SPEC_TRACKING.md | `# Specification Tracking Matrix` |
| 1 | TRACEABILITY_MATRIX.md | `# Traceability Matrix` |
| 1 | TEST_INVENTORY.yaml | `# TEST_INVENTORY.yaml` |
| 2 | 02-architecture/SAD.md | `# SAD` |
| 2 | 02-architecture/adr/ADR.md | `# Architecture Decision Records` |
| 2 | 02-architecture/TEST_SPEC.md | `#` |
| 1 | PROJECT_BRIEF.md | `# Project Brief` |

**workflow JS 自身 anchorRe** (`loadFileViaPython` 內 `replace(/^#\s*/, '')`) 對帶不帶 `#` 都相容。

#### 真因 3: persistApproval 雙重 JSON encode (v31 引入)

**症狀**：v33 run transcript + advance-phase fail:
```
ADVANCE: FAIL — _verify_agent_b_approvals_core line 4224:
  data.get("review_status", "") on a string object
```

**磁盤檔案**：
```bash
$ head -c 80 .methodology/agent_b_approvals/SRS.md.json
"{\"fr\":\"SRS.md\",\"review_status\":\"APPROVE\"...   ← 開頭是 ",不是 {
$ python -c 'import json; print(type(json.load(open("...SRS.md.json"))))'
<class 'str'>                                          ← 應該是 dict
```

**根因** (`persistApproval` line 508, v31 commit `02d0f18` 引入):
```js
// line 489: approvalPayload = JSON.stringify({...})   // → JSON string (single-line, no indent)  ✓ 這是 v31 真正的 fix
// line 508: escapedPayload = JSON.stringify(approvalPayload).replace(/'/g, "'\\''")  // ✗ 多餘的第二次 stringify
```
- `approvalPayload` 已是 JSON string
- 第二次 `JSON.stringify()` 把整個 string 包成 JSON-encoded string (`"{\"fr\":...}"`)
- CLI 收到 `--json '"{\"fr\":...}"'` → `json.loads()` 解析成 `str`(不是 dict) → `tmp_path.write_text(json.dumps(str))` 寫出雙重 encode 內容
- CLI 自己的 verify 只看 `size >= 10 bytes`,**沒看內容形狀** → 顯示 "OK" 但內容錯 → advance-phase 才發現

**正解** (v33b `dd6b242`):
```js
const escapedPayload = approvalPayload.replace(/'/g, "'\\''")
```
- v31 的「single-line JSON」目標保留 (line 489 無 indent)
- 拿掉多餘的第二次 stringify
- CLI 收到 `--json '{"fr":...}'` → `json.loads()` 拿到 dict → 寫入正常

**為什麼 v22 沒這問題** [UNVERIFIED]：v22 persistApproval wrapper 不同 (直接 string template,沒經過 JS-side escape)。

### C.3 v17..v33b 期間曾經嘗試但失敗的修法 (不重蹈)

| 嘗試 | 為何失敗 |
|------|---------|
| v17 Bash cat agent 殼子 | 10% LLM hallucinate 內容,導致 docs_embedded dirty |
| v22 harness_cli.py read-file wrapper | CLI 本身 OK,但 LLM shell wrapper 仍有 10% 失敗 |
| v27 12 行 compound bash retry inside one agent() | 4/4 → 2/4 regression: multi-line bash LLM emit 不可靠 |
| v28 mcp__filesystem__write_file 取代 Bash | 解決 persistApproval 但**新引入** loadFileViaPython 不可靠 + Agent B 偶發 LLM emit variance |
| v29 全面 MCP read | 解決部分但 Peer Review 大 context fail |
| v30/v32 fallback 雙層 (MCP + inline Python) | fallback 是 LLM-shell-wrapper,繼承同脆弱性 |
| (錯誤嘗試) 把 file_loader 改成 `in first_line` (contain) | **破壞 Bug v8 契約**:`test_prefix_is_not_substring_search` 會 fail;且改 4 個 deliverable diskPrefix (補 `#`) 是更小、治本的修法 |

### C.4 共通性邊界 (守住,沒擴大破壞)

| 改動 | 影響 phase | 不動 |
|------|------------|------|
| `loadFileViaPython` Bash pattern | phase1 + phase2 鏡像 | harness `file_loader.py` (startswith 契約保留) |
| diskPrefix 補 `#` | phase1 三個 markdown (cfg + peerDocs 共 6 處) | phase2 caller 本就帶 `#`;workflow JS anchorRe 已容錯 |
| `persistApproval` 拿掉多餘 `JSON.stringify` | phase1 + phase2 鏡像 (line 304) | CLI 不動 (CLI 設計 `--json` 收 string,契約正確) |
| advance-phase CLI 契約 | — | 不該改 CLI 來容錯 str-not-dict (會 mask 真 bug) |

### C.5 Smoke test pattern (本輪標準化)

任何對 loader / approval / advance-phase 的 fix,都必須有:

1. **loader fix**：
   ```bash
   for f in <4 deliverable>; do
     harness_cli.py read-file --file $f --expect-prefix $p --content --content-out /tmp/out --json-out /tmp/json --quiet
     assert exit=0 + contentOut 寫入 + bytes 等於磁盤檔
   done
   harness tests/test_file_loader.py: 35 passed
   ```

2. **approval fix**：
   ```bash
   # 重現 v33b bug
   python -c "import json; open('.../SRS.md.json').read()[:1]" == '"'  # 會被驗成 string
   # post-fix
   python -c "import json; print(type(json.load(open('.../SRS.md.json'))))" == "<class 'dict'>"
   ```

3. **workflow fix**：完整 re-run → 預期 transcript 4/4 approval + advance-phase PASS + state.json current_phase +1

### C.6 教訓 (寫給未來開發者)

1. **不要為了修「次要問題」而改「已驗證主要路徑」** — v28 為修 persistApproval 偶發失敗而引入 MCP,結果破壞了 v22 已驗證的 loader 6/6 reliability。**先記住黃金基線 (v22: 6/6 PASS),再考慮任何偏離**。
2. **CLI 寫入成功 ≠ 寫入正確** — `write-approval` 只 verify `size >= 10 bytes`。任何對 persistApproval 的改動都必須**回讀 + `json.load()` 確認是 dict** 才算過。
3. **Bash 之後才 MCP** — 單步 Bash tool-call 是 dominant pattern,可靠度遠高於多步驟 MCP 指令。在 headless workflow run (MCP 不一定在) 下更明顯。
4. **diskPrefix 是契約,不是 hint** — file_loader 用 startswith 錨定 H1 防幻覺;workflow JS 改 caller 必須保留 `# ` 開頭,不能圖簡潔。
5. **commit message 必須誠實** — 不要寫「6/6 PASS 由於此 fix」之類無 transcript 佐證的因果;若 fix 真治本,smoke test + test suite + workflow re-run 全綠已足夠。
6. **每次 fix 改完先看 diff** — runtime artifact (state.json / approval JSON / deliverable) 不該跟 workflow JS 一起 commit;分開 commit 避免污染 review。

---

## 附錄 D: Phase 3-8 same-pattern 修復盤點 (2026-06-29)

**範圍**: 對 v33 (`c9d49ad`) + v33b (`dd6b242`) 同型 bug 在 phase3-8 workflow JS 的盤點與修法。4 個 bug class + 4 commits 計畫,實際只做 2 個 (Step 2 + Step 4 跳過,原因見每節)。

### D.0 盤點方法

1. 直接 grep phase3-8 6 個 workflow JS 對 v33/v33b 三個函數名稱 → **0 match**。phase3-8 完全不用 `loadFileViaPython` / `persistApproval` / `diskPrefix`,所以 v33 三個 fix 不重複做。
2. 派 Explore agent 盤點 phase3-8 自己的 I/O + approval 模式,找出 v33/v33b **同型**的 bug class。
3. 派 Plan agent 設計 4 個 class 的修法,並標明哪些是已被 Explore agent 證實 (有 log/line),哪些只是 Plan agent 推論。

### D.1 結果摘要

| Class | 計畫 | 實際 | commit | 跳過原因 |
|-------|------|------|--------|----------|
| A (frIds inlining) | p5:238 file-pointer | ✅ 做了 | `ae1bbc1` | — |
| B (outer try/catch around `agent()`) | 5 phases × ~24 wraps | ⏭️ 跳過 | — | **未驗證** — 沒有 transcript 證實 phase3-8 因 agent throw 而 abort。Plan agent 把嚴重度定為「中」是推論,不是事實。改 6 檔 ~200 行 diff 風險 > 收益。改為「追蹤, 待有 fail transcript 再修」 |
| C (workflow-side approval writer) | p6 重構 + `writeApprovalJson` helper | ✅ 做了 | `36a49c5` | — |
| D (multi-line compound bash collapse/split) | p6:130, p6:216, p8:281 | ⏭️ 跳過 | — | **未驗證** — 重新對位 plan 提的 3 個 line 後,只有 p6 Gate 4 step 2 (DA challenge) 算 v27 spirit 真因,但 Gate 4 是 critical path (失敗要整 phase6 重 run),改的風險高於收益。改為「追蹤, 待有 fail transcript 才修」 |

### D.2 Class A — p5:238 frIds file-pointer (`ae1bbc1`)

**真因** (已驗證): phase5 verification-docs prompt 內嵌 `frIds.join(', ')` 作為可讀 list。30+ FR 時 prompt 超窗 (v33 spirit)。

**修法**:
- 改用 `${ctxFile}` 檔案指標 + sub-agent 跑一行 Python sub-bash 列舉:
  ```js
  '` + PY + ' -c "import json,sys; d=json.load(open(\\'' + ctxFile + '\\')); [print(fr) for fr in d.get(\'fr_ids\',[])]"`'
  ```
- prompt 本身保持固定大小,FR list 從 ctxFile 在執行時讀取

**驗證**:
- `node --check` 過
- `ctxFile` 已在 p5:143 定義 (Load FRs)
- `frIds` 仍被 p5:190-203 (per-FR loop) + p5:195 (log) 用,沒破壞

**共通性**: p3:301 + p4:254 的 `gate1Pass.join(',')` 灌入 `--fr-ids A,B` argv **不修** (驗證過 `harness_cli.py push-milestone` line 10339 收 single comma-separated string,chunking 不可行 + 不算 v33 spirit)。

### D.3 Class B — outer try/catch around `agent()` (跳過)

**真因假設** (未驗證): Plan agent 推論 phase3-p5、p7、p8 的 Gate / per-FR loop 內 `agent()` 沒 try/catch wrap,若 agent throw (rate limit / transient API error) workflow 整 phase fail。

**為何跳過**:
1. **沒有 transcript 證據** — 沒找到 phase3-8 因 agent throw 而 abort 的紀錄
2. **v22/v28 spirit 是 retry 在 orchestrator** — 這些 phase 已有 `for (let round = 1; round <= 3; round++)` outer loop,**就是 orchestrator-level retry**;只是沒把 try/catch 包 `agent()`
3. **改 6 檔 ~24 wraps ≈ 200 行 diff** — 風險高,缺乏證據不該動
4. **p6 Gate 4 已有 try/catch** (line 119-144) 作為唯一先例 — 若真的有 throw 問題,p6 為何沒問題?

**追蹤位置**: 留 6 個 phase 的 per-FR + per-round loop 給未來真因證據 (例如某次 workflow run 出現 `agent() threw`,留下 transcript + 對應 phase 行號)。

### D.4 Class C — p6 workflow writes 4 approval JSON (`36a49c5`)

**真因** (已驗證): phase6 Peer Review 原本由 sub-agent 同時 review + 用 Write tool 寫 4 份 approval JSON (`QUALITY_REPORT.md.json`, `RELEASE_NOTES.md.json`, `FINAL_SIGN_OFF.md.json`, `quality_manifest.json`)。若 sub-agent 寫出 v33b 同型 double-encode (JSON string-of-string),CLI `write-approval` 的 `size >= 10 bytes` verify 過,advance-phase `_verify_agent_b_approvals_core` 才 `data.get("review_status")` on str → AttributeError (跟 v33b 同一條失敗路徑)。

**修法** (鏡像 phase1+phase2 `persistApproval` v33b 6/6 PASS):
1. 加 `writeApprovalJson(deliverableId, obj)` helper (line 32-67): 走 `harness_cli.py write-approval --json '...'`,shell-wrapper agent 跑命令,regex match `[write-approval]\s*OK`,outer 3-attempt retry
2. Peer Review 重構為 2 stage:
   - Stage 1: sub-agent 只 review 4 個 deliverable,回傳**結構化 JSON verdict** (parseAgentJson),不寫任何 file
   - Stage 2: workflow 對每個 verdict 呼叫 `writeApprovalJson` 4 次,workflow 自己寫 4 個 file

**docs_embedded 契約** (重要!): 每個 verdict 的 `docs_embedded` 必須列**所有 4 個 required embedded docs** (`QUALITY_REPORT.md`, `RELEASE_NOTES.md`, `FINAL_SIGN_OFF.md`, `VERIFICATION_REPORT.md`),不是只列被 review 的那個。`_verify_agent_b_approvals_core` 對**每個 verdict** 跑 `_REQUIRED_EMBEDDED_DOCS[6]` 集合 AND check,任一 required 缺就 fail。

**驗證**:
- `writeApprovalJson` smoke: 4/4 deliverable `exit=0`,寫入後 `json.load()` 是 dict,`review_status=APPROVE`
- `harness_cli.py verify-agent-b-approvals --phase 6` → ✓ All 4 Agent B approvals verified
- `node --check` 過

**共通性**: `writeApprovalJson` 是 phase1+phase2 `persistApproval` 的純鏡像,行為一致;helper 不耦合 phase 邏輯,可重複用於任何需要 workflow 寫 approval 的場景 (若未來加 phase 9/10)。

### D.5 Class D — multi-line compound bash collapse/split (跳過)

**真因假設** (部分驗證): Plan agent 標 3 個位置
- p6:130 (Gate 4 step 2 DA challenge multi-step)
- p6:216 (Release Docs 2 deliverables)
- p8:281 (TDD-PRECHECK multi-step)

**重新對位後的現況**:
- p6 Gate 4 現 line 174 — 6 個 sequential **單行** bash in 1 prompt (step 0-5),**不是 v27 spirit 的 multi-line compound** (v27 失敗是 12 行 nested for/if/then/sleep/break)
- p6 Release Docs 現 line 220 — 2 個 Write tool calls (不是 bash)
- p6 Peer Review 現 line 247 — 已由 commit 36a49c5 重構
- p8 final push 現 line 275 — 3 個 sequential 單行 bash,每個 in 自己 step,加上模糊列舉 5 個 tool 沒明確 step sequence

**為何跳過**:
1. **重新對位後,3 個位置只有 p6 Gate 4 step 2 (DA challenge) 算 v27 spirit 真因** — sub-agent 在 step 2 內部要 spawn 另一個 agent (claude sub-agent) + 寫 gate4_result.json,3 個 sequential logical operation in 1 prompt。但 Gate 4 是 critical path (失敗要整 phase6 重 run),改的風險高
2. **沒有 transcript 證實** — 沒看到 phase6 因 multi-line compound bash 而 fail
3. **p8 final push 的模糊列舉** (「confirm gitleaks + ruff + mypy + pytest + spec-coverage all pass. Fix blockers」) 確實是改進點,但屬於「clearer instruction」不是 bug fix

**追蹤位置**:
- p6 Gate 4 step 2 — 若某次 run transcript 看到 DA challenge evidence 寫入不完整,拆 sub-agent
- p8 final push step 1 — 若某次 run transcript 看到 TDD-PRECHECK 只跑部分 tool,改用 explicit numbered sub-steps

### D.6 共通性邊界 (守住)

| 改動 | 影響 phase | 不動 |
|------|------------|--------|
| p5:238 file-pointer | p5 only | p3/p4 argv chunking (CLI 不支持 + 非 v33 spirit) |
| p6 Peer Review 重構 + `writeApprovalJson` helper | p6 only | p1+phase2 helper (v33b 6/6 PASS 維持) |
| Class B/D (跳過) | — | 6 phases per-FR loop / Gate 4 / final push 都保留現狀 |

### D.7 教訓 (本輪)

1. **Plan agent 的「嚴重度」標籤要質疑** — Plan agent 把 Class B/D 都標「中」,但只靠推論,沒有 transcript。實作前**必須**問:有沒有 fail log 支持這個嚴重度?若沒有,**未驗證的修法風險 > 收益**。
2. **line 號要重新對位** — 改一個檔案(line number 改變)後,Plan agent 提的「line X」就 stale,必須重 grep 找現位置。本輪 Plan agent 提的 p6:130/p6:216 在 commit 36a49c5 後已不存在。
3. **CLI argparse 契約要驗證** — 假設某 CLI option 支持重複 args (chunking) 是常見錯誤,argparse 行為要直接看原始碼。Plan agent 提的 `--fr-ids A,B --fr-ids C,D` 會 fail,因為 `push-milestone` line 10339 收 single string。
4. **v33/v33b fix 的共通性盤點要分兩層** — 一層是「同函數」(phase3-8 沒這些函數,盤點結果 0);一層是「同型 bug class」(大 context / multi-line bash / sub-agent write JSON)。本輪發現的 4 個 class 都是後者。
5. **修一個 bug,可能暴露另一個契約** — 寫 Class C 時,symptom 測出 `_REQUIRED_EMBEDDED_DOCS[6]` 要求每個 verdict 列所有 required docs,不是只列自己 review 的那個。這個契約原本被 sub-agent 自由發揮的 Write tool 隱藏,workflow 接手後契約立即浮現。


