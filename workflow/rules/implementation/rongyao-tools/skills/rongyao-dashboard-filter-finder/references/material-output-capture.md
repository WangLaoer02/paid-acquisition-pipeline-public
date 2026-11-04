# 素材产出数量

取 info.sum.count，不是明细行数或 info.count。日期 date 为目标自然月；素材产出 date2 为本次确认的完整素材范围，必须 --material-range 显式传入，不按月缩小。否定词为空；视频、新注册、过滤数据开启、group=mid，gid/category/pkid 使用当前选择及动态依赖。

scripts/capture_material_output.py 接受 --start-month、--end-month、--project（可重复）和 --material-range。重试为0，并发1–6。不连续周期分开请求。项目别名映射只是已知入口，不代表当前账号全部可见项目；全项目任务先枚举并列出排除/失败项。

没有历史固定控制值。缺少 info.sum.count 时记 missing，即使 info.count=0 也不能替代不同粒度指标。仅明确返回的数值0记0。报告项目、双日期、material_output_count、metric_location、状态与失败原因。
