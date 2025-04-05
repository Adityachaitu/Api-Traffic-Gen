import pytest
import logging
import sys
from reportportal_client import RPLogger, RPLogHandler

APP_LOGGER_NAME = 'API Security'

logger_inst = None

def report_logger():
    global logger_inst

    logging.getLogger("faker.factory").setLevel(logging.ERROR)
    if logger_inst is None:
        logging.setLoggerClass(RPLogger)
        # formatter = logging.Formatter('%(asctime)s %(filename)s:%(lineno)d %(message)s')
        rp_logger = logging.getLogger(name=APP_LOGGER_NAME)
        rp_logger.setLevel(logging.DEBUG)
        # rp_handler = RPLogHandler()
        # rp_handler.setFormatter(formatter)
        # rp_logger.addHandler(rp_handler)
        # Add StreamHandler to print logs to stdout
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s %(filename)s:%(lineno)d %(message)s')
        stream_handler.setFormatter(formatter)
        rp_logger.addHandler(stream_handler)

        logger_inst = rp_logger
    return logger_inst
