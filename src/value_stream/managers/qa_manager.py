from simpy import Environment, Store
from .manager import Manager
from ..resources import QATester, Resource


class QAManager(Manager):
    def __init__(self, env: Environment, concurrency):
        super().__init__(env, cadence=0)

        self.concurrency = concurrency

        self.qa_operators = Store(self.env, concurrency)

        for _ in range(concurrency):
            self.qa_operators.put(QATester())

    def request(self):
        return self.qa_operators.get()

    def release(self, operator: Resource):
        return self.qa_operators.put(operator)
