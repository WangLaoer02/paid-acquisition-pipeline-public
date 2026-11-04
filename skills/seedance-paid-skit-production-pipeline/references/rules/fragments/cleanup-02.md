## 输入
- `scope`：workspace／page／database／subtree；只在用户授权范围内处理。
- `cleanup_mode`：conservative／strict；未指定时保守处理。strict 不扩大删除权限，不绕过保护项和 REVIEW。
- `target_patterns`：可选候选检索模式，不等于删除授权。
- `protected_fields`：可选附加保护字段，不得削弱内置业务、附件、关系和执行规则保护。
- `preserve_audit_history`：默认 true；保留有审计价值的历史。明确要求不保留也须核验范围和依赖，不自动删除业务事实或必要来源链。
