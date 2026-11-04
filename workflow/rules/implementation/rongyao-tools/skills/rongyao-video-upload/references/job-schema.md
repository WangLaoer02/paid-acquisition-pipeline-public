# 本地上传计划

助手脚本只处理正式名、媒体元数据、哈希、参数分组和重复记录，不访问网站/凭据，也不授予上传权限。

在本 Skill 目录执行：

```sh
python3 scripts/prepare_upload.py \
  --request /绝对路径/上传任务.json --output /绝对路径/上传计划.json
```

成品仍是审看名称时，可加 `--copy-dir /绝对路径/正式成品` 生成命名副本；不会覆盖内容不同的同名文件。原文件保持原样，SHA相同即可复用已有核查。

请求结构：

```json
{
  "profile": "naruto-skit-d",
  "date_prefix": "261004",
  "designer_code": "D",
  "requester_tail": "原创",
  "shared_parameters": {},
  "shared_provenance": {},
  "uploaded_records": [],
  "items": [
    {
      "file": "/绝对路径/已核查的成品.mp4",
      "serial": 1,
      "a_description": "AI小剧场写轮眼家产继承",
      "b_key": "itachi-six-yuan",
      "expected_b_name": "260930HR9-AI新来同学接首充6元鼬踩捧-HR-OBR",
      "intern_marker": null,
      "split_37": true,
      "quality_review": {
        "media_sha256": "成品完整SHA256",
        "full_decode_exit": 0,
        "full_decode_errors": "",
        "disclaimer_verified": true,
        "moving_watermark_verified": true,
        "role_verified": true,
        "splice_verified": true,
        "evidence": ["/绝对路径/技术核查.json"]
      }
    }
  ]
}
```

`date_prefix`和`serial`必须由本次任务或已完成的编号分配提供。例子的261004/1不能自动用于新上传。

角色、B描述和第二设计师默认来自已验证B缓存；`expected_b_name`用于锁定用户选定的精确来源。当前另一个有效b_key为`itachi-800-harmonized`。用户给的是新B时，先核验并加入缓存，或用`b_source`传相同字段（完整名称、ID、源文件和SHA、role/role_token、b_description、second_designer_name/value、b_start/end）。不要为通过脚本而捏造核查。

`quality_review.media_sha256`必须匹配当前文件。声明人工抽查只覆盖实际抽查；脚本不会自动从视频像素证明标语/水印。

`shared_provenance`与单文件`provenance`保留到操作计划，单文件同名键优先；按实际来源记录AI方式、A原生导出与成片验收依据。`ai_source: ""`是显式空值，不能被档案默认值覆盖。只有本次明确要求需求人“原创”时，才记录`requester_explicit_original_override: true`；该标记不由“原创”尾标或默认值自动生成。

可选`inherit_from: {"job_id":"原作业","filename":"原完整文件名.mp4"}`随单文件传给operations，由其核对已登记来源并保留来源计划SHA。本助手先核定的完整`form_values`仍是本次显式参数，角色与第二设计师受锁定B来源保护；若只需继承通用成片参数，直接使用operations通用清单。测试请求标`test_only: true`，经准备与计划转换后仍禁止外部上传。

`uploaded_records`每项采用：

```json
{"name":"已上传正式名称（不含扩展名）","sha256":"文件SHA256","record_id":124604,"status":"listed"}
```

状态`listed`或`metadata_verified`允许跳过同名同哈希；`submitted`/`unknown`同名进入待核对，不能当成可重传。同名不同哈希产生冲突，先核对既有记录/修改版本描述。

输出包含每条正式文件名、SHA、技术参数、B来源、整套表单值、待上传分组、跳过项和冲突项。`can_proceed_to_ui`只表示本地计划无阻塞，不代表用户授权、网站入库或审核通过。不同第二设计师将生成不同分组。
