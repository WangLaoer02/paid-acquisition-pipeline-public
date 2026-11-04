"""Observable behavior and preservation checks, using isolated SQLite databases."""
import unittest,tempfile,json,sys,copy,hashlib
from unittest.mock import patch
from pathlib import Path
import store,diagnostics

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_db=store.DB;store.DB=Path(self.temp.name)/'test.sqlite3'
        self.agent={'kind':'agent','name':'Test Agent'};self.human={'kind':'human','name':'Test Human'}
        self.task=store.create_task({'form':{'title':'示例舞蹈','source':'固定镜头'},'skills':['seedance-character-shortvideo-production'],'primary':'seedance-character-shortvideo-production','draft':'人工稿'},self.human)
    def tearDown(self):store.DB=self.old_db;self.temp.cleanup()
    def start(self):return store.start_run(self.task['id'],self.agent)
    def test_global_view_does_not_activate_or_write_history(self):
        run=self.start();store.finish_run(run['id'],self.agent,'completed','完成','输出')
        before=store.workspace();a=diagnostics.monitor();b=diagnostics.monitor();after=store.workspace()
        self.assertEqual(before['active_task_id'],after['active_task_id']);self.assertEqual(before['sequence'],after['sequence'])
        self.assertEqual(a['runs'][0]['id'],run['id']);self.assertEqual(len(b['issues']),1)
        self.assertEqual(after['current']['task']['draft'],'人工稿')
    def test_exact_video_position_and_issue_persistence(self):
        run=self.start();store.add_note(self.task['id'],self.agent,'准备完成',run['id'])
        store.finish_run(run['id'],self.agent,'completed','16.54秒无声候选，角色房间一致，8秒接点姿态跳变','成片')
        item=diagnostics.monitor()['issues'][0];self.assertEqual(item['position_seconds'],8);self.assertEqual(item['title'],'8 秒接点跳变')
        diagnostics.save_issue({'status':'resolved'},self.human,item['id'])
        self.assertEqual(diagnostics.monitor()['runs'][0]['issue_count'],0)
        self.assertEqual(diagnostics.monitor()['issues'][0]['status'],'resolved')
    def test_tool_failure_and_redaction(self):
        run=self.start()
        result,code=diagnostics.execute(run['id'],self.agent,'调用测试工具',[sys.executable,'-c',"import sys;print('token=example-secret');print('failure',file=sys.stderr);sys.exit(7)"])
        self.assertEqual(code,7);self.assertNotIn('example-secret',result['output']);self.assertIn('failure',result['error'])
        view=diagnostics.monitor();tool=next(s for s in view['runs'][0]['steps'] if s['kind']=='tool')
        self.assertEqual(tool['exit_code'],7);self.assertEqual(tool['status'],'failed');self.assertIsNotNone(tool['duration_ms'])
        self.assertTrue(any('调用测试工具' in i['title'] for i in view['issues']))
        store.finish_run(run['id'],self.agent,'failed','调用测试工具失败')
        self.assertEqual(len(diagnostics.monitor()['issues']),1)
    def test_context_and_manual_steps_are_in_timeline(self):
        run=self.start();store.context(self.task['id'],run['id'])
        s=diagnostics.start_step(run['id'],self.agent,'检查输入','check',{'file':'reference.mp4'})
        diagnostics.finish_step(run['id'],s['step_id'],self.agent,'completed','输入可读')
        view=diagnostics.monitor()['runs'][0]
        self.assertTrue(any(x['kind']=='context_read' for x in view['steps']))
        self.assertEqual(view['steps'][-1]['output'],'输入可读')
        with self.assertRaises(store.StudioError):diagnostics.finish_step(run['id'],s['step_id'],self.agent,'completed','重复')
    def test_manual_problem_is_anchored_to_step(self):
        run=self.start();step=diagnostics.monitor()['runs'][0]['steps'][0]
        issue=diagnostics.save_issue({'run_id':run['id'],'step_id':step['id'],'title':'输入少了一张图','position_seconds':3},self.human)
        self.assertEqual(issue['step_id'],step['id']);self.assertEqual(issue['position_seconds'],3)
        with self.assertRaises(store.StudioError):diagnostics.save_issue({'run_id':run['id'],'step_id':'other','title':'无效'},self.human)
    def test_terminal_and_wrong_actor_rejected(self):
        run=self.start()
        with self.assertRaises(store.StudioError):diagnostics.start_step(run['id'],self.human,'错误执行者')
        store.finish_run(run['id'],self.agent,'completed','完成','输出')
        with self.assertRaises(store.StudioError):diagnostics.start_step(run['id'],self.agent,'结束后重复执行')
    def test_registered_files_and_missing_output(self):
        run=self.start();file=Path(self.temp.name)/'result.txt';file.write_text('local result')
        store.finish_run(run['id'],self.agent,'completed','完成','输出',[str(file)])
        item=diagnostics.monitor()['runs'][0]['files'][0];self.assertEqual(diagnostics.registered_file(item['id'])['path'],str(file.resolve()))
        file.unlink();self.assertTrue(any('输出文件不存在' in i['title'] for i in diagnostics.monitor()['issues']))
        with self.assertRaises(store.StudioError):diagnostics.registered_file('../../etc/passwd')
    def test_reference_changes_get_new_snapshot_without_rewriting_old_run(self):
        original=store.catalog();new=copy.deepcopy(original)
        target=next(s for s in new['skills'] if s['slug']=='seedance-character-shortvideo-production')
        target['references'].append({'name':'new.md','path':'/test/new.md','body':'新规则','sha256':hashlib.sha256('新规则'.encode()).hexdigest()})
        first=self.start()
        with patch('store.catalog',return_value=new):second=self.start()
        self.assertEqual(first['skills'][0]['sha256'],second['skills'][0]['sha256'])
        self.assertNotEqual(first['skills'][0]['snapshot_id'],second['skills'][0]['snapshot_id'])
        self.assertNotIn('new.md',[r['name'] for r in store.context(self.task['id'],first['id'])['skill_instructions'][0]['references']])
        self.assertIn('new.md',[r['name'] for r in store.context(self.task['id'],second['id'])['skill_instructions'][0]['references']])


