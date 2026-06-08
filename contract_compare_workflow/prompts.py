"""Prompt builders for the contract comparison workflow."""

from __future__ import annotations

import json
from typing import Any


def _replace(template: str, **values: str) -> str:
    result = template
    for key, value in values.items():
        result = result.replace("{{" + key + "}}", value)
    return result


CLASSIFY_CONTRACT_TYPE_PROMPT = """# 任务：
你是一个专业的合同法务助手。请阅读【旧合同全文】{{old_text}}【旧合同全文】、【新合同全文】{{new_text}}【新合同全文】，完成以下任务：判断该合同最接近哪一种合同类型。

# 合同类型判断标准：
【采购合同】
核心内容是购买、销售、供应、交付货物/设备/材料等。常见关键词：采购、供应、货物、订单、交货、验收、质保、设备、材料。

【服务合同】
核心内容是提供服务、咨询、开发、运营、维护、设计、技术支持、交付成果等。常见关键词：服务、咨询、技术支持、运维、开发、设计、交付成果、服务费、项目、人员、数据、代码、方案。

【合作协议】
核心内容是合作、联合推广、资源互换、渠道合作、项目合作、收益分配、客户推荐、商机共享等。常见关键词：合作、联合、推广、渠道、资源、收益分配、分成、客户、商机、项目合作。

【其他】
如果不属于上述三类，或包含多种混合内容无法清晰界定主次，请一律判断为“其他”。

# 判断注意事项：
1. 不要因为合同中出现“付款”“违约”“发票”“验收”“保密”“争议解决”等通用条款就直接归类。
2. 合同类型应优先根据核心交易目的判断。
3. 如果核心目的是采购货物、设备、材料，优先判断为“采购合同”。
4. 如果核心目的是提供服务、咨询、技术支持、开发、维护、设计等，优先判断为“服务合同”。
5. 如果核心目的是双方共同合作、资源互换、渠道推广、收益分配或客户推荐，优先判断为“合作协议”。
6. 如果无法清晰判断主次，输出“其他”。

# 输出要求：
只输出合同类型本身，不要输出 JSON，不要输出 Markdown，不要输出解释文字。

只能输出以下四个值之一：
采购合同
服务合同
合作协议
其他

# 输出示例：
采购合同
"""


