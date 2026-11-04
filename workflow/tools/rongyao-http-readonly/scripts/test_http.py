import unittest
from http_core import list_result
from http_transport import validate_url
class ReadonlyTests(unittest.TestCase):
 def test_card_pairing_not_global_input_order(self):
  body='<p>视频数量为：2</p><input type="text" value="search"><div class="col-sm-2"><input name="id[]" value="20"><input type="text" value="alpha"></div><div class="col-sm-2"><input type="text" value="beta"><input name="id[]" value="19"></div>'
  self.assertEqual(list_result(body)['rows'],[{'record_id':'20','name':'alpha'},{'record_id':'19','name':'beta'}])
 def test_positive_total_without_cards_is_not_empty_success(self):
  with self.assertRaisesRegex(ValueError,'LIST_STRUCTURE_CHANGED'):list_result('<p>视频数量为：50</p>')
 def test_ambiguous_card_and_duplicate_id_rejected(self):
  for body in ['<div class="col-sm-2"><input name="id[]" value="20"><input type="text" value="a"><input type="text" value="b"></div>', '<div class="col-sm-2"><input name="id[]" value="20"><input type="text" value="a"></div>'*2]:
   with self.assertRaises(ValueError):list_result('<p>视频数量为：2</p>'+body)
 def test_login_page_is_not_list(self):
  with self.assertRaisesRegex(ValueError,'LOGIN_EXPIRED'):list_result('<input type="password">',host='power.houtai.backend.example.invalid')
 def test_upload_and_external_hosts_rejected_before_network(self):
  for url,post in [('http://adopenplatform.backend.example.invalid/app/data/?_c=jrttList&_a=index&ac=toImgInfo&do=video',False),('http://adopenplatform.backend.example.invalid/',True),('https://accounts.feishu.cn.attacker.example/accounts/qrlogin/init',True),('https://accounts.feishu.cn/accounts/qrlogin/confirm',True),('https://u:p@accounts.feishu.cn/',False)]:
   with self.assertRaises(ValueError):validate_url(url,post)
 def test_allowed_auth_and_list(self):
  validate_url('https://accounts.feishu.cn/accounts/qrlogin/polling',True)
  validate_url('https://login.feishu.cn/accounts/trap')
  validate_url('http://adopenplatform.backend.example.invalid/app/data/?_c=jrttList&_a=index&ac=jrttVideoList')
if __name__=='__main__':unittest.main()