class GeneralInspectionTests(unittest.TestCase):
    setUp=MonitorTests.setUp
    tearDown=MonitorTests.tearDown
    start=MonitorTests.start
    def test_all_eleven_skills_use_same_inspection_contract(self):
        from catalog import SPECS
        for slug,title,*_ in SPECS:
            with self.subTest(skill=slug):
                task=store.create_task({'form':{'title':'协作验收｜'+title,'source':'检查本机 Skill 正文与参考可读，不执行生成'},'skills':[slug]},self.human)
                run=store.start_run(task['id'],self.agent)
                read=diagnostics.read_skill(run['id'],self.agent,slug,'核对当前方法与用户任务的关系')
                self.assertEqual(read['document']['slug'],slug)
                ref=read['document']['references'][0]
                ref_read=diagnostics.read_skill(run['id'],self.agent,slug,'检查具体参考',ref['path'],read['step_id'])
                self.assertEqual(ref_read['document']['sha256'],ref['sha256'])
                check=diagnostics.start_step(run['id'],self.agent,'检查 Skill 入口','check',{'slug':slug},slug,read['step_id'],expected='正文入口名称与目录一致')
                diagnostics.finish_step(run['id'],check['step_id'],self.agent,'completed','正文入口名称与目录一致',outcome='matched')
                store.finish_run(run['id'],self.agent,'completed','完成本机入口检查','正文和一份参考已通过统一接口读取')
                view=next(r for r in diagnostics.monitor()['runs'] if r['id']==run['id'])
                self.assertEqual(view['issue_count'],0)
                self.assertEqual(view['skill_trace'][0]['reason'],'核对当前方法与用户任务的关系')
                self.assertEqual(len(view['skill_trace'][0]['references'][0]['read_steps']),1)
                self.assertEqual(next(s for s in view['steps'] if s['id']==ref_read['step_id'])['parent_step_id'],read['step_id'])
    def test_routing_locks_new_skill_and_parent_without_altering_task(self):
        run=self.start()
        first=diagnostics.read_skill(run['id'],self.agent,'seedance-character-shortvideo-production','沿用角色展示方法')
        second=diagnostics.read_skill(run['id'],self.agent,'seedance-cinematic-director','需要设计镜头调度',parent_step_id=first['step_id'])
        view=diagnostics.monitor()['runs'][0]
        self.assertEqual(len(view['skills']),2)
        self.assertEqual(view['input_snapshot']['skills'],['seedance-character-shortvideo-production'])
        self.assertEqual(view['skill_trace'][1]['reason'],'需要设计镜头调度')
        self.assertEqual(diagnostics.skill_snapshot(run['id'],'seedance-cinematic-director')['slug'],'seedance-cinematic-director')
        with self.assertRaises(store.StudioError):diagnostics.read_skill(run['id'],self.agent,'seedance-prompts','无效上游',parent_step_id='elsewhere')
        self.assertEqual(len(diagnostics.monitor()['runs'][0]['skills']),2)
    def test_requirement_and_check_difference_are_preserved(self):
        run=self.start()
        check=diagnostics.start_step(run['id'],self.agent,'核对镜头要求','check',{},expected='固定镜头')
        diagnostics.finish_step(run['id'],check['step_id'],self.agent,'completed','出现了推镜',outcome='different')
        task=store.workspace()['current']['task'];task['form']['source']='后续修改的要求'
        store.update_task(task['id'],task,self.human,task['revision'])
        view=diagnostics.monitor()['runs'][0]
        self.assertEqual(view['input_snapshot']['form']['source'],'固定镜头')
        finding=view['issues'][0];self.assertEqual(finding['category'],'output')
        self.assertEqual(finding['expected'],'固定镜头');self.assertEqual(finding['actual'],'出现了推镜')
        saved=diagnostics.save_issue({'basis':'原要求与检查返回','cause':'提示词加入了推镜','fix':'移除推镜描述','related_skill':'seedance-character-shortvideo-production'},self.agent,finding['id'])
        self.assertEqual(saved['status'],'open');self.assertEqual(saved['fix'],'移除推镜描述')
        self.assertEqual(diagnostics.monitor()['issues'][0]['cause'],'提示词加入了推镜')
    def test_snapshot_view_is_readonly_and_reference_read_uses_locked_bytes(self):
        run=self.start();original=diagnostics.skill_snapshot(run['id'],'seedance-character-shortvideo-production')
        before=store.workspace()['sequence']
        diagnostics.skill_snapshot(run['id'],'seedance-character-shortvideo-production')
        self.assertEqual(before,store.workspace()['sequence'])
        current=copy.deepcopy(store.catalog());target=next(s for s in current['skills'] if s['slug']=='seedance-character-shortvideo-production')
        target['references'][0]['body']='current changed'
        target['references'][0]['sha256']='new-hash'
        with patch('diagnostics.catalog',return_value=current):
            read=diagnostics.read_skill(run['id'],self.agent,target['slug'],reference=original['references'][0]['path'])
            self.assertEqual(read['document']['body'],original['references'][0]['body'])
            self.assertTrue(diagnostics.monitor()['runs'][0]['skill_trace'][0]['references_changed'])
    def test_unfinished_steps_and_context_only_are_recording_problems(self):
        run=self.start();store.context(self.task['id'],run['id'])
        store.finish_run(run['id'],self.agent,'completed','仅保存了文本结果','结果')
        self.assertTrue(any(i['category']=='recording' for i in diagnostics.monitor()['issues']))
        run=self.start();s=diagnostics.start_step(run['id'],self.agent,'实际工具')
        store.finish_run(run['id'],self.agent,'completed','保存结果','结果')
        self.assertTrue(any(i['step_id']==s['step_id'] and i['category']=='recording' for i in diagnostics.monitor()['issues']))
    def test_general_issue_fields_and_media_attachment_validation(self):
        run=self.start()
        item=diagnostics.save_issue({'run_id':run['id'],'category':'routing','title':'专项选择不合适','expected':'保留既有动作','actual':'重写了完整交锋','basis':'原稿','cause':'分流依据不匹配','fix':'只修冲击帧'},self.human)
        self.assertEqual(diagnostics.monitor()['issues'][0]['category'],'routing')
        with self.assertRaises(store.StudioError):diagnostics.save_issue({'category':'unknown'},self.human,item['id'])
        with self.assertRaises(store.StudioError):diagnostics.save_issue({'related_skill':'seedance-prompts'},self.human,item['id'])
        with self.assertRaises(store.StudioError):diagnostics.save_issue({'file_id':'some-other-run'},self.human,item['id'])
        diagnostics.save_issue({'position_seconds':8},self.human,item['id'])
        updated=diagnostics.save_issue({'position_seconds':None,'status':'resolved'},self.human,item['id'])
        self.assertIsNone(updated['position_seconds']);self.assertEqual(updated['status'],'resolved')

    def test_single_run_inspection_preserves_history_and_locked_references(self):
        run=self.start();step=diagnostics.start_step(run['id'],self.agent,'比较输入','check',{'token':'example-secret'})
        finding=diagnostics.save_issue({'run_id':run['id'],'step_id':step['step_id'],'title':'原要求有遗漏'},self.human)
        before=store.workspace()
        bundle=diagnostics.inspection(run['id'],step['step_id'],finding['id'])
        self.assertEqual(bundle['run']['id'],run['id'])
        self.assertEqual(bundle['focus']['issue_id'],finding['id'])
        self.assertNotIn('example-secret',json.dumps(bundle))
        self.assertEqual(bundle['skill_instructions'][0]['slug'],'seedance-character-shortvideo-production')
        self.assertIn('body',bundle['skill_instructions'][0]['references'][0])
        self.assertEqual(before,store.workspace())
    def test_inspection_rejects_cross_run_focus(self):
        first=self.start();step=diagnostics.start_step(first['id'],self.agent,'第一个步骤')
        finding=diagnostics.save_issue({'run_id':first['id'],'title':'第一个问题'},self.human)
        second=self.start()
        for args in [(second['id'],step['step_id'],None),(second['id'],None,finding['id']),('missing',None,None)]:
            with self.assertRaises(store.StudioError):diagnostics.inspection(*args)

if __name__=='__main__':unittest.main()
