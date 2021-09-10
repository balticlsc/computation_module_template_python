import abc
import json
import os
import re
import threading
from typing import Type, Union
from flask import Flask, request, Response

from balticlsc.scheme.configuration import IConfiguration
from balticlsc.scheme.data_handler import IDataHandler, DataHandler
from balticlsc.scheme.job_registry import IJobRegistry, JobRegistry
from balticlsc.scheme.logger import logger
from balticlsc.scheme.messages import Status, InputTokenMessage, SeqToken


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
            if 'true' == self.__registry.get_pin_configuration(self.__pin_name).is_required:
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


__registry: Union[JobRegistry, None] = None
__handler: Union[DataHandler, None] = None
__listener_type: Union[Type[TokenListener], None] = None


def camel_dict_to_snake_dict(source: {}) -> {}:
    pattern = re.compile(r'(?<!^)(?=[A-Z])')
    return {pattern.sub('_', key).lower(): list(
        camel_dict_to_snake_dict(in_value) for in_value in value
    ) if isinstance(value, type([])) else value for key, value in source.items()}


def init_job_controller(listener_type: Type[TokenListener]) -> Flask:
    global __registry, __handler, __listener_type
    configuration = IConfiguration()
    __registry = JobRegistry(configuration)
    __handler = DataHandler(__registry, configuration)
    __listener_type = listener_type
    app = Flask(os.getenv('SYS_MODULE_NAME', 'BalticLSC module'))

    @app.route('/token', methods=['POST'])
    def process_token():
        try:
            logger.debug('Token message received: ' + str(request.json))
            input_token = InputTokenMessage(
                **{key: value if 'token_seq_stack' != key else list(
                    SeqToken(**in_value) for in_value in value)
                   for key, value in camel_dict_to_snake_dict(request.json).items() if key in
                   InputTokenMessage.__dict__['__annotations__']})
            __registry.register_token(input_token)
            try:
                result = __handler.check_connection(input_token.pin_name, json.loads(input_token.values))
                match result:
                    case 0:
                        job_thread = JobThread(input_token.pin_name, __listener_type(__registry, __handler),
                                               __registry, __handler)
                        __registry.register_thread(job_thread)
                        pin_task = threading.Thread(target=job_thread.run)
                        pin_task.daemon = True
                        pin_task.start()
                        return Response(status=200, mimetype='application/json')
                    case - 1:
                        ret__message = 'No response (' + input_token.pin_name + ').'
                        logger.debug(ret__message)
                        return Response(ret__message, status=404, mimetype='application/json')
                        pass
                    case - 2:
                        ret__message = 'Unauthorized (' + input_token.pin_name + ').'
                        logger.debug(ret__message)
                        return Response(ret__message, status=401, mimetype='application/json')
                        pass
                    case - 3:
                        ret__message = 'Invalid path (' + input_token.pin_name + ').'
                        logger.debug(ret__message)
                        return Response(ret__message, status=401, mimetype='application/json')
                        pass
                return Response(status=400, mimetype='application/json')
            except Exception as e:
                logger.debug('Corrupted token: : ' + str(e))
                return Response('Error of type ' + type(e).__name__ + ':' + str(e), status=200,
                                mimetype='application/json')
        except Exception as e:
            logger.debug('Corrupted token: : ' + str(e))
            return Response(str(e), status=400, mimetype='application/json')

    @app.route('/status', methods=['GET'])
    def get_status():
        camel_dict = {''.join(word.title() for word in key.split('_')): value if 'status' != key else value.name.title()
                      for key, value in __registry.get_job_status().__dict__.items()}
        return Response(json.dumps(camel_dict), status=200, mimetype='application/json')

    return app
