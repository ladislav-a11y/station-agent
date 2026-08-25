# Development Protocol

## PowerShell workflow

- Always work step by step.
- One modification command at a time.
- After every command wait for verification output.
- Never combine multiple risky operations.

## Code changes

Before changing code:
1. Inspect the relevant file section.
2. Understand the current implementation.
3. Make one focused change.
4. Run targeted tests.
5. Run full test suite after stabilization.

## Editing rules

Avoid:
- complex PowerShell escaping
- regex edits through nested string replacements
- blind search and replace without validation

Prefer:
- exact block replacement with validation
- manual inspection
- git diff after changes

## Testing

After modifications:
- run py_compile for changed Python files
- run relevant pytest tests
- run full pytest before committing

## Debugging

When an error appears:
1. Stop modifying.
2. Identify the failing layer.
3. Make one correction only.
4. Verify.

## Communication

The assistant provides:
- one actionable step at a time
- exact PowerShell commands
- waits for command output before continuing
