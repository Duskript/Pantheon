# Reading JSX/TSX Source Files — Angle-Bracket Mangling

## The problem

`cat`, `read_file`, and similar tools silently strip or mangle JSX/TSX angle-bracket content. When reading a React component file, JSX like `<TaskDetailDrawer task={selectedTask} />` may appear as blank lines or truncated content.

This affects:
- `read_file` (Hermes tool)
- `mcp_filesystem_read_text_file`
- `cat` in terminal
- Most text-reading tools that attempt to parse angle brackets as HTML/XML

## The workaround

Use `awk` with explicit line-by-line printing. The `printf` format prevents any interpretation:

```bash
awk 'NR>=237 && NR<=260 {printf "LINE %d: |%s|\n", NR, $0}' src/kanban/board.tsx
```

This prints each line with a pipe-delimited format that makes angle brackets visible:

```
LINE 242: |        <TaskDetailDrawer|
LINE 243: |          task={selectedTask}|
LINE 244: |          isOpen={selectedTask !== null}|
LINE 245: |          onClose={handleDrawerClose}|
LINE 246: |        >|
```

## Alternative: `xxd` hex dump

When awk is insufficient (nested angle brackets, binary characters):

```bash
xxd src/kanban/board.tsx | grep -n "offset_pattern"
```

Decode the hex manually or with `xxd -r`.

## Alternative: `git show` piped to `awk`

When verifying committed code (not working tree):

```bash
git show HEAD:src/kanban/board.tsx | awk 'NR>=237 && NR<=260 {printf "LINE %d: |%s|\n", NR, $0}'
```

## When to use this

- Tier-1 code review when `read_file` returns blank lines where JSX should be
- Verifying that a component renders expected JSX children
- Debugging "component is imported but not rendered" claims that turn out to be tool artifacts

## Pitfall

This workaround is for READING files. Never use it to verify file correctness — use `npx tsc --noEmit` and the test suite. The workaround confirms "the code is there, the tool is lying." It does not confirm the code is correct.
