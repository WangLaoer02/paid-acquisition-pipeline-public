# 原生选框与未知受理恢复（按需读取）

仅在本批明确采用原生辅助功能选框时读取。安全拒绝不换通道；权限、登录、HTTPS确认、工具能力分别判断。Chrome JavaScript开关不可用时记录一次真实能力结果并停止同组菜单尝试，不默认要求用户反复切换；列表能查不证明上传能力。能力变化须用户处理后以真实窗口重新核验。

使用发布的工作区入口，不执行项目内历史Python、Swift或二进制上传助手。`python3 scripts/native_upload_build.py`只编译当前已发布Swift，生成本机源码／二进制SHA回执，不打开界面。以真实目标窗口完整标题登记：`python3 scripts/rongyao.py video native-plan --manifest <本批绝对路径清单> --output <新计划绝对路径> --workspace <工作区绝对路径> --window-title <实际后台窗口完整标题>`。原生清单的parameters填写本次真实可见字段值，每条provenance.parameter_encoding明确为visible_ui_labels_only_native_adapter；与CDP提交值分别核对，不猜数字／标签映射，原生计划不能交普通video upload。计划登记到原SQLite，绑定文件、全部字段、控制器／守卫／Swift／本机构建二进制SHA、窗口及发布版；`video inspect-plan`再次核验。控制器、二进制或规则变更停止旧计划；新计划不得重传原账本已listed／未知项。

票据仍由本批真实上传授权产生，action=material_upload，scope=material-upload:rongyao-operations，input_sha256取inspect-plan。`video native-upload --plan <计划> --workspace <工作区> --authorization-ticket <本批票据>`只接受stdin逐项JSON命令。先读实际窗口和全部字段，再`{"op":"open","index":0}`打开该条选框；根据本次可访问控件，用goto、set、select_file_row、press之一，路径使用刚读到的唯一控件，不猜历史坐标。set固定本条已核文件，不隐式Enter；press限选框内Go／Open，不藏双击或其他回退。每次动作后实际重新读取目标状态。

同一文件SHA／窗口／目标的无效次数保存在native-actions.sqlite3，跨进程、换接口／快捷键和新计划不清零。返回0、窗口移动、无关文字变化、只读观察不算成功。连续两次无效停止该目标；未知在途动作只核对，不重新发出。只有目标实际成功或有真实用户处理及不同目标证据的显式检查点才能解除；checkpoint命令须携本条index、实际goal及approval_ref，重新观察到该目标才可记入检查点。能力阻塞不自动重试，明确处理后`capability-recheck`携本次approval_ref只读核验。

`{"op":"observe","index":0}`只读记录当前选框和文件状态。选框消失也可能是取消；只有当前精确文件已选或本文件真实上传进度才能记submitted_pending，不能记入库成功。中断保存实际异常类型／超时和原证据；不编造exit12、网络或登录原因。`resume`仅接续已确认同条文件、同窗口、selection_pending的现存选框；submission_unknown／submitted_pending／listed只回查，不能降级后重选。`{"op":"finish"}`结束助手；结束不代表入库。

后台完整名称唯一匹配且有真实ID才记listed，归属详情、远端播放、内容验收、审核、广告发布各自核验。旧计划与历史助手保留作溯源，不改项目文件或删账本来恢复。该原生控制器的守卫与模拟交互已隔离验证，编译已验证；本次没有新上传，不声明通用原生助手已实网验收或跨账号并行通过。
