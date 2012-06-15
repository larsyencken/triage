import zmq
import msgpack
import mongoengine
import logging
from sys import argv
from pyramid.paster import get_appsettings
from models import Error, ErrorHasher, ErrorInstance

#logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')


# config
logging.info('Loading configuration')
ZMQ_URI = "tcp://0.0.0.0:5001"
settings = get_appsettings(argv[1], 'triage')

# zero mq
logging.info('Initializing zeromq socket at: ' + ZMQ_URI)
context = zmq.Context()
socket = context.socket(zmq.SUB)
socket.bind(ZMQ_URI)
socket.setsockopt(zmq.SUBSCRIBE, '')

# mongo
logging.info('Connecting to mongo at: mongodb://' + settings['mongodb.host'] + '/' + settings['mongodb.db_name'])
mongoengine.connect(settings['mongodb.db_name'], host=settings['mongodb.host'])


# messagepack
unpacker = msgpack.Unpacker()

# serve!
logging.info('Serving!')
while True:
    try:
        data = socket.recv()
        logging.debug('received data')
        unpacker.feed(data)
        logging.debug('fed data to unpacker')
        for msg in unpacker:
            logging.debug('found message in unpacker')
            if type(msg) == dict:
                logging.debug('found object in message')

                msg['hash'] = ErrorHasher(msg).get_hash()
                if 'timestamp' not in msg:
                    msg['timestamp'] = int(time())

                Error.validate_and_upsert(msg)
                logging.debug('saved error')

                ErrorInstance.from_raw(msg).save(safe=False)
                logging.debug('saved instance')

    except Exception, a:
        logging.exception('Failed to process error')
