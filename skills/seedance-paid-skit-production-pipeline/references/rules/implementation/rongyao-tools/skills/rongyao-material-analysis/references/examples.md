# 完整判断示例

以下全部为演示数据，不是历史周报事实或当前投放结果。示例用于说明如何计算和绑定证据；实际执行用真实输入，不复制数值、角色故事或判断。

## 1. 新老贡献与加权回本

示例项目为忍界大战，前期9月12日至18日、当期9月19日至25日，均为7天。示例假定项目、筛选、成熟度与新老身份可比。前期老/新消耗为6000/2000元；当期如下：

| 分组 | 消耗 | 新付费数 | ROI1 | ROI2 |
| --- | ---: | ---: | ---: | ---: |
| 老素材 | 8000元 | 80 | 8% | 16% |
| 当期新素材 | 2000元 | 15 | 10% | 19% |

计算：总消耗增长25%；老素材贡献当期消耗80%，新素材消耗持平。ROI1=(8000×8%+2000×10%)/10000=8.4%；ROI2=16.6%；推导倍率约1.98。付费数为95，不能称95个去重用户。未提供有效规则，因此不能从这张表计算有效贡献或宣布新素材已经接替。

## 2. 有内容依据的创意假设

示例用户描述两版B段均为同一福利展示，A段分别为师徒争执和技能展示。可以建议保持B段比较A段，说明要验证吸量和付费差异；这属于未验证建议。未提供视频/台词时不编具体镜头、角色、对白，也不声称师徒冲突已导致更好表现。

## 3. 缺失数据的最小判断

示例素材A只返回1200元消耗，ROI1、ROI2、新付费数均为null。保留消耗事实和字段缺口；不补0，不评优质/潜力，也不因缺字段宣称付费差。

## 对应的完整结构化输出

`next_test`在纯效果判断中为null，建议项使用`validated=false`。下列4项可交给现有`validate_finding(finding, facts)`校验；它验证来源与外推边界，不能证明演示内容是真实业务数据。

```json
{
  "example_only": true,
  "notice": "全部为演示数据，不是后台查询、用户当期事实或可复用的业务结论。实际执行须替换为真实已校验输入。",
  "facts": {
    "F-current": {
      "evidence_type": "backend_metric",
      "example_only": true,
      "period": "2026-09-19/2026-09-25",
      "old": {
        "cost": 8000,
        "new_pay_count": 80,
        "roi1_pct": 8,
        "roi2_pct": 16
      },
      "new": {
        "cost": 2000,
        "new_pay_count": 15,
        "roi1_pct": 10,
        "roi2_pct": 19
      }
    },
    "F-previous": {
      "evidence_type": "backend_metric",
      "example_only": true,
      "period": "2026-09-12/2026-09-18",
      "old_cost": 6000,
      "new_cost": 2000
    },
    "F-description": {
      "evidence_type": "user_input",
      "example_only": true,
      "content": "用户提供的示例内容：两版B段均为同一福利展示；A段分别为师徒争执和技能展示。未提供视频或台词。"
    },
    "F-missing": {
      "evidence_type": "backend_metric",
      "example_only": true,
      "material": "示例素材A",
      "cost": 1200,
      "roi1": null,
      "roi2": null,
      "new_pay_count": null
    }
  },
  "analysis_findings": [
    {
      "evidence_type": "backend_metric",
      "topic": "示例方向的新老贡献",
      "judgment": "总消耗由8000元增至10000元，增量2000元全部来自老素材；当期新素材消耗持平。老素材贡献当期消耗的80%。",
      "support_fact_ids": [
        "F-current",
        "F-previous"
      ],
      "counterevidence_fact_ids": [],
      "boundary": "演示数据。两期等长且紧邻，示例假定同项目同筛选、新老身份已校验；未提供有效分类和视频，结论只涉及消耗。",
      "next_test": null,
      "coverage": {
        "scope": "specified_project",
        "projects": [
          {
            "gid": 193,
            "name": "忍界大战"
          }
        ],
        "excluded_projects": [],
        "failed_projects": [],
        "enumeration_complete": false,
        "period_start": "2026-09-19",
        "period_end": "2026-09-25",
        "material_start": "2023-01-01",
        "material_end": "2026-09-25",
        "threshold_source": "示例使用工具参数，非业务标准"
      }
    },
    {
      "evidence_type": "backend_metric",
      "topic": "示例方向的首日与后续回本",
      "judgment": "按花费加权，当期ROI1为8.4%，ROI2为16.6%，推导2日倍率约1.98。首日低于示例9%参数，后续累计回本上升。",
      "support_fact_ids": [
        "F-current"
      ],
      "counterevidence_fact_ids": [],
      "boundary": "演示数据，ROI使用百分数。累计目标未提供，无法判断是否达到累计回本目标；后台原始倍率未提供。",
      "next_test": null,
      "coverage": {
        "scope": "specified_project",
        "projects": [
          {
            "gid": 193,
            "name": "忍界大战"
          }
        ],
        "excluded_projects": [],
        "failed_projects": [],
        "enumeration_complete": false,
        "period_start": "2026-09-19",
        "period_end": "2026-09-25",
        "material_start": "2023-01-01",
        "material_end": "2026-09-25",
        "threshold_source": "示例使用工具参数，非业务标准"
      }
    },
    {
      "evidence_type": "generated_proposal",
      "topic": "示例内容的A段对照",
      "judgment": "创作建议：保留同一福利B段，比较师徒争执与技能展示两种A段；师徒关系能否带动吸量属于待验证假设。",
      "support_fact_ids": [
        "F-description"
      ],
      "counterevidence_fact_ids": [],
      "boundary": "示例仅有用户内容描述，未观看视频、未核验台词，也没有对应投放数据；不能写成当前素材原因。",
      "validated": false,
      "next_test": {
        "fixed": "福利B段",
        "replace": "两种已由用户描述的A段",
        "question": "A段差异是否影响消耗与付费结果",
        "observe": "同口径消耗、付费成本及ROI；同时核对投放条件与成熟度"
      },
      "coverage": {
        "scope": "specified_project",
        "projects": [
          {
            "gid": 193,
            "name": "忍界大战"
          }
        ],
        "excluded_projects": [],
        "failed_projects": [],
        "enumeration_complete": false,
        "period_start": "2026-09-19",
        "period_end": "2026-09-25",
        "material_start": "2023-01-01",
        "material_end": "2026-09-25",
        "threshold_source": "示例使用工具参数，非业务标准"
      }
    },
    {
      "evidence_type": "backend_metric",
      "topic": "示例素材A的数据缺口",
      "judgment": "当前可描述示例素材A的1200元消耗；付费数和首日、后续回本保留未知。",
      "support_fact_ids": [
        "F-missing"
      ],
      "counterevidence_fact_ids": [],
      "boundary": "演示缺失字段情形。缺失值为null；输入未通过完整表现字段门槛，只交付缺口判断，不进入完整方向评价。",
      "next_test": null,
      "coverage": {
        "scope": "specified_project",
        "projects": [
          {
            "gid": 193,
            "name": "忍界大战"
          }
        ],
        "excluded_projects": [],
        "failed_projects": [],
        "enumeration_complete": false,
        "period_start": "2026-09-19",
        "period_end": "2026-09-25",
        "material_start": "2023-01-01",
        "material_end": "2026-09-25",
        "threshold_source": "示例使用工具参数，非业务标准"
      }
    }
  ]
}
```
