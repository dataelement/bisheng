from pydantic import BaseModel


class SFTBackend(BaseModel):
    """ 封装和SFT-Backend的交互 """

    def __init__(self, url: str):
        super().__init__()
        self.url = url

    def create_job(self):
        pass
