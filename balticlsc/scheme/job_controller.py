import abc
from typing import Type
from flask import Flask

from balticlsc.scheme.data_handler import IDataHandler, DataHandler
from balticlsc.scheme.job_registry import IJobRegistry, JobRegistry
from balticlsc.scheme.messages import Status


class TokenListener:

    @classmethod
    def __subclasshook__(cls, subclass):
        return (hasattr(subclass, 'data_received') and
                callable(subclass.data_received) and
                hasattr(subclass, 'optional_data_received') and
                callable(subclass.optional_data_received) and
                hasattr(subclass, 'data_ready') and
                callable(subclass.data_ready) and
                hasattr(subclass, 'data_complete') and
                callable(subclass.data_complete) or
                NotImplemented)

    @abc.abstractmethod
    def __init__(self, registry: IJobRegistry, data: IDataHandler):
        _data = data
        _registry = registry

    @abc.abstractmethod
    def data_received(self, pin_name: str):
        pass

    @abc.abstractmethod
    def optional_data_received(self, pin_name: str):
        pass

    @abc.abstractmethod
    def data_ready(self):
        pass

    @abc.abstractmethod
    def data_complete(self):
        pass


class JobThread:

    def __init__(self, pin_name: str, listener: TokenListener, registry: JobRegistry, handler: DataHandler):
        self.__pin_name = pin_name
        self.__listener = listener
        self.__registry = registry
        self.__handler = handler

    def run(self):
        try:
            self.__listener.data_received(self.__pin_name)
            if "true" == self.__registry.get_pin_configuration(self.__pin_name).is_required:
                self.__listener.optional_data_received(self.__pin_name)
            pin_aggregated_status = Status.COMPLETED
            for pin_name in self.__registry.get_strong_pin_names():
                pin_status = self.__registry.get_pin_status(pin_name)
                if Status.WORKING == pin_status:
                    pin_aggregated_status = Status.WORKING
                elif Status.IDLE == pin_status:
                    pin_aggregated_status = Status.IDLE
                    break
            if Status.IDLE != pin_aggregated_status:
                self.__listener.data_ready()
            if Status.COMPLETED == pin_aggregated_status:
                self.__listener.data_complete()
        except Exception as e:
            self.__handler.fail_processing(str(e))


def init_job_controller(listener: Type[TokenListener]) -> Flask:
    pass
