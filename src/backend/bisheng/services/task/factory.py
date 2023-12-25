from bisheng.services.factory import ServiceFactory
from bisheng.services.task.service import TaskService


class TaskServiceFactory(ServiceFactory):

    def __init__(self):
        super().__init__(TaskService)

    def create(self):
        # Here you would have logic to create and configure a TaskService
        return TaskService()
