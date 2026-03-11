import { Queue } from 'bullmq';
import { Redis as IORedis } from 'ioredis';

import { isString } from '../guards.js';
import logger from '../logging.js';
import { REDIS_HOST, REDIS_PORT, REDIS_PASS} from '../config.js';


function getWorkerQueue(connection:IORedis, queueName:string):Queue {

    if (isString(queueName)) {
        logger.debug(`Connect to the queue: ${queueName}`);

        return new Queue(queueName, { connection });
    }

    throw new Error('Queue name is missing');
}

export { getWorkerQueue }