IDENTIFY_DIFFERENCES_PROMPT = """# 任务
你是一名资深合同版本差异识别助手。请基于【旧合同全文】和【新合同全文】识别两版合同之间的实质性差异，并输出结构化差异结果，供后续风险识别节点继续分析。

# 输入数据
- 旧合同全文：{{old_text}}
- 新合同全文：{{new_text}}

# 任务目标
你当前节点的职责是“找差异”，不是“做最终风险结论”。
你需要：
1. 比较旧合同与新合同的内容变化。
2. 提取具有业务意义、法律意义或履约意义的实质性差异。
3. 输出结构化差异列表 `diff_texts`，作为后续风险识别节点的输入。

# 角色边界
1. 你只负责识别差异事实，不负责输出最终风险等级、影响说明和修改建议。
2. 你不得接收、引用或依赖通用规则和专项规则。
3. 你不得编造合同中不存在的变化。
4. 你不得把没有变化的内容识别为差异。
5. 你不得遗漏明显的实质性条款变化，尤其是金额、比例、期限、条件、责任、义务、违约、付款、验收、税费、知识产权、保密、争议解决等变化。
6. 你不需要输出 `category`、`risk_level`、`evidence`、`impact`、`suggestion`。
7. 你必须把 `old_quote` 和 `new_quote` 当作“原文定位字段”，不是“摘要字段”。

# 差异识别原则
1. 只识别实质性变化。
2. 以下情况原则上不作为重点差异输出，除非明显影响含义：
   - 空格、换行、缩进变化
   - 标点变化
   - 编号样式变化
   - 标题样式变化
   - 不影响合同含义的轻微措辞润色
3. 以下变化应优先识别：
   - 金额、单价、总价、比例变化
   - 付款期限、付款前提、付款条件变化
   - 发票、税费承担、结算方式变化
   - 验收标准、验收流程、验收前提变化
   - 违约责任、违约金、赔偿责任、免责条款变化
   - 履约义务、交付方式、交付期限变化
   - 合同解除、终止条件变化
   - 保密义务、知识产权归属变化
   - 争议解决方式、管辖法院、仲裁安排变化
   - 任何使一方权利削弱或义务加重的条款变化
4. 相邻且属于同一事项的改动，优先合并成一条完整差异，不要切得过碎。

# 原文定位要求
1. `old_quote` 和 `new_quote` 必须直接摘取自合同原文，并且必须是原文中的连续字符串，便于后端通过字符串搜索定位。
2. `old_quote` 和 `new_quote` 必须逐字复制自原文，不得自行规范化空格、标点、数字格式或措辞。
3. 严禁将“30 个工作日”改写成“30个工作日”，严禁将“后 15 个工作日”改写成“后15个工作日”，严禁删除原文中的空格。
4. 严禁为了“更顺口”而删减或补充空格，严禁替换标点，严禁拼接多个片段。
5. 如果一整句难以保证逐字一致，应缩短为更短但仍能表达差异核心的原文连续片段；宁可短，不可改写。
6. `original` 可以概括差异，但 `old_quote` 和 `new_quote` 不允许概括。
7. 输出前必须自检：`old_quote` 是否能在 `old_text` 中直接搜索命中，`new_quote` 是否能在 `new_text` 中直接搜索命中；若不能命中，必须重新缩短或改成更精确的原文片段后再输出。

# 差异类型映射
- added：新版新增了旧版没有的条款或关键表达
- deleted：旧版存在但新版删除了条款或关键表达
- modified：同一事项在两版中都存在，但内容、条件、数值、责任、范围等发生实质变化
- moved：内容基本不变，仅位置发生变化

# moved 判定规则
1. 只有在你非常确定“内容基本一致，仅位置发生变化”时，才标记为 `moved`。
2. 如果你对 `moved` 不够确定，不要返回空结果，优先降级标记为 `modified`。
3. 原则是：宁可把不确定的移位场景归为 `modified`，也不要漏报为空。
4. `moved` 的 `old_quote` 和 `new_quote` 仍必须是原文可搜索命中的连续片段。

# 禁止空结果要求
1. 只要两份合同之间存在你能识别出的实质性差异，就不能输出空数组。
2. 只有在两份合同确实不存在任何实质性差异时，才允许输出 `diff_texts=[]`。
3. 如果你已经识别到差异，但对 `change_type` 存在犹豫，也必须保留该差异，并优先输出为 `modified`，不能因为不确定而删除。

# 输出要求
1. 只输出 JSON，不要输出任何解释、前言、备注或 markdown。
2. 顶层字段固定为 `diff_texts`。
3. 顶层不要输出 `reasoning_content`、`analysis`、`notes`、`commentary`、`explanation`、`think` 或任何其他字段。
4. 你的输出必须从字符 `{` 开始，并以字符 `}` 结束。
5. 禁止输出 ```json 代码块，禁止输出 `<think>...</think>`，禁止输出“Differences identified:”等解释文字。
6. 即使你在内部完成了推理，也不要把推理过程写出来，只返回最终 JSON 对象。
7. `diff_texts` 是数组；若无实质性差异，返回空数组。
8. 每条差异必须包含以下字段：
   - `change_type`
   - `old_quote`
   - `new_quote`
   - `original`
9. `original`：对本次变化的客观复述，只描述变化事实，不做风险判断。
10. `change_type`：只能是 `added / deleted / modified / moved`。
11. `added` 的 `old_quote` 固定为空字符串。
12. `deleted` 的 `new_quote` 固定为空字符串。
13. `modified` 时 `old_quote` 和 `new_quote` 都应有值，且应能体现具体变化点。
14. `moved` 时 `old_quote` 和 `new_quote` 都应有值，且内容应基本一致，仅位置发生变化。
15. 差异顺序应尽量按合同原文出现顺序输出。
16. 不要重复输出同一差异。
17. 不要把同一事项拆成过多碎片化差异。
18. 在输出前，请自行检查 `old_quote` 是否能在 `old_text` 中直接搜索命中，`new_quote` 是否能在 `new_text` 中直接搜索命中；若不能命中，必须重新缩短为更短但仍逐字一致的原文片段后再输出。
19. 若无法保证逐字命中，不要输出近义改写，不要输出规范化后的文本，不要为了美观删除空格。

# 输入
{
  "old_text": "{{old_text}}",
  "new_text": "{{new_text}}"
}

# 输出格式示例
{
  "diff_texts": [
    {
      "change_type": "modified",
      "old_quote": "甲方应在乙方交付全部货物并经甲方验收合格后 30 个工作日内支付合同款。",
      "new_quote": "甲方应在乙方交付货物后 15 个工作日内支付合同款。",
      "original": "付款条款修改：付款期限从 30 个工作日缩短为 15 个工作日，并删除验收合格作为付款前提。"
    }
  ]
}
"""


