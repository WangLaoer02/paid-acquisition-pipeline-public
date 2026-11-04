import time,unittest
from sms_receiver import select_code
class SmsTests(unittest.TestCase):
    def setUp(self):self.now=time.time()
    def row(self,seconds=1,text='验证码 123456',sender='any',rid=10):return (rid,int((self.now+seconds-978307200)*1e9),sender,text)
    def test_new_sender_and_unrelated_purpose_allowed(self):
        self.assertEqual(select_code([self.row(text='服务验证 123456',sender='new')],'old',self.now),(10,'123456'))
    def test_no_purpose_text_required(self):self.assertEqual(select_code([self.row(text='123456')],None,self.now),(10,'123456'))
    def test_pre_request_rejected(self):self.assertIsNone(select_code([self.row(-1)],None,self.now))
    def test_after_one_minute_rejected(self):self.assertIsNone(select_code([self.row(61)],None,self.now))
    def test_within_one_minute_allowed(self):self.assertIsNotNone(select_code([self.row(59)],None,self.now))
    def test_long_number_not_code(self):self.assertIsNone(select_code([self.row(text='1234567')],None,self.now))
    def test_different_codes_stop(self):
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS_NEW_RONGYAO_SMS'):select_code([self.row(),self.row(text='654321',rid=11)],None,self.now)
    def test_multiple_codes_in_one_message_stop(self):
        with self.assertRaises(ValueError):select_code([self.row(text='123456 654321')],None,self.now)
    def test_duplicate_same_code_allowed(self):self.assertEqual(select_code([self.row(),self.row(rid=11)],None,self.now),(11,'123456'))
if __name__=='__main__':unittest.main()
