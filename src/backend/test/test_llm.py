def test(func: callable):
    func('123')


def auto_gen():
    flow_id = '4e533fed-7bb1-4bee-a6f3-ae6dffdc7801'

    print(flow_id)


test(str)

from bisheng.interface.stts.custom import BishengSTT
from bisheng.interface.ttss.custom import BishengTTS
