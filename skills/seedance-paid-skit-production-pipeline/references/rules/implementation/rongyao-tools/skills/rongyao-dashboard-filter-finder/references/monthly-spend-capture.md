# 月度消耗契约

按自然月 date、母游戏 gid、区间汇总 tenyear 查询 info.sum.cost。素材产出 date2 必须显式传入本次确认的全范围，不随目标月变化。category/pkid/pcid 由当前页面依赖展开；标签、角色、关键词等限定在口径中列明。

使用 scripts/capture_monthly_spend.py 的 --start-month、--end-month、--material-range 和 --capture。可选 --control-month 与 --control-spend 必须成对传入；仅在用户提供本次可比控制值时增加控制查询，不能把历史数值当永久真值。无控制值时 calibration.passed=null，不声称已校准。失败项保留 missing，部分成功整体不标全成功。--result 是用户提供值，不能声称本次实时抓取。

不使用旧归档代替当前响应；保留自然月边界、筛选、来源日期。仅提取汇总，不为月度数值发起素材编号分页或导出。