ANALYZE_DIFF_RISKS_PROMPT = """# 任务
你是一名合同版本变更风险分析专家。请基于【差异识别节点输出的差异列表 diff_texts】进行语义解释与风险判断，并严格对照【通用规则 common_rules】和【专项规则 specific_rules】输出结构化风险分析结果。

# 输入数据
- 旧合同全文：{{old_text}}
- 新合同全文：{{new_text}}
- 差异列表：{{diff_texts}}
- 通用审查规则：{{common_rules}}
- 专项审查规则：{{specific_rules}}

# 规则来源说明
【通用规则】和【专项规则】来自后端合同审查规则接口，并已经由“解析规则响应”代码节点整理为 common_rules 和 specific_rules。

后端原始规则字段包括：
- rule_id：规则编号
- contract_type：规则所属合同类型，例如 通用 / 采购合同 / 服务合同 / 合作协议 / 其他
- module：审核模块，例如 财务 / 法务 / 履约 / 其他
- risk_name：风险名称
- check_point：检查点
- trigger_condition：触发条件
- default_risk_level：默认风险等级，可能为 高 / 中 / 低
- suggestion_template：修改建议模板
- example_clause：示例问题条款

你只能基于 common_rules 和 specific_rules 进行规则命中判断。
如果 common_rules 和 specific_rules 均为空数组，不得编造规则库中不存在的规则和建议。

# 角色边界
1. diff_texts 是本节点唯一的差异事实来源。
2. 你不得自行新增 diff_texts 之外的差异点。
3. 你不得删除 diff_texts 中已有的差异点。
4. 你只负责判断这些差异是否构成重点改动或风险改动，并输出语义摘要、风险等级、证据、影响和建议。
5. old_quote 和 new_quote 是前端定位原文的依据，必须原样保留，不得修改。

# 规则命中原则
1. 必须逐条处理 diff_texts 中的每一条差异。
2. 每条差异都要与 common_rules 和 specific_rules 中的规则进行比对。
3. 判断是否命中规则时，重点参考规则中的 risk_name、check_point、trigger_condition、example_clause。
4. 如果命中规则，summary、impact 和 suggestion 应围绕该规则展开。
5. 如果命中规则，suggestion 必须优先使用该规则的 suggestion_template，不得自行编造新的建议。
6. 如果同时命中多条规则，优先选择与差异内容最直接相关、风险更高、合同类型更匹配的规则。
7. specific_rules 优先于 common_rules；但如果通用规则更准确，也可以使用通用规则。
8. 如果某条差异未命中任何规则，但属于实质性改动或需要人工重点关注的改动，可以保留为普通重点改动，risk_level 输出 low，suggestion 输出“建议人工复核该改动是否符合业务预期”。
9. 如果某条差异只是空格、标点、格式、换行、编号样式等非实质性变化，risk_level 输出 low，summary 说明“该差异主要为非实质性格式变化”，suggestion 输出“无需修改，建议人工确认”。

# 核心纪律
1. 必须将 diff_texts 中的每一条差异，与 common_rules 和 specific_rules 逐条比对。
2. 如果某条差异命中规则，suggestion 必须优先使用规则里的 suggestion_template。
3. 严禁编造规则库中不存在的建议。
4. 如果某条差异未命中任何已提供规则，但属于用户需要关注的实质性改动，可以保留为普通重点改动，risk_level 输出 low，suggestion 输出“建议人工复核该改动是否符合业务预期”。
5. 如果某条差异只是格式、标点、换行、编号、排版、位置调整等非实质性变化，也必须保留该条输出，但通常不计入 total_risks。

# 风险等级映射
规则中的 default_risk_level 需要转换为英文风险等级：
- 高 → high
- 中 → medium
- 低 → low

如果未命中规则：
- 实质性改动或需要人工重点关注的改动，输出 low
- 非实质性格式变化，输出 low

# 差异类型映射
- added 表示新增
- deleted 表示删除
- modified 表示修改
- moved 表示移位

# 输出字段任务
你需要对 diff_texts 中的每一条差异，结合旧版文本、新版文本、通用规则和专项规则，输出：
1. category
2. summary
3. risk_level
4. evidence
5. impact
6. suggestion

# category 输出要求
category 应输出风险所属的具体条款分类，优先使用命中规则的 risk_name 或 module 进行简短概括。

可参考分类：
- 合同金额
- 付款条款
- 付款前提
- 发票条款
- 税费条款
- 违约责任
- 费用范围
- 验收条款
- 知识产权
- 保密条款
- 争议解决
- 解除终止
- 交付条款
- 其他

不要随意泛化为不准确分类。

# summary 输出要求
summary 应说明该差异的核心变化，只描述变化事实和风险含义，不要夸大。
如果命中规则，可以结合 risk_name 和 check_point 说明为什么需要关注。

# evidence 输出要求
evidence 应尽量引用 old_quote 和 new_quote 中的关键变化。
不得改写 old_quote 和 new_quote 字段本身。

# impact 输出要求
impact 应重点说明该改动可能带来的合同风险、财务风险、履约风险或争议风险。
避免展开过多双方利益分析或主观推测。

# suggestion 输出要求
1. 命中规则时，必须优先使用 suggestion_template。
2. 未命中规则但属于实质性改动或需要人工重点关注的改动时，输出“建议人工复核该改动是否符合业务预期”。
3. 非实质性格式变化时，输出“无需修改，建议人工确认”。
4. 严禁编造规则库中不存在的规则建议。

# 禁止空结果要求
1. 只要 diff_texts 不是空数组，就必须逐条生成 enhanced，不能返回空 enhanced。
2. enhanced 的条目数应尽量与 diff_texts 保持一致。
3. 不得因为风险低、仅结构调整、仅位置变化而删除对应条目。
4. 只有在 diff_texts=[] 时，才允许返回 enhanced=[]。

# total_risks 统计规则
total_risks 沿用原工作流逻辑，统计 enhanced 中存在实质性风险或需要人工重点关注的数量。

具体规则：
1. risk_level 为 high 的条目，计入 total_risks。
2. risk_level 为 medium 的条目，计入 total_risks。
3. risk_level 为 low 但属于实质性改动、权利义务变化、付款变化、金额变化、责任变化、期限变化、验收变化、解除终止变化、争议解决变化、知识产权变化、保密变化，或需要人工复核的普通重点改动，也计入 total_risks。
4. risk_level 为 low 但仅属于空格、标点、格式、换行、编号样式、标题样式、单纯位置移动、排版调整等非实质性变化，不计入 total_risks。
5. 在成功结果中，total_risks 必须等于 enhanced.length。

# 输出要求
1. 必须逐条处理 diff_texts，不能跳项。
2. enhanced 数组顺序应尽量与 diff_texts 保持一致。
3. original / change_type / old_quote / new_quote 必须保留并与输入一致，不得改写字段值。
4. old_quote 和 new_quote 来自上游差异识别节点，是后端和前端定位依据；必须原样保留，不得删字、加字、改写、规范化空格或替换标点。
5. 如果你认为上游 quote 本身不够完整，也只能在 summary / evidence / impact 中说明，不能修改 old_quote / new_quote 字段值。
6. 不要输出 rule_id，除非后端明确要求。
7. 不要输出中文风险等级。
8. 不要输出中文差异类型。
9. 严格输出纯 JSON，不要输出 Markdown，不要输出解释文字。
10. 顶层只允许输出 `success`、`enhanced`、`total_risks`、`message` 四个字段，禁止输出 `reasoning_content`、`analysis`、`notes`、`commentary`、`explanation`、`think` 或任何其他字段。
11. 你的输出必须从字符 `{` 开始，并以字符 `}` 结束。
12. 禁止输出 ```json 代码块，禁止输出 `<think>...</think>`，禁止输出“Let me analyze...”或任何前言。
13. 即使你在内部完成了推理，也不要把推理过程写出来，只返回最终 JSON 对象。

# 输出格式
{
  "success": true,
  "enhanced": [
    {
      "original": "原始差异内容，来自 diff_texts.original",
      "change_type": "added/deleted/modified/moved，来自 diff_texts.change_type",
      "old_quote": "来自 diff_texts.old_quote",
      "new_quote": "来自 diff_texts.new_quote",
      "category": "风险分类，例如付款条款/违约责任/验收条款/知识产权/保密条款",
      "summary": "语义增强摘要，说明该改动的核心变化",
      "risk_level": "high/medium/low",
      "evidence": "证据材料，尽量引用旧版和新版的关键变化",
      "impact": "该改动可能带来的影响",
      "suggestion": "建议处理方式，命中规则时优先引用规则库 suggestion_template"
    }
  ],
  "total_risks": 0,
  "message": ""
}

# 输出约束
1. success 必须是布尔值。
2. enhanced 必须是数组。
3. total_risks 必须按照“total_risks 统计规则”计算。
4. change_type 必须是 added / deleted / modified / moved 之一。
5. risk_level 必须是 high / medium / low 之一。
6. 如果全部差异都属于非实质性格式变化，success 仍输出 true，enhanced 正常返回，total_risks 可为 0。
7. 如果 diff_texts 为空数组，则输出：
{
  "success": true,
  "enhanced": [],
  "total_risks": 0,
  "message": ""
}
"""


def build_classify_contract_type_prompt(old_text: str, new_text: str) -> str:
    return _replace(CLASSIFY_CONTRACT_TYPE_PROMPT, old_text=old_text, new_text=new_text)


def build_identify_differences_prompt(old_text: str, new_text: str) -> str:
    return _replace(IDENTIFY_DIFFERENCES_PROMPT, old_text=old_text, new_text=new_text)


def build_analyze_diff_risks_prompt(
    old_text: str,
    new_text: str,
    diff_texts: list[dict[str, Any]],
    common_rules: list[dict[str, Any]],
    specific_rules: list[dict[str, Any]],
) -> str:
    return _replace(
        ANALYZE_DIFF_RISKS_PROMPT,
        old_text=old_text,
        new_text=new_text,
        diff_texts=json.dumps(diff_texts, ensure_ascii=False, indent=2),
        common_rules=json.dumps(common_rules, ensure_ascii=False, indent=2),
        specific_rules=json.dumps(specific_rules, ensure_ascii=False, indent=2),
    )
