# Coze 规则查询接口

## `GET /api/audit-rules`

| 项 | 值 |
|---|---|
| 方法 | GET |
| 鉴权 | 无 |
| 参数 | `contract_type`（默认 `"通用"`） |
| 地址 | `http://complass-service:8080/api/audit-rules?contract_type=采购合同` |

**查询逻辑：**

| contract_type | 返回规则 |
|---|---|
| 采购合同 | 通用 + 采购合同专项 |
| 服务合同 | 通用 + 服务合同专项 |
| 合作协议 | 通用 + 合作协议专项 |
| 其他 / 空 | 仅通用 |

**返回结构：**

```json
{
  "finance_rules":    [{ "rule_id": "COM-FIN-001", "module": "财务", ... }],
  "legal_rules":      [{ "rule_id": "COM-LAW-001", "module": "法务", ... }],
  "performance_rules":[{ "rule_id": "COM-PER-001", "module": "履约", ... }],
  "other_rules":      [],
  "debug_info": {
    "total_count": 40,
    "common_count": 20,
    "specific_count": 20,
    "finance_count": 14,
    "legal_count": 13,
    "performance_count": 13
  }
}
```

**规则字段：** `rule_id` / `contract_type` / `module` / `risk_name` / `check_point` / `trigger_condition` / `default_risk_level` / `suggestion_template` / `example_clause`

**预期数量：**

| 合同类型 | 总数 |
|---|---|
| 采购合同 | 40 |
| 服务合同 | 39 |
| 合作协议 | 36 |
| 其他 | 20 |

---

## 审查工作流入参变更（v0.3）

```diff
{
  "file_id": "...",
- "contract_type": "通用",
- "rule_version_id": "...",
- "rules": [...],
  "sanitized_text": "...",
  "sanitization_enabled": true,
+ "audit_rules_api_url": "http://complass-service:8080/api/audit-rules"
}
```

规则不再由后端传入，Coze 判断合同类型后自行调 `audit_rules_api_url` 获取。
