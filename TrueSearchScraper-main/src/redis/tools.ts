import { Redis as IORedis } from 'ioredis';

import logger from '../logging.js';
import { REDIS_HOST, REDIS_PORT, REDIS_PASS } from '../config.js';


function getRedisClient(): IORedis {
    logger.debug(`New redis connection: ${REDIS_HOST}:${REDIS_PORT}/${REDIS_PASS}`);

    return new IORedis({
        host: REDIS_HOST,
        port: REDIS_PORT,
        password: REDIS_PASS,
        maxRetriesPerRequest: null,
    });
}

export { getRedisClient }
